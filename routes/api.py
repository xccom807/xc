"""API routes: wallet, payment, SBT, escrow sync, contracts config, chatbot."""

import secrets
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

import requests as http_requests
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from extensions import db, csrf
from blockchain_service import append_statement, maybe_seal_block
from web3_service import get_web3, get_signer_address, submit_anchor_transaction
from routes.helpers import notify

api_bp = Blueprint("api", __name__)


def _has_active_paid_escrow_task(user_id: int) -> bool:
    from models import HelpOffer, HelpRequest

    active_as_requester = HelpRequest.query.filter(
        HelpRequest.user_id == user_id,
        HelpRequest.status.in_(("in_progress", "disputed")),
        HelpRequest.is_volunteer.is_(False),
        HelpRequest.price.isnot(None),
    ).first()
    if active_as_requester:
        return True
    active_as_helper = (
        HelpOffer.query
        .join(HelpRequest, HelpOffer.request_id == HelpRequest.id)
        .filter(
            HelpOffer.helper_id == user_id,
            HelpOffer.status == "accepted",
            HelpRequest.status.in_(("in_progress", "disputed")),
            HelpRequest.is_volunteer.is_(False),
            HelpRequest.price.isnot(None),
        )
        .first()
    )
    return bool(active_as_helper)


# ── Wallet ──────────────────────────────────────────

@api_bp.route("/connect-wallet")
@login_required
def connect_wallet():
    from models import WalletLink
    wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
    return render_template("wallet/connect.html", wallet_link=wallet_link)


@api_bp.route("/wallet/me")
@login_required
def wallet_me():
    from models import WalletLink
    wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
    return jsonify({
        "address": wallet_link.address if wallet_link and wallet_link.verified_at else None,
        "verified": bool(wallet_link and wallet_link.verified_at),
        "verified_at": wallet_link.verified_at.isoformat() if wallet_link and wallet_link.verified_at else None,
    })


@api_bp.route("/wallet/challenge", methods=["POST"])
@csrf.exempt
@login_required
def wallet_challenge():
    from models import WalletLink

    payload = request.get_json(silent=True) or {}
    raw_address = str(payload.get("address", "")).strip()
    if not raw_address or not Web3.is_address(raw_address):
        return jsonify({"ok": False, "error": "Invalid wallet address."}), 400

    address = Web3.to_checksum_address(raw_address)
    existing_by_address = WalletLink.query.filter_by(address=address).one_or_none()
    if existing_by_address and existing_by_address.user_id != current_user.id:
        return jsonify({"ok": False, "error": "This wallet address is already linked to another account."}), 409

    nonce = secrets.token_hex(16)
    issued_at = datetime.now(timezone.utc)
    chain_id = int(current_app.config.get("ETH_CHAIN_ID", 11155111))
    message = (
        "DailyHelper Wallet Verification\n\n"
        f"User ID: {current_user.id}\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at.isoformat()}Z\n"
        f"Domain: {request.host}"
    )

    wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
    if wallet_link and wallet_link.verified_at and wallet_link.address.lower() != address.lower():
        if _has_active_paid_escrow_task(current_user.id):
            return jsonify({"ok": False, "error": "存在进行中或仲裁中的付费 Escrow 任务，暂不能改绑钱包。"}), 409
    if wallet_link is None:
        wallet_link = WalletLink(user_id=current_user.id, address=address, challenge_nonce=nonce, challenge_issued_at=issued_at)
        db.session.add(wallet_link)
    else:
        wallet_link.address = address
        wallet_link.challenge_nonce = nonce
        wallet_link.challenge_issued_at = issued_at
        wallet_link.verified_at = None
    db.session.commit()

    return jsonify({"ok": True, "message": message, "chain_id": chain_id})


