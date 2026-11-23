# RainCheck: chain layer

What this adds: a Solidity contract (`contracts/`), a Python chain client, repayment-schedule maths and
evidence hashing (`backend/chain/`), with tests. It does not touch `ml/`, the labels or the trained models.

## Run the tests
Contract (37 tests):
    cd contracts && npm install --legacy-peer-deps && npx hardhat test

Backend schedule + evidence tests (no chain needed):
    cd backend && pip install -r requirements-chain.txt && pytest tests/test_schedule.py tests/test_evidence.py

Live-chain tests (client + oracle, 11 tests; skipped automatically when no node is running):
    # terminal 1
    cd contracts && npx hardhat node
    # terminal 2
    cd contracts && npx hardhat run scripts/deploy.ts --network localhost
    cd ../backend && pytest tests/test_chain_integration.py tests/test_oracle.py

One command, from the raincheck directory: `./scripts/dev.sh` (macOS/Linux) or `.\scripts\dev.ps1` (Windows).

## Units (everywhere, on-chain and off)
- rainfall: integer **tenths of a millimetre** (1363.0 mm = 13630)
- percentages: **basis points** (30% = 3000)
- money: integer **cents**
Daily rainfall is stored at 0.1 mm precision (Open-Meteo's native precision) so hashing is exact.

## Contract rules (LoanRelief.sol)
- Only the oracle can call `applyRelief`; only the owner can change the oracle.
- Relief requires observed season rainfall STRICTLY below the loan's trigger (equal = no relief).
- Reductions are capped cumulatively across the loan (design decision, not in the original spec).
  Deferrals are capped cumulatively too.
- At most one relief per loan per season id, and an evidence hash can be used once per loan.
- The contract holds no weather data and no ML. It enforces limits and keeps an auditable history.

## Schedule rules (backend/chain/schedule.py)
- Baseline: standard monthly annuity.
- REDUCTION: next 3 installments are cut by the given %, unpaid part stays in the balance, then the
  balance is re-amortised over the remaining installments. Term unchanged.
- DEFERRAL: next M installments are skipped, interest is capitalised, loan ends M months later.
- Relief never forgives debt: the final installment always clears the balance.
- Relief windows may not overlap and must start inside the original term.

## Known limits (say these in the submission)
- The chain proves WHAT evidence was submitted, not that the weather data is true (oracle problem).
- Local Hardhat chain only. Nobody but your machine runs it.
- The oracle key in local mode is Hardhat's public test key. Never use it on a real network.
