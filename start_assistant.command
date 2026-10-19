#!/bin/zsh
# Double-click to start the Grill House assistant. Keeps the Mac awake until this window is closed.
cd "$(dirname "$0")" || exit 1

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

open -a Ollama
echo "Starting the AI model..."
curl -s --retry 20 --retry-connrefused --retry-delay 2 -o /dev/null http://localhost:11434/api/version || {
  echo "Ollama didn't start. Open the Ollama app and try again."; read -k1; exit 1; }

( curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://localhost:8501/ && open http://localhost:8501 ) &

# 0.0.0.0 lets devices on your Tailscale network connect; the app refuses every other network
GRILLHOUSE_HOST=0.0.0.0 caffeinate -i .venv/bin/python src/web_chat.py
echo "Assistant stopped. You can close this window."
