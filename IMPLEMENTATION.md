# Implementation Guide - Public Signal + Telegram Relay

Complete walkthrough for deploying your Signal + Telegram relay with public Cloudflare access.

## Timeline

| Step | Task | Time |
|------|------|------|
| 1 | Prepare Cloudflare domain | 5-10 min |
| 2 | Start Docker services | 1 min |
| 3 | Link Signal account | 10 min |
| 4 | Configure Cloudflare tunnel | 3 min |
| 5 | Start public access | 2-5 min |
| 6 | Configure reminders | 5 min |
| 7 | Test & monitor | 5 min |

**Total: ~30-35 minutes**

---

## Step 1: Prepare Cloudflare Domain

### Option A: Use Existing Domain

If you already have a domain:

```bash
# 1. Go to: https://dash.cloudflare.com
# 2. Click "Add a site"
# 3. Enter your domain
# 4. Follow Cloudflare's setup
# 5. Update nameservers at your registrar
# 6. Wait for DNS propagation (can take 24h)
```

### Option B: Get Free Domain

```bash
# 1. Visit: https://freenom.com
# 2. Search for domain (e.g., "signal-relay")
# 3. Choose free TLD: .tk, .ml, .ga, .cf
# 4. Register for free (12 months)
# 5. Add to Cloudflare (see Option A, step 2-5)
```

**Verify setup:**
```bash
nslookup your-domain.com
# Should show Cloudflare nameservers:
# NS1.CLOUDFLARE.COM
# NS2.CLOUDFLARE.COM
```

---

## Step 2: Start Docker Services

```bash
# Start core services
setup.bat up

# Verify they're running
setup.bat ps

# Expected output:
# signal-api         running
# signal-dashboard   running
```

Wait ~30 seconds for services to become healthy.

Test local access:
```bash
# In browser: http://127.0.0.1:8788
# Username: (leave blank, just password)
# Password: 1111
```

---

## Step 3: Link Signal Account

This requires Signal app on your phone.

```bash
# Start linker
setup.bat link

# On your phone:
# 1. Open Signal
# 2. Settings → Linked Devices
# 3. Click "Add Device"
# 4. Wait for QR code in command window
# 5. Scan QR code
# 6. Wait for confirmation (~1 minute)

# Expected output:
# ✓ УСТРОЙСТВО ПРИВЯЗАНО: [your-signal-number]
```

If QR doesn't appear:
- Ensure Signal API container is running: `setup.bat ps`
- Check logs: `setup.bat logs signal-api`
- Make sure Signal app is open on phone before starting

---

## Step 4: Configure Cloudflare Tunnel

```bash
# Run interactive setup
setup.bat cf-setup

# Follow prompts:
# 1. Provide Cloudflare API Token
#    - Get from: https://dash.cloudflare.com/profile/api-tokens
#    - Use "Edit zone DNS" template
# 2. Provide Zone ID
#    - Found in dashboard when you select your domain
# 3. Confirm your domain
#    - Should be: signal-relay.example.com (or your choice)

# Wait for completion
# Expected output:
# [SUCCESS] Cloudflare Tunnel Configured
# Public Dashboard URL: https://signal-relay.example.com
```

The script will:
- ✅ Create tunnel automatically
- ✅ Generate tunnel token
- ✅ Create DNS CNAME record
- ✅ Update `.env` file

---

## Step 5: Start Public Tunnel

```bash
# Start tunnel
setup.bat cloudflare

# Expected output:
# [+] Tunnel started!
```

Wait 2-5 minutes for DNS to propagate:

```bash
# Check tunnel status
nslookup signal-relay.example.com
# Should resolve to: 104.16.x.x (Cloudflare edge)

# Check if reachable
curl https://signal-relay.example.com -I
# Should return: HTTP/1.1 200 OK
```

---

## Step 6: Test Public Access

### From Local Network

```bash
# In browser: https://signal-relay.example.com
# Or: https://signal-relay.example.com/status

# You should see Signal Dashboard login
# Password: 1111
```

### From Phone (or Different Network)

```bash
# Open browser on different device
# Visit: https://signal-relay.example.com
# Should load your Signal Dashboard
```

If it doesn't work:
- Check tunnel is running: `docker compose ps`
- View logs: `setup.bat logs cloudflare-tunnel`
- Wait longer (DNS can take 10 minutes)

---

## Step 7: Configure Reminders

### Setup Message Content

Edit `message.txt`:
```bash
# Example message:
Join our Signal group! 
New updates every day.
```

### Setup Schedule & Credentials

Edit `reminder_config.json`:

```json
{
  "message_text_file": "message.txt",
  "min_interval_minutes": 30,
  "max_interval_minutes": 60,
  
  "telegram": {
    "enabled": true,
    "api_id": 38690162,
    "api_hash": "238a5673...",
    "session_dir": "./sessions",
    "folder_name": "Your Folder Name"
  },
  
  "signal": {
    "enabled": true,
    "dashboard_url": "http://signal-api:8080",
    "password": "1111"
  }
}
```

### Start Scheduler

```bash
# Start sending reminders
setup.bat scheduler

# Watch logs in real-time
# Ctrl+C to stop
```

---

## Step 8: Monitor & Maintain

### Daily Monitoring

```bash
# Check services are running
setup.bat ps

# View recent logs
setup.bat logs

# Check specific service
setup.bat logs cloudflare-tunnel
setup.bat logs reminder-scheduler
```

### Weekly Tasks

- [ ] Verify public access works
- [ ] Check reminder message delivery
- [ ] Review logs for errors
- [ ] Monitor Cloudflare bandwidth

### Monthly Tasks

