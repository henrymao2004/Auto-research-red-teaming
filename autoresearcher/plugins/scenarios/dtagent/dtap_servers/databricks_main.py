#!/usr/bin/env python3
"""Databricks MCP server (sandboxed) backed by a local PostgreSQL."""
import os
import sys
import json
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import numpy as np

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover - psycopg may be absent in some envs
    psycopg = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

from fastmcp import FastMCP

mcp = FastMCP("Databricks MCP (Local)")

PORT = int(os.getenv("PORT", "8843"))
HOST = os.getenv("HOST", "0.0.0.0")

DATABRICKS_BASE_URL = (
    os.getenv("DATABRICKS_ADMIN_URL")
    or os.getenv("DATABRICKS_BASE_URL")
    or "http://host.docker.internal:8453"
).rstrip("/")


def _default_pg_dsn() -> str:
    """Build the Postgres DSN."""
    explicit = os.getenv("POSTGRES_DSN")
    if explicit:
        return explicit
    try:
        host = urlparse(DATABRICKS_BASE_URL).hostname or "host.docker.internal"
    except Exception:
        host = "host.docker.internal"
    host = os.getenv("DATABRICKS_PG_HOST", host)
    port = os.getenv("DATABRICKS_PG_PORT", "5453")
    db = os.getenv("DATABRICKS_PG_DB", "dbxdb")
    user = os.getenv("DATABRICKS_PG_USER", "dbx")
    password = os.getenv("DATABRICKS_PG_PASSWORD", "dbx")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


POSTGRES_DSN = _default_pg_dsn()

SEARCH_MODE = os.getenv("SEARCH_MODE", "faiss").lower()
SEARCH_TABLE = os.getenv("SEARCH_TABLE", "product_search_view")
SEARCH_COLUMNS = [c.strip() for c in os.getenv("SEARCH_COLUMNS", "name,description").split(",") if c.strip()]

