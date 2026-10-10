#!/usr/bin/env python3
"""
Token ledger that the agent cannot touch.

Runs on the PC, between the SSH tunnel and llama-server:

    VM:127.0.0.1:8080  --ssh -R-->  PC:127.0.0.1:8081 (this proxy)  -->  PC:127.0.0.1:8080 (llama-server)

Every /v1/chat/completions call is forwarded unchanged and one JSON line is
appended to the ledger: time, run/worker labels sent by the harness, the
server's usage and timings, and the size of the request. The harness keeps
its own transcripts inside the VM, but the agent runs as root there and
could edit them; this file lives on the PC and is the source of truth for
token counts and GPU time.

Standard library only.

    python3 logproxy.py --listen 8081 --upstream http://127.0.0.1:8080 --ledger ledger.jsonl
"""
import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()


def make_handler(upstream: str, ledger: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet
            pass

        def _forward(self, method: str):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ("host", "content-length", "connection", "accept-encoding")}
            req = urllib.request.Request(upstream + self.path, data=body, method=method, headers=headers)
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=3600) as r:
                    status, data, rheaders = r.status, r.read(), r.headers
            except urllib.error.HTTPError as e:
                status, data, rheaders = e.code, e.read(), e.headers
            except Exception as e:  # upstream down: tell the client, log it
                status, data, rheaders = 502, json.dumps({"error": str(e)}).encode(), {}
            t1 = time.time()

            if self.path.startswith("/v1/chat/completions"):
                row = {"t_start": t0, "t_end": t1, "status": status,
                       "run": self.headers.get("X-Bench-Run"), "worker": self.headers.get("X-Bench-Worker"),
                       "request_bytes": len(body or b"")}
                try:
                    resp = json.loads(data)
                    row["usage"] = resp.get("usage")
                    row["timings"] = resp.get("timings")
                    row["model"] = resp.get("model")
                    choice = (resp.get("choices") or [{}])[0]
                    row["finish_reason"] = choice.get("finish_reason")
                    row["n_tool_calls"] = len((choice.get("message") or {}).get("tool_calls") or [])
                except Exception:
                    row["unparsed_response_bytes"] = len(data)
                with LOCK, open(ledger, "a") as f:
                    f.write(json.dumps(row) + "\n")

            self.send_response(status)
            ctype = rheaders.get("Content-Type", "application/json") if rheaders else "application/json"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self._forward("POST")

        def do_GET(self):
            self._forward("GET")

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=8081)
    ap.add_argument("--upstream", default="http://127.0.0.1:8080")
    ap.add_argument("--ledger", default="ledger.jsonl")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.listen), make_handler(a.upstream.rstrip("/"), a.ledger))
    print(f"logproxy 127.0.0.1:{a.listen} -> {a.upstream}, ledger {a.ledger}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
