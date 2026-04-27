"""Authentication routes: signup, login, logout, password reset/change."""

import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, login_user, logout_user, current_user

from extensions import db
from blockchain_service import append_statement, maybe_seal_block

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    from models import User
    from forms import SignUpForm

    form = SignUpForm()
    if form.validate_on_submit():
        existing_email = User.query.filter_by(email=form.email.data.lower()).first()
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_email:
            flash("该邮箱已被注册。", "error")
            return render_template("auth/signup.html", form=form)
        if existing_user:
            flash("该用户名已被占用。", "error")
            return render_template("auth/signup.html", form=form)

        user = User(
            username=form.username.data,
            email=form.email.data.lower(),
            full_name=form.full_name.data or None,
            phone=form.phone.data or None,
            location=form.location.data or None,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        try:
            append_statement(
                kind="signup",
                payload={"username": user.username, "email": user.email},
                user_id=user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass
        flash("账号创建成功，请登录。", "success")
        return redirect(url_for("auth.login"))

    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
    return render_template("auth/signup.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.post_login_redirect"))

    from models import User
    from forms import LoginForm

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            try:
                append_statement(
                    kind="login",
                    payload={"remember": bool(form.remember_me.data)},
                    user_id=user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass
            if user.is_blacklisted:
                flash("⚠️ 您的账号已被管理员列入黑名单，部分功能受限。<a href='/appeal' style='color:var(--accent);text-decoration:underline;'>点此申诉</a>", "warning")
            else:
                flash("登录成功。", "success")
            return redirect(url_for("main.post_login_redirect"))
        flash("邮箱或密码错误。", "error")
    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    uid = getattr(current_user, "id", None)
    logout_user()
    session.clear()
    try:
        append_statement(kind="logout", payload={}, user_id=uid)
        maybe_seal_block()
    except Exception:  # noqa: BLE001
        pass
    flash("您已退出登录。", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    from models import User, PasswordResetToken
    from forms import ForgotPasswordForm

    form = ForgotPasswordForm()
    reset_link = None
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({"used": True})
            token = secrets.token_urlsafe(32)
            prt = PasswordResetToken(user_id=user.id, token=token)
            db.session.add(prt)
            db.session.commit()
            reset_link = url_for("auth.reset_password", token=token, _external=True)
        else:
            flash("如果该邮箱已注册，重置链接已生成。", "info")
            return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot_password.html", form=form, reset_link=reset_link)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    from models import PasswordResetToken
    from forms import ResetPasswordForm

    prt = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if prt is None:
        flash("重置链接无效或已过期。", "error")
        return redirect(url_for("auth.forgot_password"))
    created = prt.created_at if prt.created_at.tzinfo else prt.created_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() > 3600:
        flash("重置链接已过期，请重新申请。", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        prt.user.set_password(form.password.data)
        prt.used = True
        db.session.commit()
        flash("密码已重置，请登录。", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form, token=token)


@auth_bp.route("/settings/password", methods=["GET", "POST"])
@login_required
def change_password():
    from forms import ChangePasswordForm

    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("当前密码不正确。", "error")
            return render_template("auth/change_password.html", form=form)

        current_user.set_password(form.new_password.data)
        db.session.commit()
        try:
            append_statement(kind="password_changed", payload={}, user_id=current_user.id)
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass
        flash("密码修改成功。", "success")
        return redirect(url_for("profile.profile_view", username=current_user.username))

    if request.method == "POST" and form.errors:
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
    return render_template("auth/change_password.html", form=form)
