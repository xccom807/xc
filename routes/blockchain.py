"""Blockchain routes: block explorer, statement detail, reputation proof/anchor."""

import hashlib
import json
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user

from extensions import db
from blockchain_service import append_statement, maybe_seal_block
from web3_service import submit_anchor_transaction

blockchain_bp = Blueprint("blockchain", __name__)


@blockchain_bp.route("/blockchain/blocks")
@login_required
def blockchain_blocks():
    from models import Block, Statement
    page = int(request.args.get("page", 1) or 1)
    per_page = 10
    blocks_query = db.session.query(
        Block, db.func.count(Statement.id).label('statement_count')
    ).outerjoin(Statement, Block.id == Statement.block_id)\
     .group_by(Block.id)\
     .order_by(Block.index.desc())
    pagination = blocks_query.paginate(page=page, per_page=per_page, error_out=False)
    blocks_with_counts = pagination.items
    total_blocks = db.session.query(Block).count()
    return render_template("blockchain/blocks.html", blocks_with_counts=blocks_with_counts, pagination=pagination, total_blocks=total_blocks)


@blockchain_bp.route("/blockchain/blocks/<int:block_id>")
@login_required
def blockchain_block_detail(block_id: int):
    from models import Block, Statement
    block = Block.query.get_or_404(block_id)
    statements = Statement.query.filter_by(block_id=block.id).order_by(Statement.created_at.asc()).all()
    prev_block = Block.query.filter(Block.index < block.index).order_by(Block.index.desc()).first()
    next_block = Block.query.filter(Block.index > block.index).order_by(Block.index.asc()).first()
    return render_template("blockchain/block_detail.html", block=block, statements=statements, prev_block=prev_block, next_block=next_block)


@blockchain_bp.route("/blockchain/statements/<int:statement_id>")
@login_required
def blockchain_statement_detail(statement_id: int):
    from models import Statement
    stmt = Statement.query.get_or_404(statement_id)
    return render_template("blockchain/statement_detail.html", stmt=stmt)


def _build_reputation_snapshot(user) -> dict:
    from models import HelpRequest, HelpOffer
    requests_completed = HelpRequest.query.filter_by(user_id=user.id, status="completed").count()
    helps_completed = HelpOffer.query.filter_by(helper_id=user.id, status="completed").count()
    total_offers_attempted = HelpOffer.query.filter(
        HelpOffer.helper_id == user.id, HelpOffer.status.in_(["accepted", "completed", "rejected"])
    ).count()
    success_rate = int((helps_completed / total_offers_attempted) * 100) if total_offers_attempted else 0
    score = float(getattr(user, "reputation_score", 0.0) or 0.0)
    tier = "新手"
    if score >= 80:
        tier = "专家"
    elif score >= 50:
        tier = "可信赖"
    elif score >= 20:
        tier = "帮助者"
    snapshot = {
        "source": "dailyhelper_reputation_snapshot",
        "user_id": user.id, "username": user.username,
        "reputation_score": score, "tier": tier,
        "requests_completed": requests_completed, "helps_completed": helps_completed,
        "success_rate": success_rate,
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
    }
    snapshot_blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot["snapshot_hash"] = hashlib.sha256(snapshot_blob).hexdigest()
    return snapshot


@blockchain_bp.route("/blockchain/reputation/proof/<string:username>")
@login_required
def reputation_proof(username: str):
    from models import User, Statement
    user = User.query.filter_by(username=username).first_or_404()
    snapshot = _build_reputation_snapshot(user)
    latest_anchor = Statement.query.filter_by(user_id=user.id, kind="reputation_snapshot_anchored").order_by(Statement.created_at.desc()).first()
    return jsonify({"ok": True, "snapshot": snapshot, "latest_anchor": latest_anchor.payload if latest_anchor else None})


@blockchain_bp.route("/blockchain/reputation/anchor", methods=["POST"])
@login_required
def anchor_my_reputation():
    snapshot = _build_reputation_snapshot(current_user)
    anchor_text = json.dumps({"source": "dailyhelper_reputation_anchor", "snapshot_hash": snapshot["snapshot_hash"], "snapshot": snapshot}, sort_keys=True, separators=(",", ":"))
    try:
        tx = submit_anchor_transaction(anchor_text)
        append_statement(
            kind="reputation_snapshot_anchored",
            payload={
                "snapshot_hash": snapshot["snapshot_hash"], "reputation_score": snapshot["reputation_score"],
                "tier": snapshot["tier"], "tx_hash": tx.get("tx_hash"), "chain_id": tx.get("chain_id"),
                "tx_status": tx.get("status"), "tx_url": tx.get("tx_url"),
                "anchored_at": datetime.now(timezone.utc).isoformat() + "Z",
            },
            user_id=current_user.id,
        )
        maybe_seal_block()
        flash(f"信誉快照已上链：{tx.get('tx_hash')}", "success")
    except Exception as e:  # noqa: BLE001
        try:
            append_statement(
                kind="reputation_snapshot_anchor_failed",
                payload={"snapshot_hash": snapshot["snapshot_hash"], "error": str(e)[:500], "failed_at": datetime.now(timezone.utc).isoformat() + "Z"},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:
            pass
        flash(f"信誉快照上链失败：{e}", "error")
    return redirect(url_for("profile.profile_view", username=current_user.username))
