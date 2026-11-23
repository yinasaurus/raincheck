#!/usr/bin/env bash
# Start a local Hardhat node, deploy LoanRelief, and serve the API and the frontend.
# Exit (Ctrl-C) stops the API and kills the node and the frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "backend/.venv is missing. From backend/: python3.11 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

port_open() {
  "$PYTHON" -c "import socket; s=socket.create_connection(('127.0.0.1',8545),0.3); s.close()" >/dev/null 2>&1
}

if port_open; then
  echo "127.0.0.1:8545 is already in use. Stop that process, then run scripts/dev.sh again." >&2
  exit 1
fi

cd "$ROOT/contracts"
npx hardhat node > node.log 2>&1 &
NODE_PID=$!
WEB_PID=""
cleanup() {
  if [[ -n "$WEB_PID" ]]; then
    kill "$WEB_PID" >/dev/null 2>&1 || true
    pkill -P "$WEB_PID" >/dev/null 2>&1 || true
  fi
  kill "$NODE_PID" >/dev/null 2>&1 || true
  pkill -P "$NODE_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 60); do
  if port_open; then
    ready=1
    break
  fi
  sleep 0.5
done
if [[ "$ready" -ne 1 ]]; then
  echo "Hardhat did not open port 8545. See contracts/node.log" >&2
  exit 1
fi

npx hardhat run scripts/deploy.ts --network localhost
cd "$ROOT/backend"
export RPC_URL="http://127.0.0.1:8545"
# Public Hardhat account #1. It only has coins on this local node.
export ORACLE_PRIVATE_KEY="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
export DEPLOYMENT_PATH="$ROOT/backend/chain/deployment.json"
cd "$ROOT/frontend"
npm run dev > "$ROOT/frontend/vite.log" 2>&1 &
WEB_PID=$!
cd "$ROOT/backend"
echo
echo "Frontend  http://127.0.0.1:5173"
echo "API       http://127.0.0.1:8000"
echo "RPC       http://127.0.0.1:8545"
echo
"$PYTHON" -m uvicorn app.main:app --port 8000
