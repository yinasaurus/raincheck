"""web3 client for LoanRelief.

The connection is opened on the first call, not at import. A stopped node
raises ChainUnavailable. A contract revert raises ChainRevert. This module
never invents a transaction hash and never logs the oracle key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from web3.exceptions import Web3Exception

from chain.errors import ChainUnavailable, ChainRevert
from data.paths import BACKEND_ROOT

# Hardhat's published account #1. It is a public test key. It is used only
# when the RPC is the local node and no ORACLE_PRIVATE_KEY is set.
LOCAL_RPCS = {"http://127.0.0.1:8545", "http://localhost:8545"}
LOCAL_ORACLE_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

RELIEF_TYPES = {"REDUCTION": 0, "DEFERRAL": 1}
RELIEF_NAMES = {0: "REDUCTION", 1: "DEFERRAL"}

_ENV_LOADED = False


def _load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_dotenv(BACKEND_ROOT.parent / ".env", override=False)
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    _ENV_LOADED = True


def _deployment_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    _load_env()
    raw = os.environ.get("DEPLOYMENT_PATH", "").strip()
    if not raw:
        return Path(__file__).resolve().parent / "deployment.json"
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_ROOT.parent / path
    return path


def _rpc_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    _load_env()
    return os.environ.get("RPC_URL", "http://127.0.0.1:8545").strip()


def _oracle_key(explicit: str | None, rpc_url: str) -> str:
    if explicit:
        return explicit
    _load_env()
    key = os.environ.get("ORACLE_PRIVATE_KEY", "").strip()
    if key:
        return key
    if rpc_url.rstrip("/") in LOCAL_RPCS:
        return LOCAL_ORACLE_KEY
    raise ChainUnavailable(
        "ORACLE_PRIVATE_KEY is not set. The public Hardhat key is used only for http://127.0.0.1:8545."
    )


def _node_down_message(rpc_url: str) -> str:
    return (
        f"The Hardhat node is not running at {rpc_url}. "
        "From the repo root run scripts/dev.ps1 (or scripts/dev.sh), "
        "or in contracts/ run `npx hardhat node` and then "
        "`npx hardhat run scripts/deploy.ts --network localhost`."
    )


class ChainClient:
    def __init__(
        self,
        rpc_url: str | None = None,
        private_key: str | None = None,
        deployment_path: Path | None = None,
    ) -> None:
        self.rpc_url = _rpc_url(rpc_url)
        self._private_key = _oracle_key(private_key, self.rpc_url)
        self.deployment_path = _deployment_path(deployment_path)
        self._web3: Web3 | None = None
        self._contract = None
        self._account = None

    def _ready(self):
        if self._contract is not None:
            return self._web3, self._contract, self._account
        if not self.deployment_path.exists():
            raise ChainUnavailable(
                f"No deployment file at {self.deployment_path}. "
                "Deploy LoanRelief to the local node before calling the chain."
            )
        try:
            deployment = json.loads(self.deployment_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ChainUnavailable(f"{self.deployment_path} is not valid JSON.") from exc
        address = deployment.get("address")
        abi = deployment.get("abi")
        if not address or abi is None:
            raise ChainUnavailable(f"{self.deployment_path} is missing address or abi.")
        web3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 4}))
        try:
            connected = web3.is_connected()
        except Exception as exc:
            raise ChainUnavailable(_node_down_message(self.rpc_url)) from exc
        if not connected:
            raise ChainUnavailable(_node_down_message(self.rpc_url))
        self._web3 = web3
        self._account = Account.from_key(self._private_key)
        self._contract = web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        return self._web3, self._contract, self._account

    def create_loan(
        self,
        borrower: str,
        principal_cents: int,
        annual_rate_bps: int,
        term_months: int,
        trigger_rainfall_tenths_mm: int,
        max_reduction_bps: int,
        max_deferral_months: int,
    ) -> dict:
        _, contract, _ = self._ready()
        receipt = self._send(
            contract.functions.createLoan(
                Web3.to_checksum_address(borrower),
                int(principal_cents),
                int(annual_rate_bps),
                int(term_months),
                int(trigger_rainfall_tenths_mm),
                int(max_reduction_bps),
                int(max_deferral_months),
            )
        )
        logs = contract.events.LoanCreated().process_receipt(receipt)
        if not logs:
            raise ChainRevert("createLoan mined but LoanCreated was missing.")
        return {"loan_id": int(logs[0]["args"]["loanId"]), "tx_hash": _tx_hex(receipt["transactionHash"])}

    def apply_relief(
        self,
        loan_id: int,
        observed_rainfall_tenths_mm: int,
        relief_type: str,
        relief_value: int,
        data_source_hash: str,
        season_id: int,
    ) -> dict:
        _, contract, _ = self._ready()
        kind = RELIEF_TYPES.get(str(relief_type).upper())
        if kind is None:
            raise ValueError("relief_type must be REDUCTION or DEFERRAL")
        receipt = self._send(
            contract.functions.applyRelief(
                int(loan_id),
                int(observed_rainfall_tenths_mm),
                kind,
                int(relief_value),
                _bytes32(data_source_hash),
                int(season_id),
            )
        )
        return {"tx_hash": _tx_hex(receipt["transactionHash"])}

    def get_loan(self, loan_id: int) -> dict:
        _, contract, _ = self._ready()
        try:
            raw = contract.functions.getLoan(int(loan_id)).call()
        except Web3Exception as exc:
            raise self._as_revert(exc) from exc
        return _loan_dict(int(loan_id), raw)

    def get_history(self, loan_id: int) -> list[dict]:
        _, contract, _ = self._ready()
        try:
            rows = contract.functions.getReliefHistory(int(loan_id)).call()
        except Web3Exception as exc:
            raise self._as_revert(exc) from exc
        return [_relief_dict(row) for row in rows]

    def record_payment(self, loan_id: int, amount_cents: int) -> dict:
        _, contract, _ = self._ready()
        receipt = self._send(contract.functions.recordPayment(int(loan_id), int(amount_cents)))
        return {"tx_hash": _tx_hex(receipt["transactionHash"])}

    def _send(self, function):
        web3, contract, account = self._ready()
        try:
            function.call({"from": account.address})
        except Web3Exception as exc:
            raise self._as_revert(exc) from exc
        transaction = function.build_transaction(
            {
                "from": account.address,
                "nonce": web3.eth.get_transaction_count(account.address, "pending"),
                "chainId": web3.eth.chain_id,
            }
        )
        signed = account.sign_transaction(transaction)
        raw = getattr(signed, "raw_transaction", None)
        if raw is None:
            raw = signed.rawTransaction
        sent = web3.eth.send_raw_transaction(raw)
        receipt = web3.eth.wait_for_transaction_receipt(sent)
        if receipt.status != 1:
            raise ChainRevert("The transaction was mined and reverted.")
        return receipt

    def _as_revert(self, exc: Exception) -> ChainRevert:
        data = _revert_data(exc)
        contract = self._contract
        if data is not None and contract is not None:
            name = _error_name(contract.abi, data)
            if name:
                return ChainRevert(name)
        text = str(exc)
        for name in (
            "NotOracle",
            "LoanNotFound",
            "RainfallNotBelowTrigger",
            "ReductionExceedsMax",
            "TotalReductionExceedsMax",
            "DeferralExceedsMax",
            "TotalDeferralExceedsMax",
            "ReliefAlreadyAppliedForSeason",
            "DuplicateEvidence",
            "NotBorrowerOrOracle",
            "InvalidReliefValue",
        ):
            if name in text:
                return ChainRevert(name)
        return ChainRevert("The contract rejected the call.")


def _tx_hex(value) -> str:
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text if text.startswith("0x") else "0x" + text


def _bytes32(hex_hash: str) -> bytes:
    token = hex_hash[2:] if hex_hash.startswith("0x") else hex_hash
    if len(token) != 64:
        raise ValueError("data_source_hash must be 32 bytes")
    return bytes.fromhex(token)


def _loan_dict(loan_id: int, raw) -> dict:
    return {
        "loan_id": loan_id,
        "borrower": raw[0],
        "principal_cents": int(raw[1]),
        "annual_rate_bps": int(raw[2]),
        "term_months": int(raw[3]),
        "trigger_rainfall_tenths_mm": int(raw[4]),
        "max_reduction_bps": int(raw[5]),
        "max_deferral_months": int(raw[6]),
        "paid_cents": int(raw[7]),
        "reduction_bps_applied": int(raw[8]),
        "deferral_months_applied": int(raw[9]),
    }


def _relief_dict(raw) -> dict:
    kind = int(raw[1])
    data_hash = raw[4]
    return {
        "season_id": int(raw[0]),
        "relief_type": RELIEF_NAMES.get(kind, str(kind)),
        "relief_value": int(raw[2]),
        "observed_rainfall_tenths_mm": int(raw[3]),
        "data_source_hash": _tx_hex(data_hash),
        "timestamp": int(raw[5]),
    }


def _revert_data(exc: Exception) -> bytes | None:
    data = getattr(exc, "data", None)
    if isinstance(data, str):
        return _hex_bytes(data)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, dict):
        inner = data.get("data") or data.get("result")
        if isinstance(inner, str):
            return _hex_bytes(inner)
    text = str(exc)
    marker = text.rfind("0x")
    if marker >= 0:
        token = text[marker:].split()[0].strip("',)")
        if len(token) >= 10:
            return _hex_bytes(token)
    return None


def _hex_bytes(value: str) -> bytes | None:
    token = value[2:] if value.startswith("0x") else value
    if len(token) < 8 or len(token) % 2:
        return None
    try:
        return bytes.fromhex(token)
    except ValueError:
        return None


def _error_name(abi: list, data: bytes) -> str | None:
    if len(data) < 4:
        return None
    selector = data[:4]
    for item in abi:
        if item.get("type") != "error":
            continue
        signature = item["name"] + "(" + ",".join(arg["type"] for arg in item.get("inputs", [])) + ")"
        if Web3.keccak(text=signature)[:4] == selector:
            return item["name"]
    return None
