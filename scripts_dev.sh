#!/usr/bin/env bash
# macOS/Linux: start a local chain, deploy the contract, start the API. Ctrl+C stops everything.
# NOTE: the node+deploy part was tested; the final uvicorn line assumes your app is app.main:app.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/contracts"
[ -d node_modules ] || npm install --legacy-peer-deps
npx hardhat node > "$ROOT/.hardhat-node.log" 2>&1 &
NODE_PID=$!
trap 'kill $NODE_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  curl -s -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' http://127.0.0.1:8545 >/dev/null 2>&1 && break
  sleep 1
done
npx hardhat run scripts/deploy.ts --network localhost
cd "$ROOT/backend"
echo "API on http://127.0.0.1:8000  (docs at /docs)"
python3 -m uvicorn app.main:app --port 8000