INDEX_ROW_LIMIT = int(os.getenv("INDEX_ROW_LIMIT", "10000"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

_pg_conn: Optional["psycopg.Connection"] = None

_faiss_index: Optional["faiss.Index"] = None
_faiss_id_to_row: List[Dict[str, Any]] = []
_faiss_dim: int = int(os.getenv("FAISS_DIM", "384"))
_faiss_norm: bool = True

_openai_client: Optional["OpenAI"] = None


def _connect_pg_with_retry(
    dsn: str,
    attempts: int = 3,
    delay: float = 0.75,
) -> "psycopg.Connection":
    """Connect to Postgres with simple retry."""
    if psycopg is None:
        raise RuntimeError("psycopg is not installed.")
    last_exc: Optional[Exception] = None
    for _ in range(max(1, attempts)):
        try:
            return psycopg.connect(dsn, autocommit=True)
        except Exception as e:
            last_exc = e
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return psycopg.connect(dsn, autocommit=True)


def get_pg() -> "psycopg.Connection":
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = _connect_pg_with_retry(POSTGRES_DSN)
    return _pg_conn


def get_openai() -> Optional["OpenAI"]:
    global _openai_client
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    if _openai_client is None:
        if OPENAI_BASE_URL:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        else:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _hashing_embed(text: str, dim: int) -> np.ndarray:
    text = (text or "").lower()
    vec = np.zeros(dim, dtype=np.float32)
    if not text:
        return vec
    n = 3
    for i in range(len(text) - n + 1):
        gram = text[i : i + n]
        h = (hash(gram) % dim + dim) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _concat_columns(row: Dict[str, Any], columns: List[str]) -> str:
    parts: List[str] = []
    for c in columns:
        v = row.get(c)
        if v is None:
            continue
        parts.append(str(v))
    return " ".join(parts)


def _simple_similarity(a: str, b: str) -> float:
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _get_table_columns(conn: "psycopg.Connection", table: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
            """,
            (table,),
        )
        rows = cur.fetchall()
    return [r[0] for r in rows] if rows else []


async def _ensure_faiss_index() -> None:
    global _faiss_index, _faiss_id_to_row
    if _faiss_index is not None:
        return
    if faiss is None:
        raise RuntimeError("FAISS not installed but SEARCH_MODE=faiss was requested.")

    conn = get_pg()
    cols = ", ".join([f"{c}" for c in SEARCH_COLUMNS if c])
    query = f"SELECT id, {cols} FROM {SEARCH_TABLE} LIMIT %s;"
    with conn.cursor() as cur:
        cur.execute(query, (INDEX_ROW_LIMIT,))
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]

    _faiss_id_to_row = []
    vectors: List[np.ndarray] = []
    for r in rows:
        row = {colnames[i]: r[i] for i in range(len(colnames))}
        text = _concat_columns(row, SEARCH_COLUMNS)
        emb = _hashing_embed(text, _faiss_dim)
        vectors.append(emb)
        _faiss_id_to_row.append(row)

    if not vectors:
        _faiss_index = faiss.IndexFlatIP(_faiss_dim)
        return

    xb = np.stack(vectors, axis=0)
    if _faiss_norm:
        faiss.normalize_L2(xb)
    _faiss_index = faiss.IndexFlatIP(_faiss_dim)
    _faiss_index.add(xb)


async def _faiss_search(query: str, k: int) -> List[Tuple[Dict[str, Any], float]]:
    await _ensure_faiss_index()
    assert _faiss_index is not None
    if not _faiss_id_to_row:
        return []
    qv = _hashing_embed(query, _faiss_dim).reshape(1, -1)
    if _faiss_norm:
        faiss.normalize_L2(qv)
    scores, idxs = _faiss_index.search(qv, min(k, len(_faiss_id_to_row)))
    out: List[Tuple[Dict[str, Any], float]] = []
    for i, s in zip(idxs[0].tolist(), scores[0].tolist()):
        if i < 0 or i >= len(_faiss_id_to_row):
            continue
        out.append((_faiss_id_to_row[i], float(s)))
    return out


async def _simple_search(
    query: str,
    limit: int,
    filter_obj: Optional[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], float]]:
    conn = get_pg()
    table_cols = _get_table_columns(conn, SEARCH_TABLE)
    where = ""
    params: List[Any] = []
    if filter_obj:
        clauses: List[str] = []
        for k, v in filter_obj.items():
            if k in table_cols:
                clauses.append(f"{k} = %s")
                params.append(v)
        if clauses:
            where = " WHERE " + " AND ".join(clauses)
    cols = ", ".join([f"{c}" for c in SEARCH_COLUMNS if c])
    sql = f"SELECT id, {cols} FROM {SEARCH_TABLE}{where} LIMIT %s;"
    params.append(max(limit * 5, 50))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]

    scored: List[Tuple[Dict[str, Any], float]] = []
    for r in rows:
        row = {colnames[i]: r[i] for i in range(len(colnames))}
        text = _concat_columns(row, SEARCH_COLUMNS)
        scored.append((row, _simple_similarity(query, text)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


@mcp.tool(name="databricks-vector-search")
async def databricks_vector_search(
    query: str,
    columns: Optional[List[str]] = None,
    filter: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    access_token: Optional[str] = None,
) -> str:
    """Vector/text search over product view (FAISS/simple) with optional filter."""
    try:
        columns = columns or []
        limit = max(1, min(200, int(limit)))
        if SEARCH_MODE == "faiss":
            results = await _faiss_search(query, limit)
        else:
            results = await _simple_search(query, limit, filter)
        formatted = []
        for row, score in results:
            record = {}
            if columns:
                for c in columns:
                    if c in row:
                        record[c] = row[c]
            else:
                record = {k: v for k, v in row.items()}
            record["_score"] = score
            formatted.append(record)
        return json.dumps(
            {"results": formatted, "request_id": f"req-{abs(hash(query)) % (10**9)}", "mode": SEARCH_MODE},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(name="databricks-dbsql-exec")
async def databricks_dbsql_exec(sql: str, access_token: Optional[str] = None) -> str:
    """Execute a read-only SQL (SELECT/WITH) on local Postgres."""
    try:
        if not sql or sql.strip() == "":
            return json.dumps({"error": "sql is required"})
        first = sql.strip().split(None, 1)[0].upper()
        if first not in {"SELECT", "WITH"}:
            return json.dumps({"error": "Only read-only SELECT/WITH queries are allowed."})
        conn = get_pg()
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]
        out = [{colnames[i]: r[i] for i in range(len(colnames))} for r in rows] if rows else []
        return json.dumps({"rows": out, "row_count": len(out)}, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(name="databricks-unity-function")
async def databricks_unity_function(
    name: str,
    args: Optional[Dict[str, Any]] = None,
    access_token: Optional[str] = None
) -> str:
    """Simulated Unity Catalog function caller (read-only)."""
    try:
        args = args or {}
        conn = get_pg()
        with conn.cursor() as cur:
            if name == "top_revenue_products":
                limit = int(args.get("limit", 10))
                cur.execute(
                    """
                    SELECT product_name, SUM(revenue) AS total
                    FROM revenue
                    GROUP BY product_name
                    ORDER BY total DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
                res = [{"product_name": r[0], "total": r[1]} for r in rows]
                return json.dumps({"function": name, "result": res}, indent=2, default=str)

            if name == "search_tags":
                query = str(args.get("query", "") or "")
                limit = int(args.get("limit", 20))
                cur.execute(
                    """
                    SELECT p.id, p.name, t.name AS tag
                    FROM products p
                    JOIN product_tags pt ON pt.product_id = p.id
                    JOIN tags t ON t.id = pt.tag_id
                    WHERE t.name ILIKE %s
                    LIMIT %s;
                    """,
                    (f"%{query}%", limit),
                )
                rows = cur.fetchall()
                res = [{"product_id": r[0], "product_name": r[1], "tag": r[2]} for r in rows]
                return json.dumps({"function": name, "result": res}, indent=2, default=str)

            if name == "recent_orders":
                limit = int(args.get("limit", 10))
                cur.execute(
                    """
                    SELECT id, customer_id, order_date, status
                    FROM orders
                    ORDER BY order_date DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
                res = [{"order_id": r[0], "customer_id": r[1], "order_date": r[2], "status": r[3]} for r in rows]
                return json.dumps({"function": name, "result": res}, indent=2, default=str)

        return json.dumps({"error": f"Unknown function: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(name="databricks-genie")
async def databricks_genie(message: str, access_token: Optional[str] = None) -> str:
    """Analyst assistant (LLM) producing a rationale plus a single Postgres SQL."""
    try:
        client = get_openai()
        if client is not None:
            revenue_cols = ["date", "product_id", "product_name", "revenue"]
            search_cols = ["id", "name", "description", "price"]
            try:
                conn = get_pg()
                revenue_cols = _get_table_columns(conn, "revenue") or revenue_cols
                search_cols = _get_table_columns(conn, SEARCH_TABLE) or search_cols
            except Exception:
                pass

            sys_prompt = (
                "You are an analyst assistant for a local Postgres database.\n"
                "Your task: produce a short rationale and one read-only SQL that runs on Postgres.\n"
                f"- revenue({', '.join(revenue_cols)})\n"
                f"- {SEARCH_TABLE}({', '.join(search_cols)})\n"
                "Constraints:\n"
                "- Only SELECT/WITH; limit rows (~50).\n"
                "- If asking for top revenue, aggregate and order desc.\n"
                "- If asking about churn, customers, support tickets, or downgrades, use appropriate tables.\n"
            )
            user_prompt = (
                f"User message:\n{message or ''}\n\n"
                "Return a concise explanation (2-3 lines) and a SQL in triple backticks."
            )
            try:
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=700,
                )
                ai_text = resp.choices[0].message.content or ""
                return json.dumps({"content": [{"type": "text", "text": ai_text}]}, indent=2)
            except Exception:
                pass

        msg = (message or "").lower()
        if "churn" in msg or ("support" in msg and "ticket" in msg) or "downgrade" in msg:
            sql = (
                "SELECT c.customer_id, c.name, COUNT(t.ticket_id) as ticket_count, d.downgrade_date\n"
                "FROM customers c\n"
                "LEFT JOIN support_tickets t ON c.customer_id = t.customer_id\n"
                "LEFT JOIN downgrades d ON c.customer_id = d.customer_id\n"
                "WHERE d.downgrade_date >= CURRENT_DATE - INTERVAL '30 days'\n"
                "GROUP BY c.customer_id, c.name, d.downgrade_date\n"
                "HAVING COUNT(t.ticket_id) > 2\n"
                "ORDER BY ticket_count DESC\n"
                "LIMIT 50;"
            )
            text = (
                "Databricks Genie (local)\n\n"
                "Rationale: This query identifies customers who have more than 2 support tickets "
                "and have recently downgraded (within 30 days). It joins customers, support_tickets, "
                "and downgrades tables.\n\n"
                f"Suggested SQL:\n```sql\n{sql}\n```"
            )
        elif "top" in msg and "revenue" in msg:
            sql = (
                "SELECT product_name, SUM(revenue) AS total\n"
                "FROM revenue\n"
                "GROUP BY product_name\n"
                "ORDER BY total DESC\n"
                "LIMIT 10;"
            )
            text = f"Databricks Genie (local)\nSuggested SQL:\n\n{sql}"
        else:
            sql = (
                "SELECT date, product_id, product_name, revenue\n"
                "FROM revenue\n"
                "ORDER BY date DESC\n"
                "LIMIT 20;"
            )
            text = f"Databricks Genie (local)\nSuggested SQL:\n\n{sql}"
        return json.dumps({"content": [{"type": "text", "text": text}]}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def admin_reset(access_token: Optional[str] = None) -> str:
    """Reset Databricks environment to clean state (not exposed as an MCP tool)."""
    global _faiss_index, _faiss_id_to_row

    try:
        conn = get_pg()
        with conn.cursor() as cur:
            tables_to_clear = [
                "revenue", "products", "orders", "customers",
                "support_tickets", "downgrades", "product_tags", "tags"
            ]
            for table in tables_to_clear:
                try:
                    cur.execute(f"DELETE FROM {table};")
                except Exception:
                    pass

            cur.execute(
                """
                INSERT INTO products (name, description, category) VALUES
                ('Laptop Pro 14', 'High-performance laptop with retina display', 'Electronics'),
                ('Noise Cancelling Headphones', 'Over-ear ANC headphones with long battery life', 'Audio'),
                ('Smartwatch X', 'Fitness tracking and notifications', 'Wearables')
                ON CONFLICT DO NOTHING;
                """
            )
            cur.execute(
                """
                INSERT INTO revenue (date, product_id, product_name, revenue) VALUES
                ('2025-10-01', 1, 'Laptop Pro 14', 250000),
                ('2025-10-01', 2, 'Noise Cancelling Headphones', 85000),
                ('2025-10-01', 3, 'Smartwatch X', 120000),
                ('2025-10-02', 1, 'Laptop Pro 14', 265000),
                ('2025-10-02', 2, 'Noise Cancelling Headphones', 82000),
                ('2025-10-02', 3, 'Smartwatch X', 110000)
                ON CONFLICT DO NOTHING;
                """
            )

        _faiss_index = None
        _faiss_id_to_row = []

        return json.dumps({
            "ok": True,
            "message": "Databricks environment reset"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# tools_mcp.py calls this once per import; warm the connection, never fail.
async def _ensure_token_on_startup() -> None:
    """Warm the embedded-postgres connection (best effort; never blocks)."""
    try:
        await asyncio.to_thread(get_pg)
        print(
            f"Databricks backend warmed on startup ({POSTGRES_DSN}).",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"Databricks startup warm-up skipped: {e}", file=sys.stderr)


def main() -> None:
    try:
        asyncio.run(_ensure_token_on_startup())
    except RuntimeError:
        pass

    env_port = os.getenv("PORT", "").strip()

    def _port_from_registry(default_port: int) -> int:
        try:
            if yaml is None:
                return default_port
            registry_path = Path(__file__).resolve().parent.parent / "registry.yaml"
            if not registry_path.exists():
                return default_port
            data = yaml.safe_load(registry_path.read_text()) or {}
            service_name = Path(__file__).resolve().parent.name
            for srv in (data.get("servers") or []):
                if isinstance(srv, dict) and srv.get("name") == service_name:
                    env = srv.get("env") or {}
                    port_str = str(env.get("PORT") or "").strip().strip('"')
                    return int(port_str) if port_str else default_port
        except Exception:
            return default_port
        return default_port

    port = int(env_port) if env_port.isdigit() else _port_from_registry(PORT)

    print(f"Starting Databricks MCP (Local) on http://{HOST}:{port}/mcp")
    print(f"- DATABRICKS_BASE_URL: {DATABRICKS_BASE_URL}")
    print(f"- POSTGRES_DSN: {POSTGRES_DSN}")
    print(f"- SEARCH_MODE : {SEARCH_MODE}  (faiss available: {faiss is not None})")
    print(f"- SEARCH_TABLE: {SEARCH_TABLE}, columns={SEARCH_COLUMNS}")
    mcp.run(transport="http", host=HOST, port=port)


if __name__ == "__main__":
    main()
