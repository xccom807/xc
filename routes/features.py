"""Feature routes: request help, offer help, request detail, marketplace, volunteer, nearby, flag, cancel, edit, my_offers, NGO."""

import math
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, or_, and_
from web3 import Web3

from extensions import db
from blockchain_service import append_statement, maybe_seal_block
from web3_service import submit_anchor_transaction
from routes.helpers import notify

features_bp = Blueprint("features", __name__)


@features_bp.route("/request-help", methods=["GET", "POST"])
@login_required
def request_help():
    if getattr(current_user, "user_type", "user") == "admin":
        flash("管理员无需发布求助。", "info")
        return redirect(url_for("admin.admin_index"))
    from models import HelpRequest
    from forms import RequestHelpForm

    if getattr(current_user, "is_blacklisted", False):
        flash("您的账号已被列入黑名单，无法发布求助。", "error")
        return redirect(url_for("main.dashboard"))

    form = RequestHelpForm()
    if form.validate_on_submit():
        desc = form.description.data
        if form.skills_required.data:
            desc += f"\n\n所需技能: {form.skills_required.data}"
        if form.notes.data:
            desc += f"\n\n补充说明: {form.notes.data}"

        hr = HelpRequest(
            user_id=current_user.id,
            title=form.title.data,
            description=desc,
            category=form.category.data,
            location=form.location.data or None,
            time_needed=(form.datetime_needed.data.strftime("%Y-%m-%d %H:%M") if form.datetime_needed.data else form.duration_estimate.data or None),
            price=float(form.price_offered.data) if (form.price_offered.data and not form.is_volunteer.data) else None,
            is_volunteer=bool(form.is_volunteer.data),
        )
        db.session.add(hr)
        db.session.commit()

        try:
            append_statement(
                kind="request_create",
                payload={
                    "request_id": hr.id,
                    "title": hr.title,
                    "category": hr.category,
                    "is_volunteer": hr.is_volunteer,
                    "price": float(hr.price) if hr.price else None,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("求助发布成功。", "success")
        return redirect(url_for("features.request_help"))

    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")

    my_requests = (
        HelpRequest.query.filter_by(user_id=current_user.id)
        .order_by(HelpRequest.created_at.desc()).all()
    )
    return render_template("features/request_help.html", form=form, my_requests=my_requests)


@features_bp.route("/offer-help")
@login_required
def offer_help():
    if getattr(current_user, "user_type", "user") == "admin":
        flash("管理员无需提供帮助。", "info")
        return redirect(url_for("admin.admin_index"))
    from models import HelpRequest, HelpOffer

    my_offer_ids = set(
        r[0] for r in db.session.query(HelpOffer.request_id).filter_by(helper_id=current_user.id).all()
    )
    q = HelpRequest.query.filter(
        HelpRequest.status == "open",
        HelpRequest.user_id != current_user.id,
    ).order_by(HelpRequest.created_at.desc())

    page = int(request.args.get("page", 1) or 1)
    per_page = 12
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items

    my_active_offers = (
        HelpOffer.query.filter_by(helper_id=current_user.id)
        .filter(HelpOffer.status.in_(["pending", "accepted"]))
        .order_by(HelpOffer.created_at.desc()).limit(10).all()
    )

    return render_template(
        "features/offer_help.html",
        items=items,
        pagination=pagination,
        my_offer_ids=my_offer_ids,
        my_active_offers=my_active_offers,
    )


@features_bp.route("/requests/<int:request_id>", methods=["GET", "POST"])
@login_required
def request_detail(request_id: int):
    from models import HelpRequest, User, HelpOffer, Review
    from forms import OfferHelpForm, ReviewForm, AcceptOfferForm, CompleteTaskForm, CancelRequestForm

    req = HelpRequest.query.get_or_404(request_id)
    requester = User.query.get(req.user_id)

    offer_form = OfferHelpForm()
    review_form = ReviewForm()
    accept_form = AcceptOfferForm()
    complete_form = CompleteTaskForm()
    cancel_form = CancelRequestForm()

    all_offers = HelpOffer.query.filter_by(request_id=request_id).order_by(HelpOffer.created_at.desc()).all()
    is_requester = current_user.id == req.user_id

    # Handle offer submit
    if getattr(current_user, "is_blacklisted", False) and offer_form.submit.data:
        flash("您的账号已被列入黑名单，无法提供帮助。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))
    if offer_form.submit.data and offer_form.validate_on_submit():
        if current_user.id == req.user_id:
            flash("不能给自己的求助提交帮助。", "error")
            return redirect(url_for("features.request_detail", request_id=req.id))
        existing_offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=current_user.id).first()
        if existing_offer:
            flash("您已对该求助提交过帮助申请，无法重复提交。", "error")
            return redirect(url_for("features.request_detail", request_id=req.id))
        msg = offer_form.message.data
        if offer_form.availability.data:
            msg += "\n\n可用性: 可以立即开始。"
        if offer_form.timeframe.data:
            msg += f"\n\n预计时间: {offer_form.timeframe.data}"
        offer = HelpOffer(
            request_id=req.id,
            helper_id=current_user.id,
            message=msg,
            status="pending",
        )
        db.session.add(offer)
        db.session.commit()

        try:
            append_statement(
                kind="offer_submit",
                payload={"request_id": req.id, "offer_id": offer.id, "message_length": len(offer.message or "")},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("帮助提议已发送给求助者。", "success")
        notify(
            req.user_id,
            "offer_received",
            f"{current_user.username} 对您的求助「{req.title[:40]}」提交了帮助提议",
            url_for("features.request_detail", request_id=req.id),
        )
        db.session.commit()
        return redirect(url_for("features.request_detail", request_id=req.id))

    # Handle offer acceptance (only by requester)
    if is_requester and accept_form.submit.data:
        offer_id = request.form.get('offer_id')
        if offer_id:
            offer = HelpOffer.query.get_or_404(offer_id)
            if offer.request_id == req.id and offer.status == "pending":
                if req.price and not req.is_volunteer:
                    flash("付费任务必须先通过 Escrow 合约锁定赏金，不能直接接受帮助申请。", "error")
                    return redirect(url_for("features.request_detail", request_id=req.id))
                HelpOffer.query.filter_by(request_id=req.id, status="pending").update({"status": "rejected"})
                offer.status = "accepted"
                req.status = "in_progress"
                db.session.commit()

                try:
                    append_statement(
                        kind="offer_accepted",
                        payload={"request_id": req.id, "offer_id": offer.id, "helper_id": offer.helper_id, "requester_id": current_user.id},
                        user_id=current_user.id,
                    )
                    maybe_seal_block()
                except Exception:  # noqa: BLE001
                    pass

                flash(f"已接受来自 {offer.helper.full_name or offer.helper.username} 的帮助！", "success")
                notify(
                    offer.helper_id,
                    "offer_accepted",
                    f"您对「{req.title[:40]}」的帮助提议已被接受！",
                    url_for("features.request_detail", request_id=req.id),
                )
                rejected = HelpOffer.query.filter_by(request_id=req.id, status="rejected").filter(HelpOffer.helper_id != offer.helper_id).all()
                for ro in rejected:
                    notify(
                        ro.helper_id,
                        "offer_rejected",
                        f"您对「{req.title[:40]}」的帮助提议未被选中",
                        url_for("features.request_detail", request_id=req.id),
                    )
                db.session.commit()
                return redirect(url_for("features.request_detail", request_id=req.id))

    # Handle task completion (only by requester)
    if is_requester and complete_form.submit.data and req.status == "in_progress":
        accepted_offer = HelpOffer.query.filter_by(request_id=req.id, status="accepted").first()
        if accepted_offer:
            req.status = "completed"
            accepted_offer.status = "completed"
            db.session.commit()

            onchain_result = None
            onchain_error = None
            anchor_payload = json.dumps(
                {
                    "source": "task_completed",
                    "request_id": req.id,
                    "requester_id": current_user.id,
                    "helper_id": accepted_offer.helper_id,
                    "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            try:
                onchain_result = submit_anchor_transaction(anchor_payload)
            except Exception as e:  # noqa: BLE001
                onchain_error = str(e)
            try:
                append_statement(
                    kind="task_completed",
                    payload={
                        "request_id": req.id,
                        "helper_id": accepted_offer.helper_id,
                        "requester_id": current_user.id,
                        "onchain_tx_hash": onchain_result.get("tx_hash") if onchain_result else None,
                        "onchain_chain_id": onchain_result.get("chain_id") if onchain_result else None,
                        "onchain_tx_status": onchain_result.get("status") if onchain_result else None,
                        "onchain_tx_url": onchain_result.get("tx_url") if onchain_result else None,
                        "onchain_error": onchain_error,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass

            if onchain_result:
                flash(f"任务已标记完成，且已上链：{onchain_result.get('tx_hash')}", "success")
            elif onchain_error:
                flash(f"任务已标记完成，但上链失败：{onchain_error}", "error")
            else:
                flash("任务已标记为完成！您现在可以进行评价。", "success")
            notify(
                accepted_offer.helper_id,
                "task_completed",
                f"求助者已将「{req.title[:40]}」标记为完成，请互相评价！",
                url_for("features.request_detail", request_id=req.id),
            )
            db.session.commit()
            return redirect(url_for("features.request_detail", request_id=req.id))

    # Handle review submit
    if getattr(current_user, "is_blacklisted", False) and review_form.submit.data:
        flash("您的账号已被列入黑名单，无法提交评价。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))
    if review_form.submit.data and review_form.validate_on_submit():
        completed = HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
        if not completed or req.status != "completed":
            flash("仅已完成的任务可以评价。", "error")
            return redirect(url_for("features.request_detail", request_id=req.id))

        if current_user.id == req.user_id:
            reviewee_id = completed.helper_id
        elif current_user.id == completed.helper_id:
            reviewee_id = req.user_id
        else:
            flash("您不是该任务的参与者。", "error")
            return redirect(url_for("features.request_detail", request_id=req.id))

        exists = Review.query.filter_by(request_id=req.id, reviewer_id=current_user.id).first()
        if exists:
            flash("您已经评价过该任务。", "error")
            return redirect(url_for("features.request_detail", request_id=req.id))

        rating = int(review_form.rating.data)
        comment = (review_form.comment.data or "").strip()
        rv = Review(
            request_id=req.id,
            reviewer_id=current_user.id,
            reviewee_id=reviewee_id,
            rating=rating,
            comment=comment or None,
        )
        db.session.add(rv)

        # Logarithmic reputation update
        reviewee = User.query.get(reviewee_id)
        delta = 0
        if reviewee is not None:
            current_score = float(reviewee.reputation_score or 0.0)
            base_points_map = {5: 5, 4: 3, 3: 1, 2: -2, 1: -4}
            base_points = base_points_map.get(rating, 0)
            comment_len = len(comment)
            if comment_len >= 200:
                comment_bonus = 1.8
            elif comment_len >= 50:
                comment_bonus = 1.5
            elif comment_len >= 10:
                comment_bonus = 1.2
            else:
                comment_bonus = 1.0
            if base_points > 0:
                diminishing = 1.0 / math.log2(current_score + 2)
                delta = base_points * diminishing * comment_bonus
            else:
                delta = base_points * comment_bonus
            delta = round(delta, 2)
            new_score = max(0.0, min(100.0, current_score + delta))
            reviewee.reputation_score = new_score

        try:
            append_statement(
                kind="review_submit",
                payload={"request_id": req.id, "review_id": rv.id, "rating": rating, "reviewee_id": reviewee_id, "reputation_change": delta},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        db.session.commit()
        flash("评价已提交。", "success")
        stars = "★" * rating + "☆" * (5 - rating)
        notify(
            reviewee_id,
            "review_received",
            f"{current_user.username} 给您留下了评价 {stars}（任务：{req.title[:30]}）",
            url_for("features.request_detail", request_id=req.id),
        )
        db.session.commit()
        return redirect(url_for("features.request_detail", request_id=req.id))

    if request.method == "POST" and (offer_form.errors or review_form.errors or accept_form.errors or complete_form.errors):
        for f in (offer_form, review_form, accept_form, complete_form):
            for field, errs in f.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

    my_offer = None
    if current_user.is_authenticated:
        my_offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=current_user.id).order_by(HelpOffer.created_at.desc()).first()

    request_reviews = Review.query.filter_by(request_id=req.id).order_by(Review.created_at.desc()).all()

    can_review = False
    if req.status == "completed":
        completed_offer = HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
        if completed_offer and current_user.id in (req.user_id, completed_offer.helper_id):
            already = db.session.query(Review.id).filter_by(request_id=req.id, reviewer_id=current_user.id).first()
            can_review = already is None

    is_helper = False
    if current_user.is_authenticated and req.status in ("in_progress", "completed", "disputed"):
        active_offer = HelpOffer.query.filter_by(request_id=req.id, helper_id=current_user.id).filter(HelpOffer.status.in_(("accepted", "completed"))).first()
        if active_offer:
            is_helper = True

    payment = None
    if req.price and not req.is_volunteer:
        from models import Payment
        payment = Payment.query.filter_by(request_id=req.id).first()

    return render_template(
        "features/request_detail.html",
        req=req,
        requester=requester,
        form=offer_form,
        review_form=review_form,
        accept_form=accept_form,
        complete_form=complete_form,
        cancel_form=cancel_form,
        all_offers=all_offers,
        is_requester=is_requester,
        my_offer=my_offer,
        request_reviews=request_reviews,
        can_review=can_review,
        payment=payment,
        is_helper=is_helper,
    )


@features_bp.route("/requests/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_request(request_id: int):
    from models import HelpRequest, HelpOffer
    from forms import CancelRequestForm

    form = CancelRequestForm()
    req = HelpRequest.query.get_or_404(request_id)

    if req.user_id != current_user.id:
        flash("您无权取消该求助。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))
    if req.status not in ("open", "in_progress"):
        flash("该求助当前状态无法取消。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))
    if req.status == "in_progress" and req.price and not req.is_volunteer:
        flash("付费任务的赏金已进入 Escrow 托管，不能直接取消。请在任务详情页释放赏金或发起仲裁退款。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))

    if form.validate_on_submit():
        old_status = req.status
        req.status = "cancelled"
        HelpOffer.query.filter_by(request_id=req.id, status="pending").update({"status": "rejected"})
        if old_status == "in_progress":
            accepted_offers = HelpOffer.query.filter_by(request_id=req.id, status="accepted").all()
            for offer in accepted_offers:
                offer.status = "rejected"
                notify(
                    offer.helper_id,
                    "request_cancelled",
                    f"求助「{req.title[:40]}」已被求助者取消。",
                    url_for("features.request_detail", request_id=req.id),
                )
        db.session.commit()

        try:
            append_statement(kind="request_cancelled", payload={"request_id": req.id, "previous_status": old_status}, user_id=current_user.id)
            maybe_seal_block()
        except Exception:
            pass

        flash("求助已取消。", "success")
    return redirect(url_for("features.request_help"))


@features_bp.route("/requests/<int:request_id>/edit", methods=["GET", "POST"])
@login_required
def edit_request(request_id: int):
    from models import HelpRequest
    from forms import EditRequestForm

    req = HelpRequest.query.get_or_404(request_id)
    if req.user_id != current_user.id:
        flash("您无权编辑该求助。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))
    if req.status != "open":
        flash("只有状态为「开放」的求助可以编辑。", "error")
        return redirect(url_for("features.request_detail", request_id=req.id))

    form = EditRequestForm(obj=req)
    if form.validate_on_submit():
        desc = form.description.data
        if form.skills_required.data:
            desc += f"\n\n所需技能: {form.skills_required.data}"
        if form.notes.data:
            desc += f"\n\n补充说明: {form.notes.data}"
        req.title = form.title.data
        req.description = desc
        req.category = form.category.data
        req.location = form.location.data or None
        req.time_needed = (form.datetime_needed.data.strftime("%Y-%m-%d %H:%M") if form.datetime_needed.data else form.duration_estimate.data or None)
        req.price = float(form.price_offered.data) if (form.price_offered.data and not form.is_volunteer.data) else None
        req.is_volunteer = bool(form.is_volunteer.data)
        db.session.commit()

        try:
            append_statement(kind="request_edited", payload={"request_id": req.id, "title": req.title, "category": req.category}, user_id=current_user.id)
            maybe_seal_block()
        except Exception:
            pass

        flash("求助已更新。", "success")
        return redirect(url_for("features.request_detail", request_id=req.id))

    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
    return render_template("features/edit_request.html", form=form, req=req)


@features_bp.route("/flag/<string:content_type>/<int:content_id>", methods=["GET", "POST"])
@login_required
def flag_content(content_type: str, content_id: int):
    from models import Flag, HelpRequest, User
    from forms import FlagForm

    if getattr(current_user, "is_blacklisted", False):
        flash("您的账号已被列入黑名单，无法举报。", "error")
        return redirect(request.referrer or url_for("main.index"))
    if content_type not in ("request", "user", "review"):
        abort(400)

    if content_type == "request":
        obj = HelpRequest.query.get_or_404(content_id)
        content_label = f"求助「{obj.title[:40]}」"
    elif content_type == "user":
        obj = User.query.get_or_404(content_id)
        content_label = f"用户「{obj.username}」"
    else:
        from models import Review
        obj = Review.query.get_or_404(content_id)
        content_label = f"评价 #{obj.id}"

    existing = Flag.query.filter_by(content_type=content_type, content_id=content_id).filter(Flag.status == "pending").first()

    form = FlagForm()
    if form.validate_on_submit():
        if existing:
            flash("该内容已被举报，正在等待审核。", "info")
            return redirect(request.referrer or url_for("main.index"))

        reason_text = form.reason.data
        if form.detail.data:
            reason_text += f" — {form.detail.data}"

        flag = Flag(
            content_type=content_type,
            content_id=content_id,
            reporter_id=current_user.id,
            reason=reason_text,
            status="pending",
        )
        db.session.add(flag)
        db.session.commit()

        try:
            append_statement(
                kind="content_flagged",
                payload={"content_type": content_type, "content_id": content_id, "reason": reason_text[:200]},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:
            pass

        flash("举报已提交，管理员将尽快审核。", "success")
        return redirect(request.referrer or url_for("main.index"))

    return render_template("flag.html", form=form, content_type=content_type, content_id=content_id, content_label=content_label)


@features_bp.route("/volunteer")
def volunteer():
    from models import HelpOffer, HelpRequest

    page = int(request.args.get("page", 1) or 1)
    per_page = 9
    q = HelpRequest.query.filter(
        HelpRequest.status == "open",
        HelpRequest.is_volunteer.is_(True),
    ).order_by(HelpRequest.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    categories = ["烹饪", "清洁", "搬运", "辅导", "跑腿", "技术支持", "其他"]
    completed_volunteer = HelpRequest.query.filter(
        HelpRequest.is_volunteer.is_(True),
        HelpRequest.status == "completed",
    ).count()
    active_volunteers = (
        db.session.query(func.count(func.distinct(HelpOffer.helper_id)))
        .join(HelpRequest, HelpOffer.request_id == HelpRequest.id)
        .filter(HelpRequest.is_volunteer.is_(True), HelpOffer.status.in_(["accepted", "completed"]))
        .scalar() or 0
    )
    return render_template(
        "features/marketplace.html",
        items=pagination.items,
        pagination=pagination,
        categories=categories,
        vol_stats={"est_hours": completed_volunteer * 2, "people_helped": completed_volunteer, "active_volunteers": active_volunteers},
        filters={"category": "", "location": "", "min_price": "", "max_price": "", "include_volunteer": "on", "start_date": "", "end_date": "", "sort": "newest"},
    )


@features_bp.route("/nearby")
@login_required
def nearby():
    from models import User

    if current_user.latitude is None or current_user.longitude is None:
        flash("请在个人资料中设置您的位置（经纬度）以查看附近的人。", "info")
        return redirect(url_for("profile.profile_edit"))

    try:
        radius_km = float(request.args.get("radius", 5))
    except Exception:
        radius_km = 5.0
    skill_q = request.args.get("skills", "").strip() or None
    try:
        rep_min = float(request.args.get("rep_min", 0))
    except Exception:
        rep_min = 0.0

    candidates = User.query.filter(
        User.id != current_user.id, User.latitude.isnot(None), User.longitude.isnot(None),
        User.is_blacklisted.is_(False), User.reputation_score >= rep_min,
    ).all()

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    results = []
    for u in candidates:
        dist = haversine(current_user.latitude, current_user.longitude, float(u.latitude), float(u.longitude))
        if dist <= radius_km:
            if skill_q and not (u.skills and skill_q.lower() in u.skills.lower()):
                continue
            results.append({"user": u, "distance": round(dist, 2)})
    results.sort(key=lambda x: (x["distance"], -(x["user"].reputation_score or 0)))

    return render_template("features/nearby.html", results=results, filters={"radius": radius_km, "skills": skill_q or "", "rep_min": rep_min})


@features_bp.route("/marketplace")
def marketplace():
    from models import HelpRequest

    q = HelpRequest.query.filter(HelpRequest.status == "open")

    category = request.args.get("category", "").strip()
    location_q = request.args.get("location", "").strip()
    min_price = request.args.get("min_price", "").strip()
    max_price = request.args.get("max_price", "").strip()
    include_volunteer = request.args.get("include_volunteer", "on")
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    sort = request.args.get("sort", "newest")
    page = int(request.args.get("page", 1) or 1)
    per_page = 9

    if category:
        q = q.filter(HelpRequest.category == category)
    if location_q:
        q = q.filter(HelpRequest.location.ilike(f"%{location_q}%"))

    price_filters = []
    if min_price:
        try:
            price_filters.append(HelpRequest.price >= float(min_price))
        except ValueError:
            pass
    if max_price:
        try:
            price_filters.append(HelpRequest.price <= float(max_price))
        except ValueError:
            pass
    if price_filters:
        range_filter = and_(*price_filters)
        if include_volunteer:
            q = q.filter(or_(HelpRequest.is_volunteer.is_(True), range_filter))
        else:
            q = q.filter(range_filter, HelpRequest.is_volunteer.is_(False))
    else:
        if not include_volunteer:
            q = q.filter(HelpRequest.is_volunteer.is_(False))

    def parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if sd:
        q = q.filter(HelpRequest.created_at >= sd)
    if ed:
        q = q.filter(HelpRequest.created_at < ed + timedelta(days=1))

    if sort == "price_high_low":
        q = q.order_by(HelpRequest.price.desc().nullslast(), HelpRequest.created_at.desc())
    elif sort == "price_low_high":
        q = q.order_by(HelpRequest.price.asc().nullsfirst(), HelpRequest.created_at.desc())
    elif sort == "urgent":
        q = q.order_by(HelpRequest.created_at.asc())
    else:
        q = q.order_by(HelpRequest.created_at.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    categories = ["烹饪", "清洁", "搬运", "辅导", "跑腿", "技术支持", "其他"]

    from models import HelpOffer
    completed_volunteer = HelpRequest.query.filter(HelpRequest.is_volunteer.is_(True), HelpRequest.status == "completed").count()
    active_volunteers = (
        db.session.query(func.count(func.distinct(HelpOffer.helper_id)))
        .join(HelpRequest, HelpOffer.request_id == HelpRequest.id)
        .filter(HelpRequest.is_volunteer.is_(True), HelpOffer.status.in_(["accepted", "completed"]))
        .scalar() or 0
    )
    vol_stats = {"est_hours": completed_volunteer * 2, "people_helped": completed_volunteer, "active_volunteers": active_volunteers}

    ctx = dict(
        items=pagination.items, pagination=pagination, categories=categories,
        vol_stats=vol_stats,
        filters={"category": category, "location": location_q, "min_price": min_price, "max_price": max_price,
                 "include_volunteer": include_volunteer, "start_date": start_date, "end_date": end_date, "sort": sort},
    )
    if request.headers.get("HX-Request"):
        return render_template("partials/marketplace_results.html", **ctx)
    return render_template("features/marketplace.html", **ctx)


@features_bp.route("/my-offers")
@login_required
def my_offers():
    if getattr(current_user, "user_type", "user") == "admin":
        return redirect(url_for("admin.admin_index"))
    from models import HelpOffer

    offers = HelpOffer.query.filter_by(helper_id=current_user.id).order_by(HelpOffer.created_at.desc()).all()
    grouped = {
        "pending": [o for o in offers if o.status == "pending"],
        "accepted": [o for o in offers if o.status == "accepted"],
        "rejected": [o for o in offers if o.status == "rejected"],
        "completed": [o for o in offers if o.status == "completed"],
    }
    badge_counts = {k: len(v) for k, v in grouped.items()}
    return render_template("features/my_offers.html", grouped=grouped, badge_counts=badge_counts)
