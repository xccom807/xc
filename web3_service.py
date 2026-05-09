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
    """Return the cached Web3 instance, or try to re-initialize if unavailable."""
    global _w3
    if _w3 is not None and _w3.is_connected():
        return _w3
    # Attempt reconnection
    from flask import current_app
    try:
        rpc_url = current_app.config.get("ETH_RPC_URL", "")
        if rpc_url:
            init_web3(rpc_url)
    except RuntimeError:
        pass  # outside of application context
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
    import time

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

    # Gas price: use at least 1.15x multiplier to handle replacement scenarios
    gas_price_multiplier = max(float(current_app.config.get("ETH_GAS_PRICE_MULTIPLIER", 1.15)), 1.1)
    configured_gas_limit = int(current_app.config.get("ETH_ANCHOR_GAS_LIMIT", 120000))

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        # Re-fetch nonce each attempt to get the latest state
        nonce = w3.eth.get_transaction_count(signer_address, "pending")

        # Increase gas price on each retry to beat pending transactions
        retry_multiplier = gas_price_multiplier * (1.0 + attempt * 0.15)
        gas_price = int(w3.eth.gas_price * retry_multiplier)
        # Ensure minimum gas price of 1 gwei
        gas_price = max(gas_price, 1_000_000_000)

        tx_base = {
            "chainId": chain_id,
            "from": signer_address,
            "to": target_address,
            "value": 0,
            "nonce": nonce,
            "data": Web3.to_hex(text=clean_text),
        }

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

        try:
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

        except Exception as e:
            err_msg = str(e).lower()
            # Retry on nonce/replacement issues
            if "replacement transaction underpriced" in err_msg or "nonce too low" in err_msg or "already known" in err_msg:
                last_error = e
                time.sleep(2 + attempt * 3)  # Wait before retry
                continue
            # Non-retryable error
            raise

    # All retries exhausted
    raise last_error or RuntimeError("Transaction submission failed after retries.")
