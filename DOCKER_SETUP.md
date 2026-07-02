# Signal + Telegram Relay - Docker Setup

Optimized containerized system for automated Signal and Telegram group messaging with Cloudflare tunnel support.

## Features

✅ **Signal Integration** - Automated messaging via Signal REST API  
✅ **Telegram Support** - Multi-session Telegram bot  
✅ **QR Device Linking** - Automatic Signal account binding  
✅ **Cloudflare Tunnel** - Public access without port forwarding  
✅ **Async Scheduling** - Configurable message intervals  
✅ **Production Ready** - Memory limits, health checks, logging  
✅ **Easy CLI** - Simple batch file interface (Windows)  

## Quick Start

### 1. Start Core Services
```bash
setup.bat up
```
Services will run in background. Dashboard available at: **http://127.0.0.1:8788** (Password: 1111)

### 2. Link Signal Account
```bash
setup.bat link
```
Scan the QR code in Signal on your phone → Settings → Linked Devices

### 3. Start Reminders
```bash
setup.bat scheduler
```
Sends configured reminders to Telegram and Signal groups at random intervals.

### 4. View Logs
```bash
setup.bat logs [service]
```

### 5. Stop Services
```bash
setup.bat down
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Compose Orchestration                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐        ┌──────────────────┐           │
│  │  signal-api      │        │ signal-dashboard │           │
│  │  (bbernhard)     │◄──────►│ (signal-web)     │           │
│  │  :8080/8000      │        │ :8788/8787       │           │
│  └──────────────────┘        └──────────────────┘           │
│         ▲                            ▲                      │
│         │                            │                      │
│  ┌──────┴────────────────────────────┴──────┐              │
│  │         Backplane Network (Internal)      │              │
│  └───────────────────────────────────────────┘              │
│                                                              │
│  ┌──────────────────────────────────────────┐              │
│  │  Optional Services (Profiles)             │              │
│  ├──────────────────────────────────────────┤              │
│  │  • signal-linker (--profile link)        │              │
│  │  • cloudflare-tunnel (--profile cloudflare)             │
│  │  • reminder-scheduler (--profile scheduler)             │
│  └──────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables (.env)
```bash
SIGNAL_WEB_PASSWORD=1111                          # Dashboard password
SIGNAL_NUMBER=+420737500587                       # Your Signal number
CLOUDFLARE_TUNNEL_TOKEN=eyJh...                   # Tunnel token (optional)
TELEGRAM_API_ID=12345                             # Telegram API ID
TELEGRAM_API_HASH=abc123...                       # Telegram API hash
```

### Message Configuration (reminder_config.json)
```json
{
  "message_text_file": "message.txt",
  "video_path": "path/to/video.mp4",
  "min_interval_minutes": 30,
  "max_interval_minutes": 60,
  "telegram": {
    "enabled": true,
    "api_id": 12345,
    "api_hash": "abc...",
    "session_dir": "./sessions"
  },
  "signal": {
    "enabled": true,
    "dashboard_url": "http://signal-api:8080",
    "password": "1111"
  }
}
```

## Commands

| Command | Purpose |
|---------|---------|
| `setup.bat link` | QR linking wizard |
| `setup.bat up` | Start Signal API + Dashboard |
| `setup.bat scheduler` | Start reminder scheduler |
| `setup.bat cloudflare` | Start with Cloudflare tunnel |
| `setup.bat logs [svc]` | View logs |
| `setup.bat ps` | List containers |
| `setup.bat down` | Stop all services |
| `setup.bat clean` | Remove volumes & networks |

## Services

### signal-api
- **Image**: `bbernhard/signal-cli-rest-api:0.100-rootless`
- **Port**: 8080 (internal)
- **Status**: Always running
- **Memory**: 512MB limit
- **Health Check**: Every 30s

### signal-dashboard
- **Image**: Custom (built from api-signal)
- **Port**: 8788 (mapped to 8787 internal)
- **Status**: Always running
- **Memory**: 256MB limit
- **Function**: Web UI for group management

### signal-linker
- **Image**: Custom Python 3.11
- **Type**: Optional (--profile link)
- **Purpose**: Device linking via QR code
- **Memory**: 128MB limit

### cloudflare-tunnel
- **Image**: `cloudflare/cloudflared:2025.1.0`
- **Type**: Optional (--profile cloudflare)
- **Purpose**: Public access tunneling
- **Requires**: CLOUDFLARE_TUNNEL_TOKEN in .env

### reminder-scheduler
- **Image**: Custom Python 3.11
- **Type**: Optional (--profile scheduler)
- **Purpose**: Automated message broadcasting
- **Memory**: 256MB limit

## Volumes

| Name | Purpose | Persistence |
|------|---------|-------------|
| `signal-cli-data` | Signal account cache | Persistent |
| `broadcaster-data` | Group/state files | Persistent |

## Networking

- **backplane** (internal): Signal API ↔ Dashboard ↔ Scheduler
- **dashboard-host**: Dashboard ↔ Tunnel ↔ Linker
- **signal-egress**: Signal API → external networks

## Security

- ✅ Non-root users (scheduler, signaller)
- ✅ Read-only volumes where possible
- ✅ Capability dropping
- ✅ PID/Memory limits
- ✅ Internal networks
- ✅ No secrets in Dockerfiles

## Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f signal-api
docker compose logs -f signal-dashboard
docker compose logs -f reminder-scheduler
```

## Troubleshooting

### Dashboard won't start
```bash
docker logs signal-dashboard
# Check Signal API is healthy: docker compose logs signal-api
```

### QR linking fails
```bash
setup.bat link
# Ensure Signal Desktop is closed on phone
# Leave window open for ~10 minutes
```

### Port already in use
```bash
# Change port in docker-compose.yml
# Line: ports: - "127.0.0.1:8788:8787"
netstat -ano | findstr ":8788"
```

### Out of memory
```bash
# Increase limits in docker-compose.yml
# mem_limit: 512m (from 256m)
docker stats
```

## Production Deployment

For production on Linux/cloud:

```bash
# Replace Windows paths with Unix paths
sed -i 's|C:\\Users\\.*\\Desktop\\signal_|/opt/signal-relay|g' .env

# Use explicit image tags (no 'latest')
# Set environment variables from secrets
# Enable Cloudflare tunnel for remote access
# Run as systemd service or Docker Swarm

# Example systemd service:
[Service]
Type=simple
WorkingDirectory=/opt/signal-relay
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always
RestartSec=10
```

## Optimization Summary

- **Multi-stage Docker builds**: Reduced image sizes
- **Layer caching**: Faster rebuilds
- **Health checks**: Automatic restart on failure
- **Resource limits**: Predictable performance
- **Non-root users**: Better security
- **Minimal logging**: Reduced disk I/O
- **Optional profiles**: Load only needed services
- **Internal networks**: Zero external exposure (except dashboard)

## License

Signal REST API: [bbernhard](https://github.com/bbernhard/signal-cli-rest-api)  
This setup: Custom orchestration
