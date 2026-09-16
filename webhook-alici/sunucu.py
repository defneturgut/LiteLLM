"""
WEBHOOK ALICI -- LiteLLM'in "alerting: webhook" modunun nereye POST attigini
canli gormek icin. Gercek bir Slack/Discord/Teams workspace'e ihtiyac yok --
LiteLLM ham JSON POST atiyor (litellm/integrations/SlackAlerting/slack_alerting.py
-> send_webhook_alert), biz de sadece o POST'u kabul edip ekrana basiyoruz.

Bagimlilik yok -- stdlib http.server, python:3-alpine imajinda calisir.
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # varsayilan erisim loglarini bastir, kendi formatimizi kullaniyoruz

    def do_POST(self):
        uzunluk = int(self.headers.get("Content-Length", 0))
        govde = self.rfile.read(uzunluk)
        damga = time.strftime("%H:%M:%S")
        print(f"\n{'=' * 64}", flush=True)
        print(f"[{damga}] WEBHOOK GELDI -- {self.path}", flush=True)
        try:
            veri = json.loads(govde)
            print(json.dumps(veri, indent=2, ensure_ascii=False), flush=True)
        except json.JSONDecodeError:
            print(govde.decode("utf-8", errors="replace"), flush=True)
        print(f"{'=' * 64}\n", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "alindi"}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"webhook-alici calisiyor")


if __name__ == "__main__":
    sunucu = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("[webhook-alici] dinleniyor: 0.0.0.0:8080/webhook", flush=True)
    sunucu.serve_forever()
