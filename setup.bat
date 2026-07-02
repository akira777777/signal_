@echo off
REM =============================================================================
REM Signal + Telegram Relay - Docker Orchestration
REM =============================================================================

setlocal enabledelayedexpansion
set "CMD=%~1"
set "ARG2=%~2"
echo DEBUG: CMD is "%CMD%", arg1 is "%~1"
if "%CMD%"=="" (
    echo.
    echo =============================================================================
    echo  Signal + Telegram Relay - Docker Compose Orchestrator
    echo =============================================================================
    echo.
    echo Commands:
    echo.
    echo   setup.bat link               Link Signal account via QR code
    echo   setup.bat up                 Start Signal API + Dashboard
    echo   setup.bat scheduler          Start reminder scheduler [sends reminders]
    echo   setup.bat cloudflare         Start with Cloudflare tunnel [public access]
    echo   setup.bat cf-setup           Configure Cloudflare domain interactively
    echo   setup.bat logs [service]     Show logs [default: all services]
    echo   setup.bat ps                 List running containers
    echo   setup.bat down               Stop all services
    echo   setup.bat clean              Remove all containers, volumes, networks
    echo.
    echo Quick Start Workflow:
    echo   1. setup.bat up              - Start the core services
    echo   2. setup.bat link            - Link your Signal account
    echo   3. setup.bat cf-setup        - Configure public Cloudflare domain
    echo   4. setup.bat cloudflare      - Start tunnel with public access
    echo   5. setup.bat scheduler       - Start automatic reminders
    echo.
    echo Dashboard (Local):  http://127.0.0.1:8788 [Password: 1111]
    echo.
    goto :eof
)

if /i "%CMD%"=="link" (
    echo.
    echo [*] Starting Signal Device Linker...
    echo [*] Make sure Signal Desktop is closed on your phone
    echo [*] Open Signal on your phone and go to Settings ^> Linked Devices
    echo [*] Click "Add Device" and scan the QR code when it appears
    echo.
    docker compose up --profile link signal-linker -it
    if errorlevel 1 (
        echo [!] Linking failed. Make sure:
        echo     - Signal API is running
        echo     - Dashboard is running
        echo     - Signal is open on your phone
        exit /b 1
    )
    echo [+] Device linked successfully!
    goto :eof
)

if /i "%CMD%"=="up" (
    echo.
    echo [*] Starting Signal API and Dashboard...
    
    set "TOKEN="
    set "HOSTNAME="
    if exist .env (
        for /f "tokens=2 delims==" %%A in ('findstr /I "CLOUDFLARE_TUNNEL_TOKEN" .env 2^>nul') do (
            set "TOKEN=%%A"
        )
        for /f "tokens=2 delims==" %%A in ('findstr /I "CLOUDFLARE_TUNNEL_HOSTNAME" .env 2^>nul') do (
            set "HOSTNAME=%%A"
        )
    )
    
    if not "!TOKEN!"=="" (
        echo [*] Custom Cloudflare Tunnel Token detected. Starting named tunnel...
        docker compose --profile cloudflare up signal-api dashboard cloudflare-tunnel -d
        if errorlevel 1 (
            echo [!] Failed to start services
            exit /b 1
        )
        timeout /t 5 /nobreak
        echo.
        echo [+] Services started successfully!
        echo.
        echo Local Dashboard:  http://127.0.0.1:8788
        if not "!HOSTNAME!"=="" (
            echo Public Dashboard: https://!HOSTNAME!
        )
        echo Password:         1111
        echo.
    ) else (
        echo [*] No Custom Cloudflare Tunnel Token detected. Starting Cloudflare Quick Tunnel...
        docker compose --profile cloudflare-quick up signal-api dashboard cloudflare-quick-tunnel -d
        if errorlevel 1 (
            echo [!] Failed to start services
            exit /b 1
        )
        echo [*] Waiting for Cloudflare Quick Tunnel link...
        timeout /t 8 /nobreak
        
        powershell -NoProfile -Command "
            \$url = ''
            for (\$i = 0; \$i -lt 12; \$i++) {
                \$logs = docker logs signal-quick-tunnel 2>&1
                if (\$logs -match '(https://[a-zA-Z0-9-]+\.trycloudflare\.com)') {
                    \$url = \$Matches[1]
                    break
                }
                Start-Sleep -Seconds 3
            }
            if (\$url) {
                Write-Host ''
                Write-Host '============================================================' -ForegroundColor Green
                Write-Host ' [SUCCESS] Cloudflare Quick Domain Assigned!' -ForegroundColor Green
                Write-Host '============================================================' -ForegroundColor Green
                Write-Host '  Public URL : ' -NoNewline; Write-Host \$url -ForegroundColor Cyan
                Write-Host '  Local URL  : http://127.0.0.1:8788'
                Write-Host '  Password   : ' -NoNewline; Write-Host (if ([System.Environment]::GetEnvironmentVariable('SIGNAL_WEB_PASSWORD')) { \$env:SIGNAL_WEB_PASSWORD } else { '1111' }) -ForegroundColor Yellow
                Write-Host '============================================================' -ForegroundColor Green
                Write-Host ''
                Write-Host 'Tip: share the Public URL with anyone who needs access.' -ForegroundColor DarkGray
                Write-Host ''
            } else {
                Write-Host '[!] Warning: Could not retrieve Cloudflare Quick Domain automatically.' -ForegroundColor Yellow
                Write-Host '    Check logs manually: docker logs signal-quick-tunnel' -ForegroundColor Yellow
                Write-Host '    Local URL: http://127.0.0.1:8788'
            }
        "
    )
    goto :eof
)

