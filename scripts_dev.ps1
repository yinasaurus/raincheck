# Windows PowerShell: start a local chain, deploy the contract, start the API.
# NOTE: untested on Windows from my side. The node+deploy commands are the ones verified on Linux.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\contracts"
if (-not (Test-Path node_modules)) { npm install --legacy-peer-deps }
$node = Start-Process -FilePath "npx.cmd" -ArgumentList "hardhat","node" -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput "$root\.hardhat-node.log"
try {
  for ($i = 0; $i -lt 40; $i++) {
    try { Invoke-RestMethod -Uri http://127.0.0.1:8545 -Method Post -ContentType "application/json" `
          -Body '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' | Out-Null; break } catch { Start-Sleep 1 }
  }
  npx.cmd hardhat run scripts/deploy.ts --network localhost
  Set-Location "$root\backend"
  Write-Host "API on http://127.0.0.1:8000  (docs at /docs)"
  .\.venv\Scripts\python -m uvicorn app.main:app --port 8000
} finally { Stop-Process -Id $node.Id -Force -ErrorAction SilentlyContinue }
