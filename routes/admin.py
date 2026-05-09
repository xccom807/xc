"""Admin routes: dashboard, users, moderation, requests, payments, export, broadcast, SBT management."""

import csv
import io

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, Response, current_app
from flask_login import login_required, current_user
from web3 import Web3

from extensions import db
from blockchain_service import append_statement, maybe_seal_block
from routes.helpers import admin_required, notify

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@login_required
@admin_required
def admin_index():
    from models import User, HelpRequest, Flag, Statement
    total_users = db.session.query(User).count()
    total_requests = db.session.query(HelpRequest).count()
    open_requests = db.session.query(HelpRequest).filter_by(status="open").count()
    completed_requests = db.session.query(HelpRequest).filter_by(status="completed").count()
    flagged_pending = db.session.query(Flag).filter_by(status="pending").count()
    recent_signups = User.query.order_by(User.created_at.desc()).limit(8).all()
    recent_activity = Statement.query.order_by(Statement.created_at.desc()).limit(12).all()
    return render_template(
        "admin/index.html",
        totals={
            "users": total_users, "requests": total_requests,
            "open_requests": open_requests, "completed_requests": completed_requests,
            "flagged": flagged_pending,
        },
        recent_signups=recent_signups,
        recent_activity=recent_activity,
    )


@admin_bp.route("/users")
@login_required
@admin_required
def admin_users():
    from models import User
    q = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1) or 1)
    per_page = 20
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter((User.username.ilike(like)) | (User.email.ilike(like)) | (User.full_name.ilike(like)))
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template("admin/users.html", users=users, q=q)