if /i "%CMD%"=="scheduler" (
    echo.
    echo [*] Starting Reminder Scheduler...
    echo [*] This will send reminders to Telegram and Signal groups
    echo [*] Press Ctrl+C to stop
    echo.
    docker compose up --profile scheduler reminder-scheduler
    goto :eof
)

if /i "%CMD%"=="cf-setup" (
    echo.
    echo =============================================================================
    echo  Cloudflare Tunnel Setup Wizard
    echo =============================================================================
    echo.
    echo Prerequisites:
    echo   1. Cloudflare account (free at https://dash.cloudflare.com)
    echo   2. Domain name (can be free .tk domain)
    echo   3. Domain added to Cloudflare
    echo.
    pause
    echo.
    echo [*] Step 1: Create Cloudflare API Token
    echo.
    echo   1. Visit: https://dash.cloudflare.com/profile/api-tokens
    echo   2. Click "Create Token"
    echo   3. Use "Edit zone DNS" template, or:
    echo      - Permissions: Zone:DNS:Edit, Zone:Zone:Read, Account:Tunnels:Edit
    echo      - Zone Resources: Your domain
    echo   4. Create and copy token
    echo.
    set /p API_TOKEN="[?] Paste API Token: "
    if "!API_TOKEN!"=="" (
        echo [!] Token required. Exiting.
        exit /b 1
    )
    
    echo.
    echo [*] Step 2: Get Zone ID
    echo.
    echo   1. Visit: https://dash.cloudflare.com
    echo   2. Select your domain
    echo   3. Copy Zone ID (right sidebar, API section)
    echo.
    set /p ZONE_ID="[?] Paste Zone ID: "
    if "!ZONE_ID!"=="" (
        echo [!] Zone ID required. Exiting.
        exit /b 1
    )
    
    echo.
    set /p DOMAIN="[?] Enter full domain for Signal Dashboard (e.g., signal.example.com): "
    if "!DOMAIN!"=="" (
        echo [!] Domain required. Exiting.
        exit /b 1
    )
    
    echo.
    echo [*] Creating Cloudflare Tunnel...
    
    powershell -NoProfile -Command "
        \$api_token = '$API_TOKEN'
        \$zone_id = '$ZONE_ID'
        \$domain = '$DOMAIN'
        
        \$headers = @{
            'Authorization' = 'Bearer ' + \$api_token
            'Content-Type'  = 'application/json'
        }
        
        try {
            # Create tunnel
            \$createResp = Invoke-RestMethod `
                -Uri 'https://api.cloudflare.com/client/v4/accounts/undefined/cfd_tunnel' `
                -Method POST `
                -Headers \$headers `
                -Body (ConvertTo-Json @{'name' = 'signal-relay'}) `
                -ErrorAction Stop
            
            if (\$createResp.success) {
                \$tunnelId = \$createResp.result.id
                Write-Host '[+] Tunnel created: ' \$tunnelId
                
                # Get tunnel token
                \$tokenResp = Invoke-RestMethod `
                    -Uri (\"https://api.cloudflare.com/client/v4/accounts/undefined/cfd_tunnel/\" + \$tunnelId + \"/token\") `
                    -Method GET `
                    -Headers \$headers `
                    -ErrorAction Stop
                
                if (\$tokenResp.success) {
                    \$tunnelToken = \$tokenResp.result
                    Write-Host '[+] Tunnel token generated'
                    
                    # Create DNS CNAME record
                    \$subdomain = \$domain.Split('.')[0]
                    \$dnsBody = @{
                        'type'    = 'CNAME'
                        'name'    = \$subdomain
                        'content' = \$tunnelId + '.cfargotunnel.com'
                        'ttl'     = 1
                        'proxied' = \$true
                    }
                    
                    \$dnsResp = Invoke-RestMethod `
                        -Uri ('https://api.cloudflare.com/client/v4/zones/' + \$zone_id + '/dns_records') `
                        -Method POST `
                        -Headers \$headers `
                        -Body (ConvertTo-Json \$dnsBody) `
                        -ErrorAction Stop
                    
                    if (\$dnsResp.success) {
                        Write-Host '[+] DNS CNAME record created'
                        
                        # Update .env file
                        \$envContent = @\"
`n# Cloudflare Tunnel Configuration`nCLOUDFLARE_TUNNEL_TOKEN=\$tunnelToken`nCLOUDFLARE_TUNNEL_ID=\$tunnelId`nCLOUDFLARE_TUNNEL_HOSTNAME=\$domain`n\"@
                        
                        Add-Content -Path '.env' -Value \$envContent
                        Write-Host '[+] Configuration saved to .env'
                        Write-Host ''
                        Write-Host '============================================================'
                        Write-Host '[SUCCESS] Cloudflare Tunnel Configured'
                        Write-Host '============================================================'
                        Write-Host ''
                        Write-Host 'Public Dashboard URL: https://' \$domain
                        Write-Host ''
                        Write-Host 'Next steps:'
                        Write-Host '  1. Wait 2-3 minutes for DNS to propagate'
                        Write-Host '  2. Run: setup.bat cloudflare'
                        Write-Host '  3. Visit: https://' \$domain
                        Write-Host ''
                    }
                    else {
                        Write-Host '[!] DNS record creation failed'
                        Write-Host \$dnsResp.errors
                        exit 1
                    }
                }
                else {
                    Write-Host '[!] Token generation failed'
                    Write-Host \$tokenResp.errors
                    exit 1
                }
            }
            else {
                Write-Host '[!] Tunnel creation failed'
                Write-Host \$createResp.errors
                exit 1
            }
        }
        catch {
            Write-Host '[!] Error: ' \$_
            exit 1
        }
    "
    if errorlevel 1 (
        echo [!] Cloudflare setup failed. Check your API token and zone ID.
        exit /b 1
    )
    goto :eof
)

