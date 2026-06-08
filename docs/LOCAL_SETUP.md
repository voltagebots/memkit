# Local setup — run memkit as an always-on service (macOS)

This is how to adopt memkit as your personal memory backend behind an MCP client
(e.g. Claude Code), with the server kept alive by `launchd`.

## 1. Build and install the binaries

```bash
go build -o ~/.memkit/memkit     ./cmd/memkit
go build -o ~/.memkit/memkit-mcp ./cmd/memkit-mcp
```

## 2. Run memkit via launchd

Create `~/Library/LaunchAgents/com.voltagebots.memkit.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.voltagebots.memkit</string>
  <key>ProgramArguments</key><array><string>/Users/YOU/.memkit/memkit</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>MEMKIT_ADDR</key><string>127.0.0.1:8420</string>
    <key>MEMKIT_DB</key><string>/Users/YOU/.memkit/memkit.db</string>
    <key>MEMKIT_API_KEYS</key><string>pilot-key:local</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/YOU/.memkit/memkit.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/.memkit/memkit.log</string>
</dict>
</plist>
```

Bound to `127.0.0.1` so it's reachable only from this machine. Load it:

```bash
launchctl load -w ~/Library/LaunchAgents/com.voltagebots.memkit.plist
curl -s localhost:8420/healthz   # {"status":"ok"}
```

## 3. Register the MCP bridge

```bash
claude mcp add memkit --scope user \
  -e MEMKIT_URL=http://localhost:8420 \
  -e MEMKIT_API_KEY=pilot-key \
  -e MEMKIT_USER=you \
  -- ~/.memkit/memkit-mcp
```

Reconnect the client (in Claude Code: `/mcp`) and the `remember` / `recall` tools appear.

## Managing the service

```bash
launchctl list | grep memkit                 # status
launchctl unload ~/Library/LaunchAgents/com.voltagebots.memkit.plist   # stop
tail -f ~/.memkit/memkit.log                 # logs
```

To upgrade: rebuild the binary, then `launchctl kickstart -k gui/$(id -u)/com.voltagebots.memkit`.

The DB at `~/.memkit/memkit.db` persists across restarts and upgrades.
