#!/usr/bin/env bash
# Start a local Hardhat node, deploy LoanRelief, and serve the API and the frontend.
# Exit (Ctrl-C) stops the API and kills the node and the frontend this script started.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "backend/.venv is missing. From backend/: python3.11 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

port_open() {
  "$PYTHON" -c "import socket,sys; s=socket.create_connection(('127.0.0.1', int(sys.argv[1])), 0.3); s.close()" "$1" >/dev/null 2>&1
}

show_busy() {
  echo "127.0.0.1:$1 is already in use." >&2
  echo "See which process: lsof -nP -iTCP:$1 -sTCP:LISTEN" >&2
  echo "Stop it: kill <pid>" >&2
}

show_urls() {
  echo
  echo "Frontend  http://127.0.0.1:5173"
  echo "API       http://127.0.0.1:8000"
  echo "RPC       http://127.0.0.1:8545"
  echo
}

CHAIN_BUSY=0
API_BUSY=0
WEB_BUSY=0
if port_open 8545; then CHAIN_BUSY=1; show_busy 8545; fi
if port_open 8000; then API_BUSY=1; show_busy 8000; fi
if port_open 5173; then
  WEB_BUSY=1
  show_busy 5173
  echo "Leaving the process on port 5173 alone." >&2
fi
if [[ "$CHAIN_BUSY" -eq 1 || "$API_BUSY" -eq 1 ]]; then
  show_urls
  exit 1
fi

cd "$ROOT/contracts"
npx hardhat node > node.log 2>&1 &
NODE_PID=$!
WEB_PID=""
cleanup() {
  if [[ -n "${WEB_PID}" ]]; then
    kill "$WEB_PID" >/dev/null 2>&1 || true
    pkill -P "$WEB_PID" >/dev/null 2>&1 || true
  fi
  kill "$NODE_PID" >/dev/null 2>&1 || true
  pkill -P "$NODE_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 60); do
  if port_open 8545; then
    ready=1
    break
  fi
  sleep 0.5
done
if [[ "$ready" -ne 1 ]]; then
  show_urls
  echo "Hardhat did not open port 8545. See contracts/node.log" >&2
  exit 1
fi

npx hardhat run scripts/deploy.ts --network localhost
cd "$ROOT/backend"
export RPC_URL="http://127.0.0.1:8545"
# Public Hardhat account #1. It only has coins on this local node.
export ORACLE_PRIVATE_KEY="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
export DEPLOYMENT_PATH="$ROOT/backend/chain/deployment.json"
if [[ "$WEB_BUSY" -ne 1 ]]; then
  cd "$ROOT/frontend"
  npm run dev > "$ROOT/frontend/vite.log" 2>&1 &
  WEB_PID=$!
fi
cd "$ROOT/backend"
show_urls
"$PYTHON" -m uvicorn app.main:app --port 8000
