"""A password-protected chat page for the assistant, served from this computer.

Run from the project root:
    GRILLHOUSE_PASSWORD=choose-one python -m ui.web_chat

Then open http://localhost:8501. Set GRILLHOUSE_HOST=0.0.0.0 to let other devices reach it (for example over
Tailscale). The password can also live in a .env file in the project root (git-ignored), as
GRILLHOUSE_PASSWORD=... on its own line.
"""

import hmac
import ipaddress
import json
import os
import secrets
import sys
import threading
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import chatbot, config  # noqa: F401  (config loads .env)


HOST = os.environ.get("GRILLHOUSE_HOST", "127.0.0.1")
PORT = int(os.environ.get("GRILLHOUSE_PORT", "8501"))
PASSWORD = os.environ.get("GRILLHOUSE_PASSWORD", "")
COOKIE = "grillhouse_session"
MAX_FAILED_LOGINS = 10  # per run, then the page locks until restarted
# Only this computer and devices on your private Tailscale network may connect, even when listening on 0.0.0.0
ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128", "100.64.0.0/10", "fd7a:115c:a1e0::/48")]

sessions: dict[str, list[dict]] = {}  # session token -> conversation history
failed_logins = 0
model_lock = threading.Lock()  # the local model answers one question at a time


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grill House Assistant</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/static/icon-192.png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#c2410c">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Grill House">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>
  :root {
    --bg: #f6f5f2; --surface: #ffffff; --ink: #1b1b19; --muted: #6b6a66; --line: #e3e1db;
    --accent: #c2410c; --accent-ink: #ffffff; --bot: #ffffff; --me: #c2410c; --me-ink: #ffffff;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141413; --surface: #1d1d1b; --ink: #f1efea; --muted: #a3a19a; --line: #2e2d2a;
      --accent: #f97316; --accent-ink: #141413; --bot: #232321; --me: #9a3412; --me-ink: #fff7ed;
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         display: flex; flex-direction: column; }
  header { padding: calc(14px + env(safe-area-inset-top)) 16px 14px; border-bottom: 1px solid var(--line); background: var(--surface);
           display: flex; align-items: baseline; gap: 10px; }
  header h1 { font-size: 17px; margin: 0; }
  header span { color: var(--muted); font-size: 13px; }
  main { flex: 1; overflow-y: auto; padding: 16px; }
  .wrap { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }
  .msg { padding: 10px 14px; border-radius: 14px; max-width: 85%; white-space: pre-wrap; overflow-wrap: anywhere; }
  .bot { background: var(--bot); border: 1px solid var(--line); align-self: flex-start; border-bottom-left-radius: 4px; }
  .me { background: var(--me); color: var(--me-ink); align-self: flex-end; border-bottom-right-radius: 4px; }
  .thinking { color: var(--muted); font-style: italic; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
  .chips button { border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 999px;
                  padding: 6px 12px; font: inherit; font-size: 14px; cursor: pointer; }
  .chips button:hover { border-color: var(--accent); }
  form.ask { padding: 12px 16px calc(12px + env(safe-area-inset-bottom)); border-top: 1px solid var(--line); background: var(--surface); }
  form.ask .wrap { flex-direction: row; gap: 8px; }
  input { flex: 1; min-width: 0; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px;
          background: var(--bg); color: var(--ink); font: inherit; }
  input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  button.send { padding: 0 18px; border: 0; border-radius: 12px; background: var(--accent); color: var(--accent-ink);
                font: inherit; font-weight: 600; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .login { margin: auto; width: min(360px, calc(100% - 32px)); background: var(--surface); border: 1px solid var(--line);
           border-radius: 16px; padding: 24px; display: flex; flex-direction: column; gap: 12px; }
  .login h1 { font-size: 20px; margin: 0; }
  .login p { margin: 0; color: var(--muted); font-size: 14px; }
  .error { color: #dc2626; font-size: 14px; min-height: 1.2em; }
</style>
</head>
<body>
<div id="app"></div>
<script>
const app = document.getElementById("app");
const examples = ["Which night is busiest?", "What should I prep for Saturday night?",
                  "What do customers complain about?", "What's the forecast for next month?"];

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function showLogin(message = "") {
  document.body.innerHTML = "";
  const form = el("form", { class: "login" });
  form.append(el("h1", {}, "Grill House Assistant"), el("p", {}, "Enter the password to continue."));
  const pw = el("input", { type: "password", autocomplete: "current-password", placeholder: "Password", required: "" });
  const err = el("div", { class: "error" }, message);
  form.append(pw, el("button", { class: "send", type: "submit", style: "padding:12px" }, "Sign in"), err);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const r = await fetch("/login", { method: "POST", body: JSON.stringify({ password: pw.value }) });
    if (r.ok) showChat(); else err.textContent = (await r.json()).error;
  };
  document.body.append(form);
  pw.focus();
}

function showChat() {
  document.body.innerHTML = "";
  const header = el("header");
  header.append(el("h1", {}, "Grill House Assistant"), el("span", {}, "Uber Eats data · runs privately"));
  const main = el("main"), log = el("div", { class: "wrap" });
  main.append(log);
  const form = el("form", { class: "ask" }), row = el("div", { class: "wrap" });
  const input = el("input", { placeholder: "Ask about sales, menu, hours, reviews…", autocomplete: "off" });
  const send = el("button", { class: "send", type: "submit" }, "Send");
  row.append(input, send); form.append(row);
  document.body.append(header, main, form);

  const add = (cls, text) => { const m = el("div", { class: "msg " + cls }, text); log.append(m); main.scrollTop = main.scrollHeight; return m; };
  add("bot", "Hi! Ask me anything about the shop's Uber Eats sales, menu, busy times, reviews or forecast.");
  const chips = el("div", { class: "chips" });
  for (const q of examples) { const b = el("button", { type: "button" }, q); b.onclick = () => ask(q); chips.append(b); }
  log.append(chips);

  async function ask(question) {
    chips.remove();
    add("me", question);
    input.value = ""; input.disabled = send.disabled = true;
    const reply = add("bot thinking", "Thinking… (this can take up to 30 seconds)");
    try {
      const r = await fetch("/ask", { method: "POST", body: JSON.stringify({ question }) });
      if (r.status === 401) return showLogin("Session expired. Please sign in again.");
      if (!r.ok) throw new Error((await r.json()).error);
      const reader = r.body.getReader(), decoder = new TextDecoder();
      let text = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        text += decoder.decode(value, { stream: true });
        reply.classList.remove("thinking");
        reply.textContent = text.replace(/\\*\\*/g, "");
        main.scrollTop = main.scrollHeight;
      }
      if (!text) reply.textContent = "No answer came back. Please try again.";
    } catch (err) {
      reply.classList.remove("thinking");
      reply.textContent = "Sorry, something went wrong: " + err.message;
    } finally {
      input.disabled = send.disabled = false; input.focus();
    }
  }
  form.onsubmit = (e) => { e.preventDefault(); const q = input.value.trim(); if (q) ask(q); };
  input.focus();
}

fetch("/session").then(r => r.ok ? showChat() : showLogin());
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
</script>
</body>
</html>
"""


STATIC = Path(__file__).parent / "static"
MANIFEST = json.dumps({
    "name": "Grill House Assistant", "short_name": "Grill House", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#f6f5f2", "theme_color": "#c2410c",
    "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}).encode()
# Answers need the Mac, so the service worker only makes the page installable; it never caches
SERVICE_WORKER = b"self.addEventListener('fetch', () => {});"


class StreamWriter:
    """Lets chatbot.answer() stream its reply straight into the HTTP response."""

    def __init__(self, wfile):
        self.wfile = wfile

    def write(self, text: str) -> None:
        self.wfile.write(text.encode())

    def flush(self) -> None:
        self.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    retriever: chatbot.Retriever

    def log_message(self, fmt, *args):  # keep the terminal quiet apart from errors
        pass

    def allowed(self) -> bool:
        address = ipaddress.ip_address(self.client_address[0].removeprefix("::ffff:"))
        if any(address in network for network in ALLOWED_NETWORKS):
            return True
        self.send_json(403, {"error": "Not allowed from this network."})
        return False

    def token(self) -> str | None:
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        value = jar[COOKIE].value if COOKIE in jar else None
        return value if value in sessions else None

    def send_json(self, status: int, payload: dict, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = min(int(self.headers.get("Content-Length", 0)), 10_000)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def send_bytes(self, body: bytes, content_type: str, cache: str = "no-cache") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return
        path = self.path.split("?")[0]
        static_file = STATIC / path.removeprefix("/static/")
        if path == "/manifest.webmanifest":
            self.send_bytes(MANIFEST, "application/manifest+json")
        elif path == "/sw.js":
            self.send_bytes(SERVICE_WORKER, "text/javascript")
        elif path.startswith("/static/") and static_file.suffix == ".png" and static_file.parent == STATIC and static_file.exists():
            self.send_bytes(static_file.read_bytes(), "image/png", "max-age=86400")
        elif path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/session":
            self.send_json(200 if self.token() else 401, {})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        global failed_logins
        if not self.allowed():
            return
        if self.path == "/login":
            if failed_logins >= MAX_FAILED_LOGINS:
                return self.send_json(429, {"error": "Too many wrong passwords. Restart the assistant to try again."})
            if not hmac.compare_digest(str(self.read_json().get("password", "")).encode(), PASSWORD.encode()):
                failed_logins += 1
                return self.send_json(401, {"error": "Wrong password."})
            token = secrets.token_urlsafe(32)
            sessions[token] = []
            cookie = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"
            return self.send_json(200, {}, {"Set-Cookie": cookie})

        if self.path == "/ask":
            token = self.token()
            if not token:
                return self.send_json(401, {"error": "Please sign in."})
            question = str(self.read_json().get("question", "")).strip()[:500]
            if not question:
                return self.send_json(400, {"error": "Empty question."})
            # No Content-Length: the reply streams until the connection closes
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                with model_lock:
                    chatbot.answer(question, self.retriever, sessions[token], stream_to=StreamWriter(self.wfile))
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser went away mid-answer
            except Exception as err:  # e.g. Ollama not running
                self.wfile.write(f"\n[Error: {err}]".encode())
            return

        self.send_json(404, {"error": "Not found"})


def main() -> None:
    if len(PASSWORD) < 8:
        sys.exit("Set a password of at least 8 characters: add GRILLHOUSE_PASSWORD=... to the .env file.")
    chatbot.check_ollama()
    sections = chatbot.build_knowledge()
    if not sections:
        sys.exit(f"No knowledge found in {chatbot.DATA}/. Run the clean, analyse and forecast scripts first.")
    Handler.retriever = chatbot.Retriever(sections)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Grill House assistant running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
