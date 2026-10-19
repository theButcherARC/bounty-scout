#!/usr/bin/env python3
"""Local proxy: SDK -> 127.0.0.1:8081 -> OpenRouter (with vault credential).

The OpenMinion SDK talks to this proxy as a plain OpenAI-compatible endpoint
(no auth needed locally). The proxy forwards to OpenRouter, attaching the
stored credential via the surrogate mechanism (swapped by egress authd).
"""
import json
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request

UPSTREAM = "https://openrouter.ai/api/v1"


class ProxyHandler(BaseHTTPRequestHandler):
    def _forward(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        # Strip a leading /v1 (SDK base_url includes it; upstream already has /v1)
        path = self.path
        if path.startswith("/v1/"):
            path = path[3:]
        url = UPSTREAM + path

        # Rewrite SDK model prefix "openai:<id>" -> "<id>" for OpenRouter.
        # Only strip the literal "openai:" prefix; model IDs themselves
        # contain colons (e.g. "cohere/north-mini-code:free").
        if body and path.endswith("/chat/completions"):
            try:
                payload = json.loads(body)
                model = payload.get("model", "")
                if model.startswith("openai:"):
                    payload["model"] = model[len("openai:"):]
                    print(f"REWRITTEN to: {payload['model']}", flush=True, file=sys.stderr)
                    body = json.dumps(payload).encode()
            except Exception as e:
                print(f"rewrite err: {e}", flush=True, file=sys.stderr)

        req = urllib.request.Request(url, data=body, method=self.command)
        # Copy safe headers
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in ("content-type", "accept"):
                req.add_header(k, v)
        req.add_header("HTTP-Referer", "https://muse.ai")
        req.add_header("X-Title", "BountyScout")
        add_surrogate_to_request(req, "custom.openrouter", allowed_hosts=["openrouter.ai"])

        try:
            with urllib.request.build_opener().open(req, timeout=180) as resp:
                data = resp.read()
                self.send_response(resp.status)
                ctype = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            # Log upstream errors for debugging
            print(f"UPSTREAM {e.code}: {err_body[:300]}", flush=True, file=sys.stderr)
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)

    def do_POST(self):
        self._forward()

    def do_GET(self):
        self._forward()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    server = HTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f"proxy listening on 127.0.0.1:{port} -> {UPSTREAM}", flush=True)
    server.serve_forever()
