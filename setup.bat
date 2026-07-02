@echo off
REM ════════════════════════════════════════════════════════════════════════════
REM Signal + Telegram Relay - Docker Orchestration
REM ════════════════════════════════════════════════════════════════════════════
REM
REM Usage:
REM   setup.bat link           - Start QR linking (link Signal account to device)
REM   setup.bat up             - Start Signal API + Dashboard
REM   setup.bat scheduler      - Start reminder scheduler (sends messages)
REM   setup.bat cloudflare     - Start with Cloudflare tunnel (public access)
REM   setup.bat logs [service] - View logs (default: all)
REM   setup.bat ps             - Show running containers
REM   setup.bat down           - Stop all services
REM   setup.bat clean          - Remove containers, networks, volumes
REM

setlocal enabledelayedexpansion
set "CMD=%~1"
set "ARG2=%~2"

if "%CMD%"=="" (
    echo.
    echo ════════════════════════════════════════════════════════════════════════════
    echo  Signal ^+ Telegram Relay - Docker Compose Orchestrator
    echo ════════════════════════════════════════════════════════════════════════════
    echo.
    echo Commands:
    echo.
    echo   setup.bat link               Link Signal account via QR code
    echo   setup.bat up                 Start Signal API + Dashboard
    echo   setup.bat scheduler          Start reminder scheduler ^(sends reminders^)
    echo   setup.bat cloudflare         Start with Cloudflare tunnel ^(public access^)
    echo   setup.bat logs [service]     Show logs ^(default: all services^)
    echo   setup.bat ps                 List running containers
    echo   setup.bat down               Stop all services
    echo   setup.bat clean              Remove all containers, volumes, networks
    echo.
    echo Quick Start Workflow:
    echo   1. setup.bat up              - Start the core services
    echo   2. setup.bat link            - Link your Signal account
    echo   3. setup.bat scheduler       - Start automatic reminders
    echo.
    echo Dashboard:
    echo   http://127.0.0.1:8787        ^(Password: 1111^)
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
    docker compose up signal-api dashboard -d
    if errorlevel 1 (
        echo [!] Failed to start services
        exit /b 1
    )
    timeout /t 5
    echo.
    echo [+] Services started!
    echo.
    echo Dashboard available at: http://127.0.0.1:8787
    echo Password: 1111
    echo.
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

if /i "%CMD%"=="cloudflare" (
    if not defined CLOUDFLARE_TUNNEL_TOKEN (
        echo.
        echo [!] ERROR: CLOUDFLARE_TUNNEL_TOKEN not set in .env
        echo.
        echo To enable Cloudflare tunnel:
        echo   1. Visit: https://dash.cloudflare.com/?to=/:account/networking/networks
        echo   2. Create a tunnel and copy the token
        echo   3. Add to .env: CLOUDFLARE_TUNNEL_TOKEN=your_token_here
        echo   4. Run: setup.bat cloudflare
        echo.
        exit /b 1
    )
    echo.
    echo [*] Starting with Cloudflare Tunnel...
    docker compose up --profile cloudflare -d
    if errorlevel 1 (
        echo [!] Failed to start tunnel
        exit /b 1
    )
    timeout /t 3
    echo [+] Tunnel started. Public URL available via: docker compose logs cloudflare-tunnel
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
