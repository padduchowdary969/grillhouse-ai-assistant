#!/bin/zsh
# Double-click once: the assistant then starts by itself whenever you log in to this Mac, restarts if it
# stops, and keeps the Mac awake while plugged in. Run with "remove" to undo: ./install_autostart.command remove
cd "$(dirname "$0")" || exit 1
PROJECT="$PWD"
LABEL="com.grillhouse.assistant"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/grillhouse-assistant.log"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null

if [ "$1" = "remove" ]; then
  rm -f "$PLIST"
  echo "Auto-start removed."
  exit 0
fi

saved=$(grep '^GRILLHOUSE_PASSWORD=' .env 2>/dev/null | head -1 | cut -d= -f2-)
if [ ${#saved} -lt 8 ]; then
  echo "Set a chat password first: double-click start_assistant.command once, then run this again."
  read -k1; exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string><string>-c</string>
    <string>open -g -a Ollama; exec /usr/bin/caffeinate -is "$PROJECT/.venv/bin/python" -m ui.web_chat</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Auto-start installed. The assistant is starting now (log: $LOG)."
