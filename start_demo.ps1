# Install dependencies
Write-Host "Installing Node.js dependencies..." -ForegroundColor Green
pnpm install

Write-Host "Installing Python dependencies..." -ForegroundColor Green
Push-Location server/face-recognition
pip install -r requirements.txt
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
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd server/face-recognition ; python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4"

# Start Frontend
Write-Host "Starting React frontend..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "pnpm run dev"

Write-Host "All services have been started successfully!" -ForegroundColor Green
