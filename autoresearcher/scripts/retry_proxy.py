#!/usr/bin/env python3
"""Transient-failure retry proxy for the researcher backbone.

Sits between the orchestrator `claude` and the upstream Anthropic-format
endpoint (default: Moon Bridge's OpenRouter ingress at :38442). OpenRouter
occasionally returns a 502 / drops the stream mid-flight ("502 ... EOF"); the
Anthropic SDK does NOT retry once a stream has started, so the orchestrator
`/loop` hangs. This proxy makes those transient failures invisible:

  claude --(ANTHROPIC_BASE_URL=:38443)--> retry_proxy --> :38442 (moonbridge) --> OpenRouter

Strategy: BUFFER the full upstream response, then validate it, then flush to
the client. Because nothing is forwarded until the upstream call fully
succeeds, the whole request is safe to retry on:
  - connection errors / read EOF (incomplete body)
  - HTTP 5xx status
  - a 200 event-stream that never reached `message_stop` (mid-stream drop)

4xx (real client errors) and complete 2xx are returned as-is. Buffering trades
first-token latency for correctness — fine for an autonomous research loop.

Env:
  RETRY_PROXY_ADDR     listen addr            (default 0.0.0.0:38443)
  RETRY_PROXY_TARGET   upstream base url      (default http://localhost:38442)
  RETRY_PROXY_MAX      max attempts           (default 4)
  RETRY_PROXY_TIMEOUT  per-attempt timeout s  (default 600)
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = os.environ.get("RETRY_PROXY_TARGET", "http://localhost:38442").rstrip("/")
MAX_ATTEMPTS = int(os.environ.get("RETRY_PROXY_MAX", "4"))
TIMEOUT = float(os.environ.get("RETRY_PROXY_TIMEOUT", "600"))
_ADDR = os.environ.get("RETRY_PROXY_ADDR", "0.0.0.0:38443")
HOST, PORT = _ADDR.rsplit(":", 1)

# Drop hop-by-hop headers.
_DROP = {"host", "content-length", "connection", "keep-alive", "proxy-authorization",
         "proxy-authenticate", "te", "trailers", "transfer-encoding", "upgrade"}


def _log(msg: str) -> None:
    sys.stderr.write(f"[retry_proxy] {msg}\n")
    sys.stderr.flush()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # Silence access log.
        pass

    def _relay(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        url = TARGET + self.path
        fwd = {k: v for k, v in self.headers.items() if k.lower() not in _DROP}

        last_err = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=fwd, method=self.command)
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    status = resp.status
                    raw = resp.read()
                    ctype = resp.headers.get("Content-Type", "")
                    rheaders = [(k, v) for k, v in resp.headers.items()
                                if k.lower() not in _DROP]
            except urllib.error.HTTPError as e:
                status = e.code
                raw = e.read() if hasattr(e, "read") else b""
                ctype = e.headers.get("Content-Type", "") if e.headers else ""
                rheaders = [(k, v) for k, v in (e.headers.items() if e.headers else [])
                            if k.lower() not in _DROP]
                if 500 <= status < 600 and attempt < MAX_ATTEMPTS:
                    last_err = f"HTTP {status}"
                    self._backoff(attempt, last_err)
                    continue
                # Pass through final response.
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < MAX_ATTEMPTS:
                    self._backoff(attempt, last_err)
                    continue
                self._fail(502, f"retry_proxy: upstream unreachable after {MAX_ATTEMPTS} tries ({last_err})")
                return

            # Retry incomplete streams.
            if (status == 200 and "event-stream" in ctype
                    and b"message_stop" not in raw and attempt < MAX_ATTEMPTS):
                last_err = "incomplete SSE (no message_stop)"
                self._backoff(attempt, last_err)
                continue

            if attempt > 1:
                _log(f"recovered on attempt {attempt} ({self.command} {self.path})")
            self._send(status, rheaders, raw)
            return

        self._fail(502, f"retry_proxy: exhausted {MAX_ATTEMPTS} attempts ({last_err})")

    def _backoff(self, attempt: int, why: str) -> None:
        wait = min(2 ** (attempt - 1), 8)
        _log(f"attempt {attempt} failed ({why}) — retrying in {wait}s")
        time.sleep(wait)

    def _send(self, status: int, headers, body: bytes) -> None:
        try:
            self.send_response(status)
            sent_len = False
            for k, v in headers:
                if k.lower() == "content-length":
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _fail(self, status: int, msg: str) -> None:
        _log(msg)
        body = ('{"type":"error","error":{"type":"api_error","message":"%s"}}' % msg).encode()
        self._send(status, [("Content-Type", "application/json")], body)

    do_POST = _relay
    do_GET = _relay
    do_DELETE = _relay
    do_PUT = _relay


def main() -> None:
    _log(f"listening on {HOST}:{PORT} -> {TARGET}  (max={MAX_ATTEMPTS}, timeout={TIMEOUT}s)")
    ThreadingHTTPServer((HOST, int(PORT)), Handler).serve_forever()


if __name__ == "__main__":
    main()
