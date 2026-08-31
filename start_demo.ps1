# Install dependencies
Write-Host "Installing Node.js dependencies..." -ForegroundColor Green
pnpm install

Write-Host "Installing Python dependencies..." -ForegroundColor Green
Push-Location server/face-recognition
if (Test-Path ".\.venv\Scripts\pip.exe") {
    & ".\.venv\Scripts\python.exe" -c "import uvicorn, face_recognition, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & ".\.venv\Scripts\pip.exe" install dlib-bin
        & ".\.venv\Scripts\pip.exe" install face-recognition --no-deps
        & ".\.venv\Scripts\pip.exe" install -r requirements.txt
    } else {
        Write-Host "Python dependencies already satisfied." -ForegroundColor Gray
    }
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -m pip install -r requirements.txt
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pip install -r requirements.txt
} else {
    Write-Host "Python/pip not found on PATH or .venv" -ForegroundColor Red
}
Pop-Location

# Start Ganache
Write-Host "Starting Ganache on port 7545..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npx ganache --port 7545 --deterministic --networkId 1337"
Write-Host "Waiting for Ganache to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Migrate smart contracts
Write-Host "Migrating smart contracts..." -ForegroundColor Green
Push-Location server/blockchain
npx truffle migrate --reset
Pop-Location

# Start Backend
Write-Host "Starting Python FastAPI backend..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd server/face-recognition ; if (Test-Path '.\.venv\Scripts\Activate.ps1') { .\.venv\Scripts\Activate.ps1 } ; python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4"

# Start Frontend
Write-Host "Starting React frontend..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "pnpm run dev"

Write-Host "All services have been started successfully!" -ForegroundColor Green