@admin_bp.post("/users/<int:user_id>/blacklist")
@login_required
@admin_required
def admin_blacklist_user(user_id: int):
    from models import User
    reason = (request.form.get("reason") or "").strip() or None
    u = User.query.get_or_404(user_id)
    u.is_blacklisted = True
    u.blacklist_reason = reason
    db.session.commit()
    try:
        append_statement(kind="admin_blacklist", payload={"target_user_id": user_id, "reason": reason, "admin_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    flash("用户已拉黑。", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.post("/users/<int:user_id>/unblacklist")
@login_required
@admin_required
def admin_unblacklist_user(user_id: int):
    from models import User
    u = User.query.get_or_404(user_id)
    u.is_blacklisted = False
    u.blacklist_reason = None
    db.session.commit()
    try:
        append_statement(kind="admin_unblacklist", payload={"target_user_id": user_id, "admin_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    flash("用户已取消拉黑。", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.post("/users/<int:user_id>/delete")
@login_required
@admin_required
def admin_delete_user(user_id: int):
    from models import (
        User, HelpRequest, HelpOffer, Review, Payment,
        Message, Notification, Flag, WalletLink, Statement, Appeal, ChatbotMessage,
    )
    u = User.query.get_or_404(user_id)
    if u.user_type == "admin":
        flash("无法删除管理员账户。", "error")
        return redirect(url_for("admin.admin_users"))

    uname = u.username
    Review.query.filter((Review.reviewer_id == user_id) | (Review.reviewee_id == user_id)).delete(synchronize_session=False)
    Payment.query.filter((Payment.helper_id == user_id) | (Payment.requester_id == user_id)).delete(synchronize_session=False)
    Message.query.filter((Message.sender_id == user_id) | (Message.receiver_id == user_id)).delete(synchronize_session=False)
    Notification.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Appeal.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ChatbotMessage.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Flag.query.filter_by(reporter_id=user_id).delete(synchronize_session=False)
    WalletLink.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Statement.query.filter_by(user_id=user_id).update({"user_id": None}, synchronize_session=False)
    HelpOffer.query.filter_by(helper_id=user_id).delete(synchronize_session=False)
    user_requests = HelpRequest.query.filter_by(user_id=user_id).all()
    for req in user_requests:
        HelpOffer.query.filter_by(request_id=req.id).delete(synchronize_session=False)
    HelpRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.delete(u)
    db.session.commit()
    try:
        append_statement(kind="admin_delete_user", payload={"target_user_id": user_id, "deleted_username": uname, "admin_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    flash(f"用户 {uname} 及其所有数据已删除。", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/moderation")
@login_required
@admin_required
def admin_moderation():
    from models import Flag
    flags = Flag.query.order_by(Flag.created_at.desc()).limit(50).all()
    return render_template("admin/moderation.html", flags=flags)


@admin_bp.post("/flags/<int:flag_id>/<string:action>")
@login_required
@admin_required
def admin_flag_action(flag_id: int, action: str):
    from models import Flag, HelpRequest, User, Review
    fl = Flag.query.get_or_404(flag_id)
    if action not in ("approve", "reject"):
        abort(400)
    if fl.status != "pending":
        flash("该举报已被处理。", "info")
        return redirect(url_for("admin.admin_moderation"))

    fl.status = "approved" if action == "approve" else "rejected"
    if action == "approve":
        if fl.content_type == "request":
            req = HelpRequest.query.get(fl.content_id)
            if req and req.status in ("open", "in_progress"):
                if req.status == "in_progress" and req.price and not req.is_volunteer:
                    flash(f"举报已通过，但求助 #{fl.content_id} 是进行中的付费 Escrow 任务，不能直接关闭。请先走链上释放或仲裁流程。", "error")
                else:
                    req.status = "cancelled"
                    flash(f"举报已通过，求助 #{fl.content_id} 已被关闭。", "success")
            else:
                flash("举报已通过。（被举报的求助已不在活跃状态）", "success")
        elif fl.content_type == "user":
            user = User.query.get(fl.content_id)
            if user and not user.is_blacklisted:
                user.is_blacklisted = True
                user.blacklist_reason = f"因举报被拉黑：{fl.reason or '违规行为'}"
                flash(f"举报已通过，用户 {user.username} 已被拉黑。", "success")
            else:
                flash("举报已通过。（用户已被拉黑或不存在）", "success")
        elif fl.content_type == "review":
            review = Review.query.get(fl.content_id)
            if review:
                db.session.delete(review)
                flash(f"举报已通过，评价 #{fl.content_id} 已被删除。", "success")
            else:
                flash("举报已通过。（评价已不存在）", "success")
        else:
            flash("举报已通过。", "success")
        try:
            append_statement(kind="flag_approved", payload={"flag_id": fl.id, "content_type": fl.content_type, "content_id": fl.content_id, "reason": fl.reason, "admin_id": current_user.id}, user_id=current_user.id)
            maybe_seal_block()
        except Exception:
            pass
    else:
        flash("举报已驳回。", "success")
    db.session.commit()
    return redirect(url_for("admin.admin_moderation"))


@admin_bp.route("/requests")
@login_required
@admin_required
def admin_requests():
    from models import HelpRequest
    q_text = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    page = int(request.args.get("page", 1) or 1)
    per_page = 20
    query = HelpRequest.query
    if q_text:
        like = f"%{q_text}%"
        query = query.filter((HelpRequest.title.ilike(like)) | (HelpRequest.description.ilike(like)))
    if status_filter:
        query = query.filter(HelpRequest.status == status_filter)
    pagination = query.order_by(HelpRequest.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template("admin/requests.html", pagination=pagination, q=q_text, status_filter=status_filter)


@admin_bp.post("/requests/<int:request_id>/cancel")
@login_required
@admin_required
def admin_cancel_request(request_id: int):
    from models import HelpRequest, HelpOffer
    req = HelpRequest.query.get_or_404(request_id)
    if req.status in ("completed", "cancelled"):
        flash("该求助已完成或已取消，无法操作。", "info")
        return redirect(url_for("admin.admin_requests"))
    if req.status in ("in_progress", "disputed") and req.price and not req.is_volunteer:
        flash("付费 Escrow 任务已有链上资金状态，不能在后台直接关闭。请通过详情页释放赏金或仲裁裁决。", "error")
        return redirect(url_for("admin.admin_requests"))
    old_status = req.status
    req.status = "cancelled"
    HelpOffer.query.filter_by(request_id=req.id, status="pending").update({"status": "rejected"})
    accepted_offers = HelpOffer.query.filter_by(request_id=req.id, status="accepted").all()
    for offer in accepted_offers:
        offer.status = "rejected"
        notify(offer.helper_id, "request_cancelled", f"管理员已关闭求助「{req.title[:40]}」。", url_for("features.request_detail", request_id=req.id))
    notify(req.user_id, "request_cancelled", f"管理员已关闭您的求助「{req.title[:40]}」。", url_for("features.request_detail", request_id=req.id))
    db.session.commit()
    try:
        append_statement(kind="admin_cancel_request", payload={"request_id": req.id, "previous_status": old_status, "admin_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:
        pass
    flash(f"求助 #{req.id}「{req.title[:30]}」已被管理员关闭。", "success")
    return redirect(url_for("admin.admin_requests"))


@admin_bp.route("/payments")
@login_required
@admin_required
def admin_payments():
    from models import Payment
    page = int(request.args.get("page", 1) or 1)
    per_page = 20
    status_filter = request.args.get("status", "").strip()
    query = Payment.query
    if status_filter:
        query = query.filter(Payment.status == status_filter)
    pagination = query.order_by(Payment.address_submitted_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template("admin/payments.html", pagination=pagination, status_filter=status_filter)


@admin_bp.route("/export/<string:data_type>")
@login_required
@admin_required
def admin_export(data_type: str):
    from models import User, HelpRequest
    output = io.StringIO()
    writer = csv.writer(output)
    if data_type == "users":
        writer.writerow(["ID", "用户名", "邮箱", "全名", "类型", "信誉分", "黑名单", "注册时间"])
        for u in User.query.order_by(User.id.asc()).all():
            writer.writerow([u.id, u.username, u.email, u.full_name or "", u.user_type, f"{u.reputation_score:.1f}", "是" if u.is_blacklisted else "否", u.created_at.strftime("%Y-%m-%d %H:%M")])
        filename = "users.csv"
    elif data_type == "requests":
        writer.writerow(["ID", "标题", "发布者", "分类", "状态", "价格", "志愿", "创建时间"])
        for r in HelpRequest.query.order_by(HelpRequest.id.asc()).all():
            writer.writerow([r.id, r.title, r.user.username if r.user else r.user_id, r.category or "", r.status, f"{r.price:.2f}" if r.price else "0", "是" if r.is_volunteer else "否", r.created_at.strftime("%Y-%m-%d %H:%M")])
        filename = "requests.csv"
    else:
        abort(404)
    output.seek(0)
    bom = "\ufeff"
    return Response(bom + output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})


@admin_bp.route("/broadcast", methods=["GET", "POST"])
@login_required
@admin_required
def admin_broadcast():
    from models import User, Notification
    if request.method == "POST":
        message = (request.form.get("message") or "").strip()
        if not message:
            flash("公告内容不能为空。", "error")
            return redirect(url_for("admin.admin_broadcast"))
        users = User.query.filter(User.user_type != "admin").all()
        count = 0
        for u in users:
            n = Notification(user_id=u.id, kind="admin_broadcast", message=message, link=None)
            db.session.add(n)
            count += 1
        db.session.commit()
        try:
            append_statement(kind="admin_broadcast", payload={"message": message[:200], "recipient_count": count, "admin_id": current_user.id}, user_id=current_user.id)
            maybe_seal_block()
        except Exception:
            pass
        flash(f"公告已发送给 {count} 位用户。", "success")
        return redirect(url_for("admin.admin_index"))
    return render_template("admin/broadcast.html")


@admin_bp.route("/appeals")
@login_required
@admin_required
def admin_appeals():
    from models import Appeal
    status_filter = request.args.get("status", "").strip()
    query = Appeal.query
    if status_filter:
        query = query.filter(Appeal.status == status_filter)
    appeals = query.order_by(Appeal.created_at.desc()).limit(50).all()
    return render_template("admin/appeals.html", appeals=appeals, status_filter=status_filter)


@admin_bp.post("/appeals/<int:appeal_id>/<string:action>")
@login_required
@admin_required
def admin_appeal_action(appeal_id: int, action: str):
    from datetime import datetime, timezone
    from models import Appeal, User
    if action not in ("approve", "reject"):
        abort(400)
    ap = Appeal.query.get_or_404(appeal_id)
    if ap.status != "pending":
        flash("该申诉已被处理。", "info")
        return redirect(url_for("admin.admin_appeals"))

    admin_reply = (request.form.get("admin_reply") or "").strip()
    ap.admin_reply = admin_reply or None
    ap.resolved_at = datetime.now(timezone.utc)

    if action == "approve":
        ap.status = "approved"
        user = User.query.get(ap.user_id)
        if user:
            user.is_blacklisted = False
            user.blacklist_reason = None
            notify(user.id, "appeal_approved", "您的申诉已通过，账号已恢复正常。", url_for("main.appeal"))
        flash(f"申诉已通过，用户 {user.username if user else ap.user_id} 已解除拉黑。", "success")
    else:
        ap.status = "rejected"
        notify(ap.user_id, "appeal_rejected", f"您的申诉已被驳回。{('理由：' + admin_reply) if admin_reply else ''}", url_for("main.appeal"))
        flash("申诉已驳回。", "success")

    db.session.commit()
    try:
        append_statement(kind=f"appeal_{action}", payload={"appeal_id": ap.id, "user_id": ap.user_id, "admin_id": current_user.id}, user_id=current_user.id)
        maybe_seal_block()
    except Exception:
        pass
    return redirect(url_for("admin.admin_appeals"))


@admin_bp.route("/sbt", methods=["GET", "POST"])
@login_required
@admin_required
def admin_sbt():
    from merkle_service import build_merkle_tree_from_db, update_merkle_root_onchain
    result = None
    tree, entries = build_merkle_tree_from_db(current_app._get_current_object())
    if request.method == "POST":
        result = update_merkle_root_onchain(current_app._get_current_object())
        if result.get("success"):
            try:
                append_statement(kind="merkle_root_update", payload={"root": result["root"], "tx_hash": result["tx_hash"], "eligible_count": result["eligible_count"], "admin_id": current_user.id}, user_id=current_user.id)
                maybe_seal_block()
            except Exception:
                pass
            flash(f"Merkle Root 已上链！共 {result['eligible_count']} 名合格用户。", "success")
        else:
            flash(f"上链失败：{result.get('error', '未知错误')}", "error")
    return render_template("admin/sbt.html", tree=tree, entries=entries, result=result, sbt_address=current_app.config.get("SBT_CONTRACT_ADDRESS", ""))


@admin_bp.route("/escrow-monitor")
@login_required
@admin_required
def admin_escrow_monitor():
    """List all paid in_progress tasks with their chain escrow state."""
    from models import HelpRequest, HelpOffer
    from web3_service import get_web3
    from datetime import datetime, timezone

    paid_in_progress = (
        HelpRequest.query
        .filter(
            HelpRequest.status.in_(("in_progress", "disputed")),
            HelpRequest.price > 0,
            HelpRequest.is_volunteer == False,  # noqa: E712
        )
        .order_by(HelpRequest.created_at.asc())
        .all()
    )

    escrow_addr = current_app.config.get("ESCROW_CONTRACT_ADDRESS", "")
    tasks = []
    w3 = get_web3()
    chain_available = w3 is not None and w3.is_connected() and escrow_addr

    for req in paid_in_progress:
        task_info = {
            "id": req.id,
            "title": req.title,
            "price": req.price,
            "created_at": req.created_at,
            "requester_id": req.user_id,
            "db_status": req.status,
            "accepted_helper": None,
            "chain_status": None,
            "chain_status_label": "",
            "hours_since_created": round((datetime.now(timezone.utc) - req.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1),
        }
        offer = HelpOffer.query.filter_by(request_id=req.id, status="accepted").first()
        if offer:
            task_info["accepted_helper"] = offer.helper_id

        if chain_available:
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
                chain_data = c.functions.getEscrow(int(req.id)).call()
                chain_status = int(chain_data[3])
                status_labels = {0: "不存在", 1: "已锁定", 2: "已完成", 3: "争议中", 4: "已裁决"}
                task_info["chain_status"] = chain_status
                task_info["chain_status_label"] = status_labels.get(chain_status, f"未知({chain_status})")
            except Exception:
                task_info["chain_status_label"] = "读取失败"

        tasks.append(task_info)

    return render_template("admin/escrow_monitor.html", tasks=tasks, chain_available=chain_available)


@admin_bp.post("/escrow-monitor/<int:task_id>/force-resolve")
@login_required
@admin_required
def admin_force_resolve(task_id: int):
    """Admin override: force-resolve a stuck disputed task."""
    from datetime import datetime, timezone
    from models import HelpRequest, HelpOffer, Payment, WalletLink

    req = HelpRequest.query.get_or_404(task_id)
    if req.status not in ("disputed", "in_progress"):
        flash("只能对仲裁中或进行中的付费任务执行强制裁决。", "error")
        return redirect(url_for("admin.admin_escrow_monitor"))
    if not req.price or req.is_volunteer:
        flash("只有付费任务可以执行强制裁决。", "error")
        return redirect(url_for("admin.admin_escrow_monitor"))

    outcome = (request.form.get("outcome") or "").strip()
    if outcome not in ("pay_helper", "refund_requester"):
        flash("请选择裁决结果（打款给帮助者 或 退款给求助者）。", "error")
        return redirect(url_for("admin.admin_escrow_monitor"))

    admin_reason = (request.form.get("admin_reason") or "").strip()
    old_status = req.status
    helper_wins = outcome == "pay_helper"

    req.status = "completed" if helper_wins else "cancelled"
    offer = HelpOffer.query.filter_by(request_id=req.id).filter(
        HelpOffer.status.in_(("accepted", "completed"))
    ).first()
    if offer:
        offer.status = "completed" if helper_wins else "rejected"

    existing_pay = Payment.query.filter_by(request_id=req.id).first()
    helper_wallet = WalletLink.query.filter_by(user_id=offer.helper_id).first() if offer else None
    requester_wallet = WalletLink.query.filter_by(user_id=req.user_id).first()
    recipient = (
        (helper_wallet.address if helper_wallet else "0x0000000000000000000000000000000000000000")
        if helper_wins
        else (requester_wallet.address if requester_wallet else "0x0000000000000000000000000000000000000000")
    )
    if existing_pay:
        existing_pay.status = "paid" if helper_wins else "refunded"
        existing_pay.recipient_address = recipient
        existing_pay.paid_at = datetime.now(timezone.utc)
    else:
        pay = Payment(
            request_id=req.id,
            helper_id=offer.helper_id if offer else 0,
            requester_id=req.user_id,
            recipient_address=recipient,
            amount=req.price,
            status="paid" if helper_wins else "refunded",
            paid_at=datetime.now(timezone.utc),
        )
        db.session.add(pay)

    db.session.commit()
    try:
        append_statement(
            kind="admin_force_resolve",
            payload={
                "task_id": req.id, "outcome": outcome, "admin_reason": admin_reason,
                "old_status": old_status, "new_status": req.status,
                "admin_id": current_user.id,
            },
            user_id=current_user.id,
        )
        maybe_seal_block()
    except Exception:
        pass

    notify(req.user_id, "force_resolved", f"管理员已对任务「{req.title[:30]}」执行强制裁决（{'打款给帮助者' if helper_wins else '退款给求助者'}）。", url_for("features.request_detail", request_id=req.id))
    if offer:
        notify(offer.helper_id, "force_resolved", f"管理员已对任务「{req.title[:30]}」执行强制裁决（{'打款给帮助者' if helper_wins else '退款给求助者'}）。", url_for("features.request_detail", request_id=req.id))
    db.session.commit()
    flash(f"已对任务 #{req.id} 执行强制裁决：{'打款给帮助者' if helper_wins else '退款给求助者'}。", "success")
    return redirect(url_for("admin.admin_escrow_monitor"))
