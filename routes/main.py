"""Main routes: index, dashboard, notifications, static pages, search, leaderboard."""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from extensions import db

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    from models import HelpRequest, HelpOffer, User

    total_users = db.session.query(func.count(User.id)).scalar()
    total_requests = db.session.query(func.count(HelpRequest.id)).scalar()
    completed_requests = db.session.query(func.count(HelpRequest.id)).filter(
        HelpRequest.status == "completed"
    ).scalar()
    total_helpers = (
        db.session.query(func.count(func.distinct(HelpOffer.helper_id)))
        .filter(HelpOffer.status.in_(["accepted", "completed"]))
        .scalar()
    )

    latest_requests = (
        HelpRequest.query.filter_by(status="open")
        .order_by(HelpRequest.created_at.desc())
        .limit(6)
        .all()
    )
    top_helpers = (
        db.session.query(User, func.count(HelpOffer.id).label("cnt"))
        .join(HelpOffer, HelpOffer.helper_id == User.id)
        .filter(HelpOffer.status == "completed")
        .group_by(User.id)
        .order_by(func.count(HelpOffer.id).desc())
        .limit(5)
        .all()
    )

    return render_template(
        "index.html",
        stats={
            "users": total_users,
            "requests": total_requests,
            "completed": completed_requests,
            "helpers": total_helpers,
        },
        latest_requests=latest_requests,
        top_helpers=top_helpers,
    )


@main_bp.route("/about")
def about():
    return render_template("about.html")


@main_bp.route("/help")
def help_page():
    return render_template("help.html")


@main_bp.route("/terms")
def terms_page():
    return render_template("terms.html")


