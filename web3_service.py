from typing import Any, Dict, Optional

from eth_account import Account
from flask import current_app
from web3 import Web3

# Simple module-level holder
_w3: Optional[Web3] = None


def init_web3(rpc_url: str) -> Optional[Web3]:
    global _w3
    if not rpc_url:
        _w3 = None
        return _w3
    try:
        _w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        # Attempt a lightweight call
        _ = _w3.is_connected()
        return _w3
    except Exception:
        _w3 = None
        return _w3


def get_web3() -> Optional[Web3]:
    return _w3


def get_signer_address() -> Optional[str]:
    private_key = str(current_app.config.get("ETH_SIGNER_PRIVATE_KEY", "")).strip()
    if not private_key:
        return None
    try:
        account = Account.from_key(private_key)
    except Exception:
        return None
    return account.address


def submit_anchor_transaction(anchor_text: str) -> Dict[str, Any]:
    w3 = get_web3()
    if w3 is None:
        raise RuntimeError("Web3 client is not initialized. Please set ETH_RPC_URL.")
    if not w3.is_connected():
        raise RuntimeError("Web3 client is not connected to the RPC endpoint.")

    clean_text = (anchor_text or "").strip()
    if not clean_text:
        raise RuntimeError("Anchor text is required.")

    private_key = str(current_app.config.get("ETH_SIGNER_PRIVATE_KEY", "")).strip()
    if not private_key:
        raise RuntimeError("ETH_SIGNER_PRIVATE_KEY is not configured.")

    account = Account.from_key(private_key)
    signer_address = Web3.to_checksum_address(account.address)

    target_raw = str(current_app.config.get("ETH_ANCHOR_TARGET_ADDRESS", "")).strip() or signer_address
    if not Web3.is_address(target_raw):
        raise RuntimeError("ETH_ANCHOR_TARGET_ADDRESS is invalid.")
    target_address = Web3.to_checksum_address(target_raw)

    chain_id_cfg = current_app.config.get("ETH_CHAIN_ID")
    chain_id = int(chain_id_cfg) if chain_id_cfg else int(w3.eth.chain_id)
    nonce = w3.eth.get_transaction_count(signer_address, "pending")

    gas_price_multiplier = float(current_app.config.get("ETH_GAS_PRICE_MULTIPLIER", 1.0))
    gas_price = int(w3.eth.gas_price * gas_price_multiplier)

    tx_base = {
        "chainId": chain_id,
        "from": signer_address,
        "to": target_address,
        "value": 0,
        "nonce": nonce,
        "data": Web3.to_hex(text=clean_text),
    }

    configured_gas_limit = int(current_app.config.get("ETH_ANCHOR_GAS_LIMIT", 120000))
    try:
        estimated = int(w3.eth.estimate_gas(tx_base))
        gas_limit = max(estimated + 30000, 21000)
    except Exception:
        gas_limit = configured_gas_limit

    tx = {
        **tx_base,
        "gas": gas_limit,
        "gasPrice": gas_price,
    }
    signed_tx = Account.sign_transaction(tx, private_key=private_key)
    tx_hash_obj = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    tx_hash = tx_hash_obj.hex()

    result: Dict[str, Any] = {
        "tx_hash": tx_hash,
        "chain_id": chain_id,
        "from": signer_address,
        "to": target_address,
        "nonce": nonce,
        "gas": gas_limit,
        "gas_price_wei": gas_price,
    }

    if bool(current_app.config.get("ETH_WAIT_FOR_RECEIPT", True)):
        timeout = int(current_app.config.get("ETH_TX_TIMEOUT_SECONDS", 180))
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash_obj, timeout=timeout, poll_latency=2)
        result["status"] = int(receipt.status)
        result["block_number"] = int(receipt.blockNumber)
        result["gas_used"] = int(receipt.gasUsed)

    explorer = str(current_app.config.get("ETH_EXPLORER_TX_BASE_URL", "")).strip()
    if explorer:
        result["tx_url"] = f"{explorer.rstrip('/')}/{tx_hash}"

    return result
