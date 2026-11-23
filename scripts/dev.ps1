# Start a local Hardhat node, deploy LoanRelief, and serve the API.
# Closing this window stops the API and kills the node.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Contracts = Join-Path $Root "contracts"
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "backend\.venv is missing. From backend/: py -3.11 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt"
}

function Test-Port {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", 8545)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

if (Test-Port) {
    Write-Error "127.0.0.1:8545 is already in use. Stop that process, then run scripts\dev.ps1 again."
}

$Node = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npx hardhat node > node.log 2>&1" `
    -WorkingDirectory $Contracts `
    -PassThru `
    -WindowStyle Hidden

try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
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

    Write-Host ""
    Write-Host "API docs  http://127.0.0.1:8000/docs"
    Write-Host "RPC       http://127.0.0.1:8545"
    Write-Host "Demo      POST http://127.0.0.1:8000/api/demo/run  {`"year`": 2004}"
    Write-Host ""

    Push-Location $Backend
    & $Python -m uvicorn app.main:app --port 8000
} finally {
    if ($Node -and -not $Node.HasExited) {
        taskkill /T /F /PID $Node.Id | Out-Null
    }
}
