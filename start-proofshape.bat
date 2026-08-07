@echo off
rem ProofShape one-click launcher (Windows). Double-click this file.
rem Needs Docker Desktop: https://www.docker.com/products/docker-desktop/
rem Safe to run repeatedly: first run builds everything (10-20 minutes);
rem later runs start in seconds. Your data survives restarts.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo.
  echo [proofshape] Docker is not installed.
  echo Download Docker Desktop from https://www.docker.com/products/docker-desktop/
  echo install it, open it once, then double-click this file again.
  echo.
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo.
  echo [proofshape] Docker is installed but not running.
  echo Open the Docker Desktop app, wait for it to say "running", then try again.
  echo.
  pause
  exit /b 1
)

if not exist .env (
  echo [proofshape] First run - creating local configuration...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$keys = 'SESSION_SECRET','HMAC_SECRET','API_KEY_PEPPER','DASHBOARD_SESSION_SECRET','MAGIC_LINK_SECRET','AUTH_PROXY_SECRET';" ^
    "$lines = Get-Content '.env.example';" ^
    "$rng = [Security.Cryptography.RandomNumberGenerator]::Create();" ^
    "foreach ($k in $keys) {" ^
    "  $b = New-Object byte[] 32; $rng.GetBytes($b);" ^
    "  $v = [Convert]::ToBase64String($b);" ^
    "  $lines = $lines | ForEach-Object { if ($_ -match ('^' + $k + '=')) { $k + '=' + $v } else { $_ } };" ^
    "};" ^
    "Set-Content -Path '.env' -Value $lines -Encoding ascii"
  if errorlevel 1 (
    echo [proofshape] Could not create .env - send me a screenshot of this window.
    pause
    exit /b 1
  )
  echo [proofshape] Configuration written to .env - keep this file private.
)

echo [proofshape] Building and starting ProofShape (first time takes 10-20 minutes)...
docker compose up -d --build
if errorlevel 1 (
  echo [proofshape] Something went wrong starting the app.
  echo Run:  docker compose logs --tail 50   in this folder and send me the output.
  pause
  exit /b 1
)

echo [proofshape] Waiting for the app to come up...
set tries=0
:waitloop
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:3000/' -TimeoutSec 5) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto ready
if !tries! geq 90 (
  echo [proofshape] The app did not come up in time.
  echo Run:  docker compose logs --tail 50   in this folder and send me the output.
  pause
  exit /b 1
)
timeout /t 10 /nobreak >nul
goto waitloop

:ready
echo [proofshape] ProofShape is running at http://localhost:3000
start "" "http://localhost:3000"
echo [proofshape] First visit: click Sign up, choose any email + password (8+ chars, a letter and a digit).
echo [proofshape] To stop later, run:  docker compose down   (your data is kept)
pause
