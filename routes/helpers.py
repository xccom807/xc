"""Shared helper functions and decorators used across all blueprints."""

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user

from extensions import db
from models import Notification


def admin_required(view_func):
    """Decorator: restrict access to admin users."""
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, "user_type", "user") != "admin":
            flash("需要管理员权限。", "error")
            return redirect(url_for("main.dashboard"))
        return view_func(*args, **kwargs)
    return _wrapped


def notify(user_id: int, kind: str, message: str, link: str | None = None) -> None:
    """Create an in-app notification for a user."""
    n = Notification(user_id=user_id, kind=kind, message=message, link=link)
    db.session.add(n)
