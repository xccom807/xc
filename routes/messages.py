"""Messages routes: inbox and chat."""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func

from extensions import db
from routes.helpers import notify

messages_bp = Blueprint("messages", __name__)


@messages_bp.route("/messages")
@login_required
def messages_inbox():
    from models import Message, User

    subq = (
        db.session.query(
            func.max(Message.id).label("last_id"),
            db.case(
                (Message.sender_id == current_user.id, Message.receiver_id),
                else_=Message.sender_id,
            ).label("partner_id"),
        )
        .filter(or_(Message.sender_id == current_user.id, Message.receiver_id == current_user.id))
        .group_by("partner_id")
        .subquery()
    )
    conversations = (
        db.session.query(Message, User)
        .join(subq, Message.id == subq.c.last_id)
        .join(User, User.id == subq.c.partner_id)
        .order_by(Message.created_at.desc())
        .all()
    )
    unread_counts = {}
    for msg, partner in conversations:
        cnt = Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False).count()
        unread_counts[partner.id] = cnt
    return render_template("messages/inbox.html", conversations=conversations, unread_counts=unread_counts)


@messages_bp.route("/messages/<int:user_id>", methods=["GET", "POST"])
@login_required
def messages_chat(user_id: int):
    from models import Message, User
    from forms import MessageForm

    partner = User.query.get_or_404(user_id)
    if partner.id == current_user.id:
        flash("不能给自己发消息。", "error")
        return redirect(url_for("messages.messages_inbox"))

    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(sender_id=current_user.id, receiver_id=partner.id, content=form.content.data.strip())
        db.session.add(msg)
        db.session.commit()
        notify(partner.id, "new_message", f"{current_user.username} 给你发了一条私信", url_for("messages.messages_chat", user_id=current_user.id))
        db.session.commit()
        return redirect(url_for("messages.messages_chat", user_id=partner.id))

    Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()

    chat_messages = (
        Message.query.filter(
            or_(
                and_(Message.sender_id == current_user.id, Message.receiver_id == partner.id),
                and_(Message.sender_id == partner.id, Message.receiver_id == current_user.id),
            )
        )
        .order_by(Message.created_at.asc()).limit(200).all()
    )
    return render_template("messages/chat.html", partner=partner, chat_messages=chat_messages, form=form)