@main_bp.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@main_bp.route("/post-login-redirect")
@login_required
def post_login_redirect():
    if getattr(current_user, "user_type", "user") == "admin":
        return redirect(url_for("admin.admin_index"))
    return redirect(url_for("main.dashboard"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    if getattr(current_user, "user_type", "user") == "admin":
        return redirect(url_for("admin.admin_index"))
    from models import HelpRequest, HelpOffer, Review, Statement

    total_requests = HelpRequest.query.filter_by(user_id=current_user.id).count()
    total_offers = HelpOffer.query.filter_by(helper_id=current_user.id).count()
    requests_completed = HelpRequest.query.filter_by(user_id=current_user.id, status="completed").count()
    helps_completed = HelpOffer.query.filter_by(helper_id=current_user.id, status="completed").count()
    total_offers_attempted = HelpOffer.query.filter(
        HelpOffer.helper_id == current_user.id,
        HelpOffer.status.in_(["accepted", "completed", "rejected"]),
    ).count()
    success_rate = int((helps_completed / total_offers_attempted) * 100) if total_offers_attempted else 0
    reputation = getattr(current_user, "reputation_score", 0.0)
    pending_tasks = HelpRequest.query.filter(
        HelpRequest.user_id == current_user.id,
        HelpRequest.status.in_(["open", "in_progress"]),
    ).count()

    recent_requests = (
        HelpRequest.query.filter_by(user_id=current_user.id)
        .order_by(HelpRequest.created_at.desc()).limit(5).all()
    )
    recent_offers = (
        HelpOffer.query.filter_by(helper_id=current_user.id)
        .order_by(HelpOffer.created_at.desc()).limit(5).all()
    )
    recent_activity = []
    for r in recent_requests:
        recent_activity.append({"type": "request", "item": r, "time": r.created_at})
    for o in recent_offers:
        recent_activity.append({"type": "offer", "item": o, "time": o.created_at})
    recent_activity.sort(key=lambda x: x["time"], reverse=True)
    recent_activity = recent_activity[:8]

    my_requests = (
        HelpRequest.query.filter_by(user_id=current_user.id)
        .order_by(HelpRequest.created_at.desc()).limit(20).all()
    )
    my_offers = (
        HelpOffer.query.filter_by(helper_id=current_user.id)
        .order_by(HelpOffer.created_at.desc()).limit(20).all()
    )
    received_reviews = (
        Review.query.filter_by(reviewee_id=current_user.id)
        .order_by(Review.created_at.desc()).limit(10).all()
    )
    latest_reputation_anchor = (
        Statement.query.filter_by(user_id=current_user.id, kind="reputation_snapshot_anchored")
        .order_by(Statement.created_at.desc()).first()
    )

    return render_template(
        "dashboard.html",
        stats={
            "total_requests": total_requests,
            "total_offers": total_offers,
            "reputation": reputation,
            "pending_tasks": pending_tasks,
            "requests_completed": requests_completed,
            "helps_completed": helps_completed,
            "success_rate": success_rate,
        },
        recent_activity=recent_activity,
        my_requests=my_requests,
        my_offers=my_offers,
        received_reviews=received_reviews,
        latest_reputation_anchor=latest_reputation_anchor,
    )


@main_bp.route("/notifications")
@login_required
def notifications():
    from models import Notification

    page = int(request.args.get("page", 1) or 1)
    per_page = 15
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    unread_ids = [n.id for n in pagination.items if not n.is_read]
    if unread_ids:
        Notification.query.filter(Notification.id.in_(unread_ids)).update(
            {"is_read": True}, synchronize_session=False
        )
        db.session.commit()
    return render_template("notifications.html", items=pagination.items, pagination=pagination)


@main_bp.route("/search")
def search_page():
    from models import HelpRequest, User

    q = request.args.get("q", "").strip()
    search_type = request.args.get("type", "all")
    page = int(request.args.get("page", 1) or 1)
    per_page = 12

    results_requests = []
    results_users = []
    pagination_requests = None
    pagination_users = None

    if q:
        if search_type in ("all", "requests"):
            rq = HelpRequest.query.filter(
                or_(
                    HelpRequest.title.ilike(f"%{q}%"),
                    HelpRequest.description.ilike(f"%{q}%"),
                    HelpRequest.category.ilike(f"%{q}%"),
                    HelpRequest.location.ilike(f"%{q}%"),
                )
            ).order_by(HelpRequest.created_at.desc())
            pagination_requests = rq.paginate(page=page, per_page=per_page, error_out=False)
            results_requests = pagination_requests.items

        if search_type in ("all", "users"):
            uq = User.query.filter(
                or_(
                    User.username.ilike(f"%{q}%"),
                    User.full_name.ilike(f"%{q}%"),
                    User.location.ilike(f"%{q}%"),
                    User.skills.ilike(f"%{q}%"),
                )
            ).order_by(User.created_at.desc())
            pagination_users = uq.paginate(page=page, per_page=per_page, error_out=False)
            results_users = pagination_users.items

    ctx = dict(
        q=q, search_type=search_type,
        results_requests=results_requests, results_users=results_users,
        pagination_requests=pagination_requests, pagination_users=pagination_users,
    )
    if request.headers.get("HX-Request"):
        return render_template("partials/search_results.html", **ctx)
    return render_template("search.html", **ctx)


@main_bp.route("/leaderboard")
def leaderboard():
    from models import User, HelpRequest, HelpOffer

    top_reputation = User.query.filter(User.user_type != "admin").order_by(
        User.reputation_score.desc()
    ).limit(20).all()
    top_helpers = (
        db.session.query(User, func.count(HelpOffer.id).label("help_count"))
        .join(HelpOffer, HelpOffer.helper_id == User.id)
        .filter(HelpOffer.status == "completed")
        .group_by(User.id)
        .order_by(func.count(HelpOffer.id).desc())
        .limit(20).all()
    )
    top_requesters = (
        db.session.query(User, func.count(HelpRequest.id).label("req_count"))
        .join(HelpRequest, HelpRequest.user_id == User.id)
        .filter(HelpRequest.status == "completed")
        .group_by(User.id)
        .order_by(func.count(HelpRequest.id).desc())
        .limit(20).all()
    )

    return render_template(
        "leaderboard.html",
        top_reputation=top_reputation,
        top_helpers=top_helpers,
        top_requesters=top_requesters,
    )


@main_bp.route("/appeal", methods=["GET", "POST"])
@login_required
def appeal():
    from models import Appeal
    from forms import AppealForm

    if not current_user.is_blacklisted:
        flash("您的账号状态正常，无需申诉。", "info")
        return redirect(url_for("main.dashboard"))

    pending = Appeal.query.filter_by(user_id=current_user.id, status="pending").first()
    history = Appeal.query.filter_by(user_id=current_user.id).order_by(Appeal.created_at.desc()).all()

    form = AppealForm()
    if form.validate_on_submit():
        if pending:
            flash("您已有一条待处理的申诉，请等待管理员回复。", "error")
            return redirect(url_for("main.appeal"))
        ap = Appeal(user_id=current_user.id, reason=form.reason.data.strip())
        db.session.add(ap)
        db.session.commit()
        flash("申诉已提交，请耐心等待管理员处理。", "success")
        return redirect(url_for("main.appeal"))

    return render_template("appeal.html", form=form, pending=pending, history=history)
