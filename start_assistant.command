#!/bin/zsh
# Double-click to start the Grill House assistant. Keeps the Mac awake until this window is closed.
cd "$(dirname "$0")" || exit 1

if [ ! -f .env ] || ! grep -q '^GRILLHOUSE_PASSWORD=' .env; then
  echo "First time setup: choose a password for the chat page (at least 8 characters)."
  read -rs "password?Password: "; echo
  echo "GRILLHOUSE_PASSWORD=$password" >> .env
  chmod 600 .env
fi

open -a Ollama
echo "Starting the AI model..."
curl -s --retry 20 --retry-connrefused --retry-delay 2 -o /dev/null http://localhost:11434/api/version || {
  echo "Ollama didn't start. Open the Ollama app and try again."; read -k1; exit 1; }

( curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://localhost:8501/ && open http://localhost:8501 ) &

# 0.0.0.0 lets devices on your Tailscale network connect; the app refuses every other network
GRILLHOUSE_HOST=0.0.0.0 caffeinate -i .venv/bin/python src/web_chat.py
echo "Assistant stopped. You can close this window."