if /i "%CMD%"=="cloudflare" (
    REM Check for token in environment or .env
    if not defined CLOUDFLARE_TUNNEL_TOKEN (
        for /f "tokens=2 delims==" %%A in ('findstr /I "CLOUDFLARE_TUNNEL_TOKEN" .env 2^>nul') do (
            set "CLOUDFLARE_TUNNEL_TOKEN=%%A"
        )
    )
    
    if not defined CLOUDFLARE_TUNNEL_TOKEN (
        echo.
        echo [!] Cloudflare tunnel not configured
        echo.
        echo Run: setup.bat cf-setup
        echo.
        exit /b 1
    )
    
    echo.
    echo [*] Starting Cloudflare tunnel...
    docker compose up --profile cloudflare -d
    if errorlevel 1 (
        echo [!] Failed to start tunnel
        exit /b 1
    )
    timeout /t 3 /nobreak
    echo.
    echo [+] Tunnel started!
    echo.
    echo View logs: setup.bat logs cloudflare-tunnel
    echo.
    goto :eof
)

if /i "%CMD%"=="logs" (
    if "%ARG2%"=="" (
        docker compose logs -f --tail=100
    ) else (
        docker compose logs -f --tail=100 %ARG2%
    )
    goto :eof
)

if /i "%CMD%"=="ps" (
    echo.
    docker compose ps -a
    echo.
    goto :eof
)

if /i "%CMD%"=="down" (
    echo.
    echo [*] Stopping all services...
    docker compose down --remove-orphans
    if errorlevel 1 (
        echo [!] Failed to stop services
        exit /b 1
    )
    echo [+] All services stopped
    echo.
    goto :eof
)

if /i "%CMD%"=="clean" (
    echo.
    echo [!] WARNING: This will delete all containers, volumes, and networks!
    echo.
    set /p confirm="Continue? (y/N): "
    if /i not "%confirm%"=="y" (
        echo Cancelled.
        goto :eof
    )
    echo.
    echo [*] Removing all containers, volumes, networks...
    docker compose down -v --remove-orphans
    if errorlevel 1 (
        echo [!] Failed to clean
        exit /b 1
    )
    echo [+] Cleanup complete
    echo.
    goto :eof
)

echo [!] Unknown command: %CMD%
echo Run 'setup.bat' for help
exit /b 1