- [ ] Refresh Cloudflare API token (if expiring)
- [ ] Review Cloudflare analytics
- [ ] Rotate dashboard password
- [ ] Update message content if needed

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Your Computer (Windows)                                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  setup.bat (CLI Interface)                                  │
│      ├─ link       → QR device linker                       │
│      ├─ up         → Start services                         │
│      ├─ cf-setup   → Configure domain                       │
│      ├─ cloudflare → Start tunnel                           │
│      ├─ scheduler  → Send reminders                         │
│      └─ logs       → Monitor                                │
│                                                              │
│  Docker Compose Network                                    │
│  ┌─────────────────────────────────────┐                   │
│  │ signal-api (bbernhard/rest-api)    │                   │
│  │ :8080                               │                   │
│  └──────────────┬──────────────────────┘                   │
│                 │                                           │
│  ┌──────────────▼──────────────────┐                       │
│  │ signal-dashboard (signal-web)  │                       │
│  │ :8788 (local) / :8787 (internal)                       │
│  └──────────────┬──────────────────┘                       │
│                 │                                           │
│  ┌──────────────▼──────────────────────────┐               │
│  │ cloudflare-tunnel (Secure Tunnel)      │               │
│  │ → signal-relay.example.com             │               │
│  │ → https://api.cloudflare.com           │               │
│  └──────────────┬──────────────────────────┘               │
│                 │                                           │
│  ┌──────────────▼──────────────────┐                       │
│  │ reminder-scheduler (Python)    │                       │
│  │ Sends to Telegram & Signal     │                       │
│  └───────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
                   │
        ┌──────────┼──────────────┐
        │          │              │
    Local Users  Internet Users Signal API
    :8788        https://domain   WebSocket
```

---

## Troubleshooting

### Can't access dashboard locally

```bash
# Check services
docker compose ps

# If stopped, start them
setup.bat up

# Check dashboard logs
setup.bat logs signal-dashboard

# Test connectivity
docker exec signal-api curl http://signal-dashboard:8787

# Try different port
# Edit docker-compose.yml line: "127.0.0.1:8788:8787"
# Change to: "127.0.0.1:8789:8787"
```

### Can't access dashboard publicly

```bash
# Check tunnel is running
docker compose ps cloudflare-tunnel

# Verify DNS resolution
nslookup signal-relay.example.com

# Test tunnel directly
docker compose logs cloudflare-tunnel

# Wait for DNS (can take 10 minutes)
```

### Reminders not sending

```bash
# Check scheduler is running
setup.bat ps reminder-scheduler

# View scheduler logs
setup.bat logs reminder-scheduler

# Verify Signal account is linked
# (Dashboard should show "Connected")

# Check Telegram credentials
# (Verify api_id, api_hash in reminder_config.json)
```

### High memory usage

```bash
# Check current usage
docker stats

# If > 500MB, increase limits:
# Edit docker-compose.yml
# Increase mem_limit values
# Restart: setup.bat down && setup.bat up
```

---

## Security Hardening

### Change Dashboard Password

```bash
# 1. Edit .env or docker-compose.yml
# 2. Change: SIGNAL_WEB_PASSWORD=1111  →  "YourSecurePassword"
# 3. Restart: setup.bat down && setup.bat up
```

### Rotate Cloudflare Token

```bash
# 1. Visit: https://dash.cloudflare.com/profile/api-tokens
# 2. Create new token (use same permissions)
# 3. Edit .env: CLOUDFLARE_TUNNEL_TOKEN=new_token
# 4. Restart tunnel: setup.bat down
# 5. Delete old token from Cloudflare dashboard
# 6. Restart: setup.bat cloudflare
```

### Firewall Setup (Optional)

```bash
# If running on server, restrict access
# Allow: Only Docker bridge network + Cloudflare IPs

# Get Cloudflare IPs: https://www.cloudflare.com/ips/

# Example Windows Firewall:
# netsh advfirewall firewall add rule name="Cloudflare" `
#   dir=in action=allow remoteip=173.245.48.0/20
```

---

## Backup & Recovery

### Backup Configuration

```bash
# 1. Backup .env
copy .env .env.backup

# 2. Backup Signal data (important!)
docker cp signal-api:/home/.local/share/signal-cli backup/

# 3. Backup reminders config
copy reminder_config.json reminder_config.json.backup
```

### Restore Configuration

```bash
# 1. Restore .env
copy .env.backup .env

# 2. Restore Signal data
docker cp backup/signal-cli signal-api:/home/.local/share/

# 3. Restart services
setup.bat down && setup.bat up
```

---

## Performance Tips

1. **Use Cloudflare Cache**
   - Dashboard → Caching → Cache everything
   - Set Browser TTL: 1 hour

2. **Monitor Bandwidth**
   - Cloudflare → Analytics → Traffic
   - Set rate limits if needed

3. **Optimize Message Size**
   - Keep videos < 50MB
   - Compress images before sending

4. **Schedule Off-Peak**
   - Send reminders during off-peak hours
   - Reduces server load

---

## Next Steps

1. ✅ Domain ready? → **setup.bat cf-setup**
2. ✅ Signal linked? → **setup.bat cloudflare**
3. ✅ Tunnel active? → **setup.bat scheduler**
4. ✅ Reminders sending? → Monitor and celebrate! 🎉

---

## Support & Documentation

- **Docker Docs**: https://docs.docker.com
- **Cloudflare Docs**: https://developers.cloudflare.com/cloudflare-one/
- **Signal Protocol**: https://signal.org/docs/
- **This Guide**: See CLOUDFLARE_SETUP.md for advanced options
