# Start a local Hardhat node, deploy LoanRelief, and serve the API and the frontend.
# Closing this window stops the API and kills the node and the frontend this script started.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Contracts = Join-Path $Root "contracts"
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "backend\.venv is missing. From backend/: py -3.11 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt"
}

function Test-Listen([int]$Port) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

function Show-Busy([int]$Port) {
    Write-Host "127.0.0.1:${Port} is already in use."
    Write-Host "See which process: netstat -ano | findstr :${Port}"
    Write-Host "Stop it: taskkill /PID <pid> /F"
}

function Show-Urls {
    Write-Host ""
    Write-Host "Frontend  http://127.0.0.1:5173"
    Write-Host "API       http://127.0.0.1:8000"
    Write-Host "RPC       http://127.0.0.1:8545"
    Write-Host ""
}

$ChainBusy = Test-Listen 8545
$ApiBusy = Test-Listen 8000
$WebBusy = Test-Listen 5173
if ($ChainBusy) { Show-Busy 8545 }
if ($ApiBusy) { Show-Busy 8000 }
if ($WebBusy) {
    Show-Busy 5173
    Write-Host "Leaving the process on port 5173 alone."
}
if ($ChainBusy -or $ApiBusy) {
    Show-Urls
    exit 1
}

$Node = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npx hardhat node > node.log 2>&1" `
    -WorkingDirectory $Contracts `
    -PassThru `
    -WindowStyle Hidden

$Web = $null
try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Listen 8545) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Show-Urls
        Write-Error "Hardhat did not open port 8545. See contracts\node.log"
    }

    Push-Location $Contracts
    npx hardhat run scripts/deploy.ts --network localhost
    if ($LASTEXITCODE -ne 0) {
        throw "Deploy failed."
    }
    Pop-Location

    $env:RPC_URL = "http://127.0.0.1:8545"
    # Public Hardhat account #1. It only has coins on this local node.
    $env:ORACLE_PRIVATE_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
    $env:DEPLOYMENT_PATH = Join-Path $Backend "chain\deployment.json"

    if (-not $WebBusy) {
        $Web = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "npm run dev" `
            -WorkingDirectory $Frontend `
            -PassThru `
            -WindowStyle Hidden
    }

    Show-Urls

    Push-Location $Backend
    & $Python -m uvicorn app.main:app --port 8000
} finally {
    if ($Web -and -not $Web.HasExited) {
        taskkill /T /F /PID $Web.Id | Out-Null
    }
    if ($Node -and -not $Node.HasExited) {
        taskkill /T /F /PID $Node.Id | Out-Null
    }
}
