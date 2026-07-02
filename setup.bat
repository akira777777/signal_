@echo off
REM Signal + Telegram Relay - Docker Quick Start
REM Usage:
REM   setup.bat link      - Start Signal QR linking
REM   setup.bat start     - Start all services (signal-api + dashboard)
REM   setup.bat scheduler - Start reminder scheduler (sends messages)
REM   setup.bat cloudflare - Start with Cloudflare tunnel
REM   setup.bat logs      - Tail logs
REM   setup.bat down      - Stop all services

setlocal enabledelayedexpansion
set CMD=%1

if "%CMD%"=="" (
    echo.
    echo Signal + Telegram Relay - Docker Compose
    echo.
    echo Usage:
    echo   setup.bat link              - Start QR linking wizard (link Signal account^)
    echo   setup.bat start             - Start Signal API + Dashboard
    echo   setup.bat scheduler         - Start scheduler (sends reminders^)
    echo   setup.bat cloudflare        - Start with Cloudflare tunnel
    echo   setup.bat logs              - View logs
    echo   setup.bat down              - Stop all services
    echo.
    echo After linking: run "setup.bat scheduler" to start automatic reminders
    echo.
    goto :eof
)

if "%CMD%"=="link" (
    echo Starting Signal Device Linker...
    docker compose up --profile link signal-linker -it
    goto :eof
)

if "%CMD%"=="start" (
    echo Starting Signal API and Dashboard...
    docker compose up signal-api dashboard -d
    echo.
    echo Dashboard available at: http://127.0.0.1:8787
    echo Password: 1111
    echo.
    goto :eof
)

if "%CMD%"=="scheduler" (
    echo Starting Reminder Scheduler...
    docker compose up --profile scheduler reminder-scheduler
    goto :eof
)

if "%CMD%"=="cloudflare" (
    echo Starting with Cloudflare Tunnel...
    if not defined CLOUDFLARE_TUNNEL_TOKEN (
        echo ERROR: CLOUDFLARE_TUNNEL_TOKEN not set in .env
        echo Get token from: https://dash.cloudflare.com/?to=/:account/networking/networks
        goto :eof
    )
    docker compose up --profile cloudflare -d
    goto :eof
)

if "%CMD%"=="logs" (
    docker compose logs -f --tail=50
    goto :eof
)

if "%CMD%"=="down" (
    echo Stopping all services...
    docker compose down --remove-orphans
    goto :eof
)

echo Unknown command: %CMD%
