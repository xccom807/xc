"""Profile routes: view and edit user profiles."""

import os
import uuid

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from blockchain_service import append_statement, maybe_seal_block

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/u/<string:username>")
def profile_view(username: str):
    from models import User, HelpRequest, HelpOffer, Review, Statement

    user = User.query.filter_by(username=username).first_or_404()
    requests_completed = HelpRequest.query.filter_by(user_id=user.id, status="completed").count()
    helps_completed = HelpOffer.query.filter_by(helper_id=user.id, status="completed").count()
    total_offers_attempted = HelpOffer.query.filter(
        HelpOffer.helper_id == user.id, HelpOffer.status.in_(["accepted", "completed", "rejected"])
    ).count()
    success_rate = int((helps_completed / total_offers_attempted) * 100) if total_offers_attempted else 0

    score = float(getattr(user, "reputation_score", 0.0) or 0.0)
    if score >= 80:
        tier = "专家"
    elif score >= 50:
        tier = "可信赖"
    elif score >= 20:
        tier = "帮助者"
    else:
        tier = "新手"

    page = int(request.args.get("page", 1) or 1)
    per_page = 5
    reviews = Review.query.filter_by(reviewee_id=user.id).order_by(Review.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    latest_reputation_anchor = Statement.query.filter_by(user_id=user.id, kind="reputation_snapshot_anchored").order_by(Statement.created_at.desc()).first()

    return render_template(
        "profile/view.html",
        profile_user=user,
        stats={"requests_completed": requests_completed, "helps_completed": helps_completed, "success_rate": success_rate},
        tier=tier, reviews=reviews, latest_reputation_anchor=latest_reputation_anchor,
        can_anchor_reputation=(current_user.is_authenticated and current_user.id == user.id),
    )


@profile_bp.route("/settings/profile", methods=["GET", "POST"])
@login_required
def profile_edit():
    from forms import ProfileForm

    user = current_user
    form = ProfileForm(obj=user)
    if form.validate_on_submit():
        user.full_name = form.full_name.data or None
        user.phone = form.phone.data or None
        user.location = form.location.data or None
        user.bio = form.bio.data or None
        user.skills = form.skills.data or None

        if form.avatar.data:
            file = form.avatar.data
            if hasattr(file, 'filename') and file.filename:
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                filename = f"{uuid.uuid4().hex}.{ext}"
                upload_dir = os.path.join(current_app.static_folder, 'uploads', 'avatars')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                if user.avatar_url and user.avatar_url.startswith('/static/uploads/avatars/'):
                    old_path = os.path.join(current_app.root_path, user.avatar_url.lstrip('/'))
                    if os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass
                user.avatar_url = f"/static/uploads/avatars/{filename}"

        try:
            user.latitude = float(form.latitude.data) if form.latitude.data is not None else None
        except Exception:
            user.latitude = None
        try:
            user.longitude = float(form.longitude.data) if form.longitude.data is not None else None
        except Exception:
            user.longitude = None
        db.session.commit()

        try:
            append_statement(
                kind="profile_update",
                payload={"updated_fields": [field for field in ["full_name", "phone", "location", "bio", "skills", "avatar", "latitude", "longitude"] if getattr(form, field).data is not None]},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("个人资料已更新。", "success")
        return redirect(url_for("profile.profile_view", username=user.username))

    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
    return render_template("profile/edit.html", form=form)