@api_bp.route("/wallet/verify", methods=["POST"])
@csrf.exempt
@login_required
def wallet_verify():
    from models import WalletLink

    payload = request.get_json(silent=True) or {}
    raw_address = str(payload.get("address", "")).strip()
    signature = str(payload.get("signature", "")).strip()
    chain_id = int(current_app.config.get("ETH_CHAIN_ID", 11155111))

    if not raw_address or not Web3.is_address(raw_address):
        return jsonify({"ok": False, "error": "Invalid wallet address."}), 400
    if not signature:
        return jsonify({"ok": False, "error": "Signature is required."}), 400

    address = Web3.to_checksum_address(raw_address)
    wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
    if wallet_link is None:
        return jsonify({"ok": False, "error": "No active challenge for this account."}), 400
    if wallet_link.address != address:
        return jsonify({"ok": False, "error": "Address does not match the active challenge."}), 400
    if not wallet_link.challenge_nonce or not wallet_link.challenge_issued_at:
        return jsonify({"ok": False, "error": "Challenge expired. Please reconnect wallet."}), 400
    issued = wallet_link.challenge_issued_at
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - issued > timedelta(minutes=10):
        wallet_link.challenge_nonce = None
        wallet_link.challenge_issued_at = None
        db.session.commit()
        return jsonify({"ok": False, "error": "Challenge expired. Please reconnect wallet."}), 400

    # Reconstruct the exact same message string that was signed.
    # SQLite strips timezone info, so we must re-attach UTC to get the
    # same isoformat() output that /wallet/challenge produced.
    issued_for_msg = wallet_link.challenge_issued_at
    if issued_for_msg.tzinfo is None:
        issued_for_msg = issued_for_msg.replace(tzinfo=timezone.utc)
    challenge_message = (
        "DailyHelper Wallet Verification\n\n"
        f"User ID: {current_user.id}\n"
        f"Address: {wallet_link.address}\n"
        f"Nonce: {wallet_link.challenge_nonce}\n"
        f"Issued At: {issued_for_msg.isoformat()}Z\n"
        f"Domain: {request.host}"
    )
    try:
        recovered = Account.recover_message(encode_defunct(text=challenge_message), signature=signature)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Invalid signature: {e}"}), 400

    if Web3.to_checksum_address(recovered) != wallet_link.address:
        return jsonify({"ok": False, "error": "Signature does not match the wallet address."}), 400

    wallet_link.verified_at = datetime.now(timezone.utc)
    wallet_link.challenge_nonce = None
    wallet_link.challenge_issued_at = None
    db.session.commit()
    try:
        append_statement(kind="wallet_linked", payload={"address": wallet_link.address, "chain_id": chain_id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"ok": True, "address": wallet_link.address, "verified_at": wallet_link.verified_at.isoformat()})


@api_bp.route("/wallet/disconnect", methods=["POST"])
@csrf.exempt
@login_required
def wallet_disconnect():
    from models import WalletLink
    wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
    if wallet_link is None:
        return jsonify({"ok": True, "address": None})
    if _has_active_paid_escrow_task(current_user.id):
        return jsonify({"ok": False, "error": "存在进行中或仲裁中的付费 Escrow 任务，暂不能解绑钱包。"}), 409
    removed_address = wallet_link.address
    db.session.delete(wallet_link)
    db.session.commit()
    try:
        append_statement(kind="wallet_unlinked", payload={"address": removed_address}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"ok": True, "address": None})


# ── Web3 status ──────────────────────────────────────

@api_bp.route("/web3", methods=["GET", "POST"])
def web3_status():
    w3 = get_web3()
    ok = False
    net_info = {}
    latest_block = None
    error = None
    anchor_result = None
    signer_address = None
    signer_error = None
    chain_id = None
    try:
        signer_address = get_signer_address()
        if current_app.config.get("ETH_SIGNER_PRIVATE_KEY") and not signer_address:
            signer_error = "Signer private key format is invalid."
    except Exception:
        signer_address = None
        signer_error = "Signer initialization failed."

    if request.method == "POST":
        anchor_text = str(request.form.get("anchor_text", "")).strip()
        if not anchor_text:
            flash("请输入需要上链的内容。", "error")
        else:
            try:
                anchor_result = submit_anchor_transaction(anchor_text)
                try:
                    append_statement(
                        kind="onchain_anchor_submitted",
                        payload={"tx_hash": anchor_result.get("tx_hash"), "chain_id": anchor_result.get("chain_id"), "tx_status": anchor_result.get("status"), "tx_url": anchor_result.get("tx_url"), "payload_size": len(anchor_text)},
                        user_id=getattr(current_user, "id", None) if current_user.is_authenticated else None,
                    )
                    maybe_seal_block()
                except Exception:
                    pass
                flash(f"已提交链上交易: {anchor_result.get('tx_hash')}", "success")
            except Exception as e:  # noqa: BLE001
                flash(f"上链失败: {e}", "error")

    if w3 is not None:
        try:
            ok = w3.is_connected()
            if ok:
                net_info = {"client": w3.client_version}
                latest_block = w3.eth.block_number
                chain_id = int(w3.eth.chain_id)
        except Exception as e:  # noqa: BLE001
            error = str(e)
    return render_template(
        "web3/status.html", ok=ok, net_info=net_info, latest_block=latest_block,
        chain_id=chain_id, signer_address=signer_address, signer_error=signer_error,
        anchor_result=anchor_result,
        rpc_url=("configured" if current_app.config.get("ETH_RPC_URL") else "not set"),
        error=error,
    )


