"""Connection-resilient HTTP for dtap judge verification.

Judges query backend services (salesforce/gmail/slack/github/...) to verify
the victim agent's actions. Under eval load a backend can transiently drop a
connection ("Remote end closed connection without response"); the bare
http.client calls did not retry, so one drop made the check raise and the
judge defaulted to no-break (false negative). This wraps the
connect->request->getresponse->read cycle with bounded retries on transient
connection errors. The verification queries are read-only, and a dropped
connection means no response was processed, so retrying is safe.
"""
from __future__ import annotations

import http.client
import time

_RETRYABLE = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def resilient_send(host, port, method, url, headers=None, body=None, *,
                   timeout=30, retries=3, backoff=0.5, https=False):
    """Connect, send one request, return (status:int, data:bytes).

    Retries up to `retries` times with exponential backoff on transient
    connection errors. Raises the last exception if all attempts fail.
    """
    headers = headers or {}
    last = None
    for attempt in range(retries):
        conn = None
        try:
            cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
            conn = cls(host, port, timeout=timeout)
            if body is not None:
                conn.request(method, url, body=body, headers=headers)
            else:
                conn.request(method, url, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data
        except _RETRYABLE as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    raise last
