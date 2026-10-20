#!/bin/zsh
# Double-click to start the Grill House assistant (or just open it, if auto-start is already running it).
cd "$(dirname "$0")/../.." || exit 1  # project root

saved=$(grep '^GRILLHOUSE_PASSWORD=' .env 2>/dev/null | head -1 | cut -d= -f2-)
if [ ${#saved} -lt 8 ]; then
  echo "Choose a password for the chat page (at least 8 characters). You'll type it to sign in."
  while true; do
    read -rs "password?Password: "; echo
    [ ${#password} -ge 8 ] && break
    echo "That's ${#password} characters - please use at least 8."
  done
  # Replace any old password line, keep everything else in .env
  { grep -v '^GRILLHOUSE_PASSWORD=' .env 2>/dev/null; echo "GRILLHOUSE_PASSWORD=$password"; } > .env.tmp && mv .env.tmp .env
  chmod 600 .env
  echo "Password saved."
fi

if curl -s -o /dev/null --max-time 2 http://localhost:8501/; then
  echo "The assistant is already running. Opening it..."
  open http://localhost:8501
  exit 0
fi

open -a Ollama
echo "Starting the AI model..."
curl -s --retry 20 --retry-connrefused --retry-delay 2 -o /dev/null http://localhost:11434/api/version || {
  echo "Ollama didn't start. Open the Ollama app and try again."; read -k1; exit 1; }

( curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://localhost:8501/ && open http://localhost:8501 ) &

# Listens on this Mac only; phones reach it through "tailscale serve" (see README). Keeps the Mac awake until closed.
GRILLHOUSE_ALLOWED_NETWORKS=private caffeinate -is .venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8501 --log-level warning
echo "Assistant stopped. You can close this window."