@api_bp.route("/web3/balance")
def web3_balance():
    w3 = get_web3()
    addr = request.args.get("address", "").strip()
    balance_eth = None
    error = None
    if w3 and addr:
        try:
            balance_wei = w3.eth.get_balance(addr)
            balance_eth = str(w3.from_wei(balance_wei, "ether"))
        except Exception as e:
            error = str(e)
    accept = request.headers.get("Accept", "")
    if "text/html" not in accept:
        return jsonify({"address": addr, "balance_eth": balance_eth, "error": error})
    return render_template("web3/balance.html", address=addr, balance_eth=balance_eth, error=error)


# ── Payment ──────────────────────────────────────────

@api_bp.route("/api/submit-payment-address", methods=["POST"])
@login_required
def submit_payment_address():
    from models import HelpRequest, HelpOffer, Payment
    if getattr(current_user, "is_blacklisted", False):
        flash("您的账号已被列入黑名单，无法操作。", "error")
        return redirect(url_for("main.dashboard"))
    request_id = request.form.get("request_id", type=int)
    helper_address = (request.form.get("helper_address") or "").strip()
    if not request_id or not helper_address:
        flash("请填写收款地址。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id or 0))
    if not Web3.is_address(helper_address):
        flash("无效的以太坊地址格式，请检查后重新提交。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    helper_address = Web3.to_checksum_address(helper_address)
    req_obj = HelpRequest.query.get_or_404(request_id)
    if req_obj.status != "completed":
        flash("任务尚未完成，无法提交收款地址。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    if not req_obj.price or req_obj.is_volunteer:
        flash("该任务为免费/志愿服务，无需支付。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    completed_offer = HelpOffer.query.filter_by(request_id=req_obj.id, status="completed").first()
    if not completed_offer or completed_offer.helper_id != current_user.id:
        flash("只有该任务的帮助者才能提交收款地址。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    existing = Payment.query.filter_by(request_id=req_obj.id).first()
    if existing:
        flash("收款地址已提交过，无需重复操作。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    payment = Payment(request_id=req_obj.id, helper_id=current_user.id, requester_id=req_obj.user_id, helper_address=helper_address, amount=req_obj.price, status="address_submitted")
    db.session.add(payment)
    db.session.commit()
    try:
        append_statement(kind="payment_address_submitted", payload={"request_id": req_obj.id, "helper_id": current_user.id, "helper_address": helper_address, "amount": req_obj.price}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    notify(req_obj.user_id, "payment_address_submitted", f"帮助者已提交收款地址，请前往「{req_obj.title[:40]}」进行转账支付。", url_for("features.request_detail", request_id=req_obj.id))
    db.session.commit()
    flash("收款地址已提交，等待求助者转账。", "success")
    return redirect(url_for("features.request_detail", request_id=request_id))


@api_bp.route("/api/record-payment", methods=["POST"])
@login_required
def record_payment():
    from models import HelpRequest, Payment
    request_id = request.form.get("request_id", type=int)
    tx_hash = (request.form.get("tx_hash") or "").strip()
    if not request_id or not tx_hash:
        flash("请填写交易哈希。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id or 0))
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        flash("交易哈希格式不正确，应为 0x 开头的66位十六进制字符串。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    req_obj = HelpRequest.query.get_or_404(request_id)
    if req_obj.user_id != current_user.id:
        flash("只有求助者本人才能上传支付凭证。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    if req_obj.status != "completed":
        flash("任务尚未完成。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    payment = Payment.query.filter_by(request_id=req_obj.id).first()
    if not payment:
        flash("帮助者尚未提交收款地址，无法上传支付凭证。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    if payment.status == "paid":
        flash("该任务已完成支付，无需重复操作。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    if payment.status == "refunded":
        flash("该任务已由仲裁退款给求助者，不能再上传支付凭证。", "error")
        return redirect(url_for("features.request_detail", request_id=request_id))
    payment.tx_hash = tx_hash
    payment.status = "paid"
    payment.paid_at = datetime.now(timezone.utc)
    db.session.commit()
    try:
        append_statement(kind="payment_proof_uploaded", payload={"request_id": req_obj.id, "helper_id": payment.helper_id, "requester_id": current_user.id, "tx_hash": tx_hash, "amount": payment.amount, "helper_address": payment.helper_address}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    notify(payment.helper_id, "payment_completed", f"求助者已完成转账并上传凭证，请前往「{req_obj.title[:40]}」查看。", url_for("features.request_detail", request_id=req_obj.id))
    db.session.commit()
    flash("支付凭证已上传成功！", "success")
    return redirect(url_for("features.request_detail", request_id=request_id))


# ── SBT ──────────────────────────────────────────────

@api_bp.route("/api/sbt/proof")
@login_required
def api_sbt_proof():
    from merkle_service import get_user_proof
    proof_data = get_user_proof(current_app._get_current_object(), current_user.id)
    if proof_data is None:
        return jsonify({"error": "不满足 SBT 申领条件（需信誉≥20且已绑定钱包）"}), 400
    return jsonify(proof_data)


@api_bp.route("/api/sbt/status/<string:address>")
def api_sbt_status(address: str):
    return jsonify({
        "address": address,
        "sbt_contract": current_app.config.get("SBT_CONTRACT_ADDRESS", ""),
        "chain_id": int(current_app.config.get("ETH_CHAIN_ID", 11155111)),
        "hint": "Use sbt_contract ABI getSBT(address) on-chain for live data",
    })


# ── Escrow sync ──────────────────────────────────────

@api_bp.post("/api/escrow/sync")
@csrf.exempt
@login_required
def api_escrow_sync():
    from models import HelpRequest, HelpOffer, WalletLink
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    action = data.get("action")
    tx_hash = data.get("tx_hash", "")
    outcome = (data.get("outcome") or "").strip()
    chain_helper_address = None
    chain_requester_address = None
    recipient_address = (data.get("recipient_address") or "").strip()
    if recipient_address and Web3.is_address(recipient_address):
        recipient_address = Web3.to_checksum_address(recipient_address)
    else:
        recipient_address = None
    if not task_id or not action:
        return jsonify({"error": "task_id and action required"}), 400
    req = HelpRequest.query.get(task_id)
    if not req:
        return jsonify({"error": "task not found"}), 404
    if getattr(current_user, "is_blacklisted", False) and action in ("lock", "dispute"):
        return jsonify({"error": "blacklisted users cannot start escrow or dispute actions"}), 403
    if action in ("lock", "release", "dispute", "resolve") and (req.is_volunteer or not req.price):
        return jsonify({"error": "escrow sync is only valid for paid tasks"}), 400
    if action in ("lock", "release") and current_user.id != req.user_id:
        return jsonify({"error": "only requester can sync this action"}), 403
    if action == "dispute":
        party_offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=current_user.id).filter(HelpOffer.status.in_(("accepted", "completed"))).first()
        if current_user.id != req.user_id and not party_offer:
            return jsonify({"error": "only task parties can sync dispute"}), 403
    if action in ("lock", "release", "dispute", "resolve"):
        escrow_addr = current_app.config.get("ESCROW_CONTRACT_ADDRESS")
        w3 = get_web3()
        if not escrow_addr or w3 is None or not w3.is_connected():
            return jsonify({"error": "cannot verify escrow state on-chain"}), 503
        try:
            escrow_abi = [{
                "inputs": [{"internalType": "uint256", "name": "taskId", "type": "uint256"}],
                "name": "getEscrow",
                "outputs": [
                    {"internalType": "address", "name": "requester", "type": "address"},
                    {"internalType": "address", "name": "helper", "type": "address"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "enum TaskEscrow.EscrowStatus", "name": "status", "type": "uint8"},
                    {"internalType": "uint64", "name": "createdAt", "type": "uint64"},
                    {"internalType": "uint64", "name": "resolvedAt", "type": "uint64"},
                    {"internalType": "uint32", "name": "votesForHelper", "type": "uint32"},
                    {"internalType": "uint32", "name": "votesForRequester", "type": "uint32"},
                ],
                "stateMutability": "view",
                "type": "function",
            }]
            c = w3.eth.contract(address=Web3.to_checksum_address(escrow_addr), abi=escrow_abi)
            chain_data = c.functions.getEscrow(int(task_id)).call()
            chain_amount_wei = int(chain_data[2])
            chain_status = int(chain_data[3])
            chain_requester_address = Web3.to_checksum_address(chain_data[0])
            chain_helper_address = Web3.to_checksum_address(chain_data[1])
            requester_wallet = WalletLink.query.filter_by(user_id=req.user_id).first()
            if not requester_wallet or not requester_wallet.verified_at:
                return jsonify({"error": "requester has no verified wallet for escrow verification"}), 409
            if requester_wallet.address.lower() != chain_requester_address.lower():
                return jsonify({"error": "escrow requester address does not match task requester wallet"}), 409
            try:
                expected_amount_wei = int(Web3.to_wei(Decimal(str(req.price)), "ether"))
            except (InvalidOperation, ValueError) as e:
                return jsonify({"error": f"invalid task price for escrow verification: {e}"}), 409
            if chain_amount_wei != expected_amount_wei:
                return jsonify({"error": "escrow amount does not match task price"}), 409
            expected_status = {"lock": 1, "release": 2, "dispute": 3, "resolve": 4}[action]
            if chain_status != expected_status:
                return jsonify({"error": f"escrow on-chain status mismatch: expected {expected_status}, got {chain_status}"}), 409
            votes_for_helper = int(chain_data[6])
            votes_for_requester = int(chain_data[7])
            if action == "release":
                outcome = "helper"
                recipient_address = chain_helper_address
            elif action == "resolve":
                if votes_for_helper > votes_for_requester:
                    outcome = "helper"
                    recipient_address = chain_helper_address
                else:
                    outcome = "requester"
                    recipient_address = chain_requester_address
        except Exception as e:
            return jsonify({"error": f"failed to verify escrow state: {e}"}), 503
    status_map = {"lock": "in_progress", "release": "completed", "dispute": "disputed", "resolve": "completed"}
    if action == "resolve" and outcome in ("requester", "refund", "refund_requester"):
        status_map["resolve"] = "cancelled"
    new_status = status_map.get(action)
    if not new_status:
        return jsonify({"error": f"unknown action: {action}"}), 400
    old_status = req.status
    req.status = new_status
    if action == "lock":
        accepted_offer = None
        if chain_helper_address:
            chain_wallet = WalletLink.query.filter(WalletLink.address.ilike(chain_helper_address)).first()
            if chain_wallet:
                accepted_offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=chain_wallet.user_id).filter(HelpOffer.status.in_(("pending", "accepted"))).first()
        if not accepted_offer:
            accepted_offer = HelpOffer.query.filter_by(request_id=req.id, status="accepted").first()
        if accepted_offer:
            notify(accepted_offer.helper_id, "escrow_locked", f"求助「{req.title[:30]}」的赏金已锁定到智能合约。", url_for("features.request_detail", request_id=req.id))
            HelpOffer.query.filter_by(request_id=req.id, status="pending").filter(HelpOffer.id != accepted_offer.id).update({"status": "rejected"})
            accepted_offer.status = "accepted"
        else:
            return jsonify({"error": "no matching offer for on-chain helper"}), 409
    if action in ("release", "resolve"):
        from models import Payment, WalletLink
        existing_pay = Payment.query.filter_by(request_id=req.id).first()
        offer = None
        if chain_helper_address:
            chain_wallet = WalletLink.query.filter(WalletLink.address.ilike(chain_helper_address)).first()
            if chain_wallet:
                offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=chain_wallet.user_id).first()
        if not offer:
            offer = HelpOffer.query.filter_by(request_id=req.id, status="accepted").first()
        if not offer:
            offer = HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
        if not offer and existing_pay:
            offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=existing_pay.helper_id).first()
        if not offer:
            offer = HelpOffer.query.filter_by(request_id=req.id, status="pending").first()
        if offer:
            helper_wins = action == "release" or outcome in ("helper", "pay_helper")
            requester_wins = action == "resolve" and outcome in ("requester", "refund", "refund_requester")
            helper_wallet = WalletLink.query.filter_by(user_id=offer.helper_id).first()
            requester_wallet = WalletLink.query.filter_by(user_id=req.user_id).first()
            helper_addr = recipient_address if helper_wins and recipient_address else (helper_wallet.address if helper_wallet else "0x0000000000000000000000000000000000000000")
            refund_addr = recipient_address if requester_wins and recipient_address else (requester_wallet.address if requester_wallet else "0x0000000000000000000000000000000000000000")
            offer.status = "completed" if helper_wins else "rejected"
            if requester_wins and existing_pay:
                existing_pay.status = "refunded"
                existing_pay.tx_hash = tx_hash or existing_pay.tx_hash
                existing_pay.helper_address = refund_addr
                existing_pay.paid_at = datetime.now(timezone.utc)
            elif requester_wins and req.price:
                pay = Payment(
                    request_id=req.id,
                    helper_id=offer.helper_id,
                    requester_id=req.user_id,
                    helper_address=refund_addr,
                    amount=req.price,
                    tx_hash=tx_hash or None,
                    status="refunded",
                    paid_at=datetime.now(timezone.utc),
                )
                db.session.add(pay)
            elif helper_wins and existing_pay:
                existing_pay.status = "paid"
                existing_pay.tx_hash = tx_hash or existing_pay.tx_hash
                existing_pay.helper_address = helper_addr
                existing_pay.paid_at = existing_pay.paid_at or datetime.now(timezone.utc)
            elif helper_wins and req.price:
                pay = Payment(
                    request_id=req.id,
                    helper_id=offer.helper_id,
                    requester_id=req.user_id,
                    helper_address=helper_addr,
                    amount=req.price,
                    tx_hash=tx_hash or None,
                    status="paid",
                    paid_at=datetime.now(timezone.utc),
                )
                db.session.add(pay)
    db.session.commit()
    try:
        append_statement(kind=f"escrow_{action}", payload={"task_id": task_id, "action": action, "outcome": outcome, "recipient_address": recipient_address, "tx_hash": tx_hash, "old_status": old_status, "new_status": new_status, "user_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:
        pass
    return jsonify({"success": True, "new_status": new_status})


# ── Contracts config ──────────────────────────────────

@api_bp.route("/api/contracts/config")
def api_contracts_config():
    return jsonify({
        "sbt_contract": current_app.config.get("SBT_CONTRACT_ADDRESS", ""),
        "escrow_contract": current_app.config.get("ESCROW_CONTRACT_ADDRESS", ""),
        "chain_id": int(current_app.config.get("ETH_CHAIN_ID", 11155111)),
        "rpc_url": current_app.config.get("ETH_RPC_URL", ""),
        "explorer_base": current_app.config.get("ETH_EXPLORER_TX_BASE_URL", ""),
    })


# ── Arbitration ──────────────────────────────────────

@api_bp.route("/arbitration")
@login_required
def arbitration_hall():
    from models import HelpRequest
    if current_user.reputation_score < 80:
        flash("仲裁大厅需要信誉分达到 80（金牌）才能进入。", "info")
        return redirect(url_for("main.dashboard"))
    disputed = HelpRequest.query.filter_by(status="disputed").order_by(HelpRequest.created_at.desc()).all()
    return render_template(
        "features/arbitration.html", disputed=disputed,
        escrow_address=current_app.config.get("ESCROW_CONTRACT_ADDRESS", ""),
        sbt_address=current_app.config.get("SBT_CONTRACT_ADDRESS", ""),
        chain_id=int(current_app.config.get("ETH_CHAIN_ID", 11155111)),
        rpc_url=current_app.config.get("ETH_RPC_URL", ""),
        vote_threshold=int(current_app.config.get("DAO_VOTE_THRESHOLD", 1)),
    )


# ── Real-time Unread Counts ──────────────────────────

@api_bp.route("/api/unread-counts")
@login_required
def unread_counts():
    from models import Notification, Message
    notif = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    msg = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({"ok": True, "notifications": notif, "messages": msg})


# ── Chatbot ──────────────────────────────────────────

KIMI_SYSTEM_PROMPT = """你是「每日互助」平台的智能助手，你的名字叫"小美"。
你的职责是回答用户关于本平台功能、使用方法和常见问题的咨询。
你可以通过工具函数直接查询平台数据库来帮助用户搜索帮助者、查找求助任务和查看用户资料。

## 平台概述
每日互助（DailyHelper）是一个基于 Flask + 区块链的社区互助平台。用户可以发布求助、提交帮助提议、完成任务后通过链上支付结算并互评，所有关键操作均记录在内部审计链并可锚定至以太坊 Sepolia 测试网。

## 核心功能
1. **用户系统**：注册/登录/个人资料/公开主页/信誉等级
2. **互助任务全流程**：发布求助 → 帮助者提交提议 → 求助者接受 → 私聊沟通 → 标记完成 → 支付 → 互评
3. **支付系统（两步链上结算）**：帮助者提交以太坊收款地址 → 求助者链上转账后上传 tx_hash
4. **信誉系统（对数衰减）**：delta = base_points * (1/log2(当前分+2)) * 评论字数加成。分越高加分越少，鼓励详细评价
5. **私信系统**：接受提议后双方可私聊
6. **区块链审计**：所有操作记录为 Statement → 自动封块 Block → 可锚定 Sepolia
7. **管理后台**：用户管理、举报审核
8. **其他**：全局搜索、排行榜、志愿专区、附近的人

## SBT 等级
- 铜牌 🥉：信誉分 ≥ 20
- 银牌 🥈：信誉分 ≥ 50
- 金牌 🥇：信誉分 ≥ 80

## 常用页面
- /dashboard 仪表盘  - /marketplace 帮助市场  - /request-help 发布求助
- /messages 私信  - /notifications 通知  - /leaderboard 排行榜
- /volunteer 志愿专区  - /nearby 附近的人
- /blockchain/blocks 区块浏览器  - /admin 管理后台（仅管理员）

## 回答要求
- 用简洁友好的中文回答
- 当用户询问的问题可以通过查询数据库获取精确答案时，请主动调用工具函数
- 在展示用户信息时，给出其主页链接格式：/u/用户名
- 如果问题与平台无关，礼貌引导回平台话题
- 可以给出操作步骤建议
- 不要编造平台没有的功能"""


# ── Function Calling: 工具定义 ──────────────────────────

CHATBOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_helpers",
            "description": "搜索平台上的帮助者/用户。可按技能、地点、最低信誉分筛选。返回匹配用户列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "技能关键词，如 '水电'、'编程'、'搬家'"
                    },
                    "location": {
                        "type": "string",
                        "description": "地点关键词，如 '北京'、'朝阳'"
                    },
                    "min_reputation": {
                        "type": "number",
                        "description": "最低信誉分要求，如 50、80"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认5",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_requests",
            "description": "搜索平台上的求助任务。可按分类、状态、关键词筛选。返回匹配的求助列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（匹配标题或描述）"
                    },
                    "category": {
                        "type": "string",
                        "description": "分类，如 '家政服务'、'技术支持'、'生活帮助'"
                    },
                    "status": {
                        "type": "string",
                        "description": "状态筛选：open/in_progress/completed/cancelled/disputed",
                        "enum": ["open", "in_progress", "completed", "cancelled", "disputed"]
                    },
                    "is_volunteer": {
                        "type": "boolean",
                        "description": "是否只看志愿（免费）任务"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认5",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "查看指定用户的详细资料，包括信誉分、SBT等级、技能、帮助次数等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "用户名"
                    }
                },
                "required": ["username"]
            }
        }
    }
]


def _exec_tool(name, args):
    """Execute a tool function call against the database."""
    import json as _json
    from models import User, HelpRequest, HelpOffer, WalletLink

    if name == "search_helpers":
        q = User.query.filter(User.user_type != "admin", User.is_blacklisted == False)
        skill = args.get("skill")
        if skill:
            q = q.filter(User.skills.ilike(f"%{skill}%"))
        location = args.get("location")
        if location:
            q = q.filter(User.location.ilike(f"%{location}%"))
        min_rep = args.get("min_reputation")
        if min_rep is not None:
            q = q.filter(User.reputation_score >= float(min_rep))
        limit = min(int(args.get("limit", 5)), 20)
        users = q.order_by(User.reputation_score.desc()).limit(limit).all()
        results = []
        for u in users:
            tier = "🥇金牌" if u.reputation_score >= 80 else "🥈银牌" if u.reputation_score >= 50 else "🥉铜牌" if u.reputation_score >= 20 else "无"
            has_wallet = WalletLink.query.filter_by(user_id=u.id).first() is not None
            helped_count = HelpOffer.query.filter_by(helper_id=u.id, status="completed").count()
            results.append({
                "username": u.username,
                "full_name": u.full_name or "",
                "reputation": u.reputation_score,
                "sbt_tier": tier,
                "skills": u.skills or "",
                "location": u.location or "",
                "helped_count": helped_count,
                "has_wallet": has_wallet,
                "profile_url": f"/u/{u.username}"
            })
        return _json.dumps(results, ensure_ascii=False)

    elif name == "search_requests":
        q = HelpRequest.query
        keyword = args.get("keyword")
        if keyword:
            q = q.filter(
                (HelpRequest.title.ilike(f"%{keyword}%")) |
                (HelpRequest.description.ilike(f"%{keyword}%"))
            )
        category = args.get("category")
        if category:
            q = q.filter(HelpRequest.category.ilike(f"%{category}%"))
        status = args.get("status")
        if status:
            q = q.filter(HelpRequest.status == status)
        is_vol = args.get("is_volunteer")
        if is_vol is not None:
            q = q.filter(HelpRequest.is_volunteer == bool(is_vol))
        limit = min(int(args.get("limit", 5)), 20)
        requests_list = q.order_by(HelpRequest.created_at.desc()).limit(limit).all()
        results = []
        for r in requests_list:
            poster = User.query.get(r.user_id)
            results.append({
                "id": r.id,
                "title": r.title,
                "category": r.category or "",
                "location": r.location or "",
                "status": r.status,
                "price": str(r.price) if r.price else "志愿",
                "is_volunteer": r.is_volunteer,
                "poster": poster.username if poster else "未知",
                "detail_url": f"/requests/{r.id}"
            })
        return _json.dumps(results, ensure_ascii=False)

    elif name == "get_user_profile":
        username = args.get("username", "")
        user = User.query.filter_by(username=username).first()
        if not user:
            return _json.dumps({"error": f"用户 '{username}' 不存在"}, ensure_ascii=False)
        tier = "🥇金牌" if user.reputation_score >= 80 else "🥈银牌" if user.reputation_score >= 50 else "🥉铜牌" if user.reputation_score >= 20 else "无"
        has_wallet = WalletLink.query.filter_by(user_id=user.id).first() is not None
        helped = HelpOffer.query.filter_by(helper_id=user.id, status="completed").count()
        posted = HelpRequest.query.filter_by(user_id=user.id).count()
        return _json.dumps({
            "username": user.username,
            "full_name": user.full_name or "",
            "reputation": user.reputation_score,
            "sbt_tier": tier,
            "skills": user.skills or "",
            "location": user.location or "",
            "bio": user.bio or "",
            "helped_count": helped,
            "posted_count": posted,
            "has_wallet": has_wallet,
            "profile_url": f"/u/{user.username}"
        }, ensure_ascii=False)

    return '{"error": "未知工具"}'


@api_bp.route("/chatbot")
@login_required
def chatbot():
    from models import ChatbotMessage

    rows = (
        ChatbotMessage.query
        .filter_by(user_id=current_user.id)
        .order_by(ChatbotMessage.created_at.desc(), ChatbotMessage.id.desc())
        .limit(50)
        .all()
    )
    chat_history = [
        {"role": row.role, "content": row.content}
        for row in reversed(rows)
        if row.role in ("user", "assistant")
    ]
    return render_template("chatbot.html", chat_history=chat_history)


@api_bp.route("/api/chatbot", methods=["POST"])
@csrf.exempt
@login_required
def chatbot_api():
    import json as _json
    from models import ChatbotMessage

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not user_message:
        return jsonify({"ok": False, "error": "消息不能为空"}), 400
    api_key = current_app.config.get("KIMI_API_KEY", "")
    model = current_app.config.get("KIMI_MODEL", "moonshot-v1-8k")
    if not api_key:
        return jsonify({"ok": False, "error": "AI 服务未配置"}), 500
    stored_history = (
        ChatbotMessage.query
        .filter_by(user_id=current_user.id)
        .order_by(ChatbotMessage.created_at.desc(), ChatbotMessage.id.desc())
        .limit(20)
        .all()
    )
    history_source = [
        {"role": row.role, "content": row.content}
        for row in reversed(stored_history)
    ] or history
    messages = [{"role": "system", "content": KIMI_SYSTEM_PROMPT}]
    for h in history_source[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    api_url = "https://api.moonshot.cn/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        # ── 首次请求（附带工具定义） ──
        resp = http_requests.post(
            api_url, headers=headers,
            json={
                "model": model, "messages": messages,
                "tools": CHATBOT_TOOLS, "temperature": 0.7, "max_tokens": 1024,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        choice = result["choices"][0]
        assistant_msg = choice["message"]

        # ── 处理 tool_calls 循环（最多 3 轮） ──
        rounds = 0
        while assistant_msg.get("tool_calls") and rounds < 3:
            rounds += 1
            messages.append(assistant_msg)

            for tc in assistant_msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = _json.loads(tc["function"].get("arguments") or "{}")
                current_app.logger.info(f"AI tool call: {fn_name}({fn_args})")
                tool_result = _exec_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

            # 把工具结果发回 AI 生成最终回复
            resp = http_requests.post(
                api_url, headers=headers,
                json={
                    "model": model, "messages": messages,
                    "tools": CHATBOT_TOOLS, "temperature": 0.7, "max_tokens": 1024,
                },
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            choice = result["choices"][0]
            assistant_msg = choice["message"]

        reply = assistant_msg.get("content") or "抱歉，我暂时无法回答这个问题。"
        db.session.add(ChatbotMessage(user_id=current_user.id, role="user", content=user_message))
        db.session.add(ChatbotMessage(user_id=current_user.id, role="assistant", content=reply))
        db.session.commit()
        return jsonify({"ok": True, "reply": reply})
    except http_requests.Timeout:
        return jsonify({"ok": False, "error": "AI 响应超时，请稍后重试"}), 504
    except Exception as e:
        current_app.logger.error(f"Kimi API error: {e}")
        return jsonify({"ok": False, "error": "AI 服务暂时不可用，请稍后重试"}), 502
