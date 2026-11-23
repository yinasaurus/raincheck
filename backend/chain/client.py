"""Thin web3.py wrapper around the LoanRelief contract.

Rules: never fake a chain result and never silently skip a call. If the node is down we raise
ChainUnavailable (the API maps that to HTTP 503); if the contract rejects a call we raise
ChainRevert with the decoded custom error name.

Config (env, all optional for local dev):
  RPC_URL               default http://127.0.0.1:8545
  DEPLOYMENT_PATH       default <this dir>/deployment.json (written by contracts/scripts/deploy.ts)
  ORACLE_PRIVATE_KEY    required on any non-local chain. On the local Hardhat chain (id 31337) we fall
                        back to Hardhat's PUBLIC test account #1. Never use that key anywhere real.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError, Web3Exception

HARDHAT_LOCAL_CHAIN_ID = 31337
HARDHAT_ACCOUNT_1_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"  # public test key
DEFAULT_DEPLOYMENT = Path(__file__).with_name("deployment.json")
RELIEF_KINDS = {"REDUCTION": 0, "DEFERRAL": 1}


class ChainUnavailable(RuntimeError):
    """Node unreachable or contract not deployed."""


class ChainRevert(RuntimeError):
    """The contract rejected the call. `.error` is the custom error name, `.args_` its arguments."""

    def __init__(self, error: str, args_: tuple = ()):
        super().__init__(f"{error}{args_ if args_ else ''}")
        self.error = error
        self.args_ = args_


def _error_table(abi: list[dict]) -> dict[bytes, tuple[str, list[str]]]:
    table = {}
    for item in abi:
        if item.get("type") == "error":
            types = [i["type"] for i in item.get("inputs", [])]
            sig = f"{item['name']}({','.join(types)})"
            table[function_signature_to_4byte_selector(sig)] = (item["name"], types)
    return table


class LoanReliefClient:
    def __init__(self, rpc_url: str | None = None, deployment_path: str | Path | None = None, private_key: str | None = None):
        self.rpc_url = rpc_url or os.getenv("RPC_URL", "http://127.0.0.1:8545")
        path = Path(deployment_path or os.getenv("DEPLOYMENT_PATH", DEFAULT_DEPLOYMENT))
        if not path.exists():
            raise ChainUnavailable(f"No deployment file at {path}. Deploy the contract first (see README).")
        self.deployment = json.loads(path.read_text())
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10}))
        try:
            connected = self.w3.is_connected()
        except Exception as exc:  # noqa: BLE001
            raise ChainUnavailable(f"Cannot reach chain node at {self.rpc_url}: {exc}") from exc
        if not connected:
            raise ChainUnavailable(f"Cannot reach chain node at {self.rpc_url}. Is the Hardhat node running?")
        self.chain_id = self.w3.eth.chain_id
        if self.chain_id != self.deployment["chainId"]:
            raise ChainUnavailable(
                f"Node chain id {self.chain_id} does not match deployment ({self.deployment['chainId']}). Redeploy."
            )
        address = Web3.to_checksum_address(self.deployment["address"])
        if not self.w3.eth.get_code(address):
            raise ChainUnavailable(f"No contract code at {address}. The node was probably restarted: redeploy.")
        self.abi = self.deployment["abi"]
        self.contract = self.w3.eth.contract(address=address, abi=self.abi)
        self._errors = _error_table(self.abi)

        key = private_key or os.getenv("ORACLE_PRIVATE_KEY")
        if not key:
            if self.chain_id == HARDHAT_LOCAL_CHAIN_ID:
                key = HARDHAT_ACCOUNT_1_KEY
            else:
                raise ChainUnavailable("ORACLE_PRIVATE_KEY is required on a non-local chain.")
        self.account = self.w3.eth.account.from_key(key)
        if self.account.address.lower() != str(self.deployment["oracle"]).lower():
            raise ChainUnavailable(
                f"Signing account {self.account.address} is not the contract's oracle {self.deployment['oracle']}."
            )

    # ------------------------------------------------------------------ plumbing
    def _decode_revert(self, exc: Exception) -> ChainRevert:
        data = getattr(exc, "data", None)
        if isinstance(data, dict):  # some nodes wrap it: {"message": ..., "data": "0x..."}
            data = data.get("data")
        if not isinstance(data, str):
            for arg in exc.args:  # fall back to scanning args (str or dict forms)
                cand = arg.get("data") if isinstance(arg, dict) else arg
                if isinstance(cand, str) and cand.startswith("0x"):
                    data = cand
                    break
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 10:
            raw = bytes.fromhex(data[2:])
            entry = self._errors.get(raw[:4])
            if entry:
                name, types = entry
                vals = abi_decode(types, raw[4:]) if types else ()
                return ChainRevert(name, tuple(vals))
        return ChainRevert("UnknownRevert", (str(exc),))

    def _send(self, fn) -> dict[str, Any]:
        """Dry-run first (so we get a decoded revert reason), then sign and send."""
        try:
            fn.call({"from": self.account.address})
        except (ContractCustomError, ContractLogicError) as exc:
            raise self._decode_revert(exc) from exc
        except Web3Exception as exc:
            raise ChainUnavailable(str(exc)) from exc
        try:
            tx = fn.build_transaction(
                {"from": self.account.address, "nonce": self.w3.eth.get_transaction_count(self.account.address)}
            )
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        except (ContractCustomError, ContractLogicError) as exc:
            raise self._decode_revert(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise ChainUnavailable(f"Transaction failed: {exc}") from exc
        if receipt["status"] != 1:
            raise ChainRevert("TransactionFailed")
        return {"tx_hash": tx_hash.hex() if tx_hash.hex().startswith("0x") else "0x" + tx_hash.hex(), "receipt": receipt}

    def _named(self, fn_name: str, values) -> dict | list[dict]:
        fn_abi = next(i for i in self.abi if i.get("type") == "function" and i["name"] == fn_name)
        comps = fn_abi["outputs"][0]["components"]
        names = [c["name"] for c in comps]
        if fn_abi["outputs"][0]["type"].endswith("[]"):
            return [dict(zip(names, v)) for v in values]
        return dict(zip(names, values))

    # -------------------------------------------------------------------- writes
    def create_loan(self, borrower: str, principal_cents: int, annual_rate_bps: int, term_months: int,
                    trigger_tenths_mm: int, max_reduction_bps: int, max_deferral_months: int) -> dict:
        fn = self.contract.functions.createLoan(
            Web3.to_checksum_address(borrower), principal_cents, annual_rate_bps, term_months,
            trigger_tenths_mm, max_reduction_bps, max_deferral_months,
        )
        sent = self._send(fn)
        logs = self.contract.events.LoanCreated().process_receipt(sent["receipt"])
        return {"loan_id": int(logs[0]["args"]["loanId"]), "tx_hash": sent["tx_hash"],
                "block_number": sent["receipt"]["blockNumber"]}

    def apply_relief(self, loan_id: int, season_id: int, observed_tenths_mm: int, kind: str, value: int,
                     evidence_hash: str) -> dict:
        if kind not in RELIEF_KINDS:
            raise ValueError(f"kind must be one of {list(RELIEF_KINDS)}")
        raw = bytes.fromhex(evidence_hash[2:] if evidence_hash.startswith("0x") else evidence_hash)
        fn = self.contract.functions.applyRelief(loan_id, season_id, observed_tenths_mm, RELIEF_KINDS[kind], value, raw)
        sent = self._send(fn)
        return {"tx_hash": sent["tx_hash"], "block_number": sent["receipt"]["blockNumber"],
                "gas_used": sent["receipt"]["gasUsed"]}

    def record_payment(self, loan_id: int, amount_cents: int) -> dict:
        sent = self._send(self.contract.functions.recordPayment(loan_id, amount_cents))
        return {"tx_hash": sent["tx_hash"]}

    # --------------------------------------------------------------------- reads
    def get_loan(self, loan_id: int) -> dict:
        try:
            return self._named("getLoan", self.contract.functions.getLoan(loan_id).call())
        except (ContractCustomError, ContractLogicError) as exc:
            raise self._decode_revert(exc) from exc

    def get_history(self, loan_id: int) -> list[dict]:
        try:
            rows = self._named("getReliefHistory", self.contract.functions.getReliefHistory(loan_id).call())
        except (ContractCustomError, ContractLogicError) as exc:
            raise self._decode_revert(exc) from exc
        kinds = {v: k for k, v in RELIEF_KINDS.items()}
        out = []
        for r in rows:
            r = dict(r)
            r["reliefType"] = kinds[r["reliefType"]]
            r["dataSourceHash"] = "0x" + bytes(r["dataSourceHash"]).hex()
            out.append(r)
        return out

    def season_relieved(self, loan_id: int, season_id: int) -> bool:
        return bool(self.contract.functions.seasonRelieved(loan_id, season_id).call())
