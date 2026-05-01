from datetime import datetime, timezone
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    user_type = db.Column(db.String(20), nullable=False, default="user")  # admin/user
    is_blacklisted = db.Column(db.Boolean, nullable=False, default=False)
    blacklist_reason = db.Column(db.String(300), nullable=True)
    reputation_score = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    # Profile
    bio = db.Column(db.Text, nullable=True)
    skills = db.Column(db.String(300), nullable=True)
    avatar_url = db.Column(db.String(300), nullable=True)

    # Relationships
    help_requests = db.relationship("HelpRequest", back_populates="user", lazy=True)
    help_offers = db.relationship(
        "HelpOffer", back_populates="helper", foreign_keys="HelpOffer.helper_id", lazy=True
    )

    reviews_written = db.relationship(
        "Review", back_populates="reviewer", foreign_keys="Review.reviewer_id", lazy=True
    )
    reviews_received = db.relationship(
        "Review", back_populates="reviewee", foreign_keys="Review.reviewee_id", lazy=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"

    # Password helpers
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class WalletLink(db.Model):
    __tablename__ = "wallet_links"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    address = db.Column(db.String(42), nullable=False, unique=True, index=True)
    challenge_nonce = db.Column(db.String(64), nullable=True)
    challenge_issued_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("wallet_link", uselist=False))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WalletLink user={self.user_id} address={self.address}>"


class HelpRequest(db.Model):
    __tablename__ = "help_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    time_needed = db.Column(db.String(120), nullable=True)
    price = db.Column(db.Float, nullable=True)
    is_volunteer = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(
        db.String(20), nullable=False, default="open"
    )  # open/in_progress/completed/cancelled/disputed
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship("User", back_populates="help_requests")
    offers = db.relationship("HelpOffer", back_populates="request", lazy=True)
    reviews = db.relationship("Review", back_populates="request", lazy=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HelpRequest {self.title} by {self.user_id}>"


class HelpOffer(db.Model):
    __tablename__ = "help_offers"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("help_requests.id"), nullable=False)
    helper_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/accepted/rejected
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    request = db.relationship("HelpRequest", back_populates="offers")
    helper = db.relationship("User", back_populates="help_offers")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HelpOffer {self.id} on request {self.request_id} by {self.helper_id}>"


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("help_requests.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    request = db.relationship("HelpRequest", back_populates="reviews")
    reviewer = db.relationship("User", foreign_keys=[reviewer_id], back_populates="reviews_written")
    reviewee = db.relationship("User", foreign_keys=[reviewee_id], back_populates="reviews_received")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Review {self.id} on request {self.request_id} {self.reviewer_id}->{self.reviewee_id}>"


class Flag(db.Model):
    __tablename__ = "flags"

    id = db.Column(db.Integer, primary_key=True)
    content_type = db.Column(db.String(50), nullable=False)  # request/review
    content_id = db.Column(db.Integer, nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reason = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/approved/rejected
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    reporter = db.relationship("User", foreign_keys=[reporter_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Flag {self.content_type}:{self.content_id} {self.status}>"


# -----------------------------
# Internal blockchain structures
# -----------------------------

class Block(db.Model):
    __tablename__ = "blocks"

    id = db.Column(db.Integer, primary_key=True)
    index = db.Column(db.Integer, nullable=False, unique=True)
    prev_hash = db.Column(db.String(128), nullable=True)
    hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    statements = db.relationship("Statement", back_populates="block", lazy=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Block idx={self.index} hash={self.hash[:10]}...>"


class Statement(db.Model):
    __tablename__ = "statements"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(50), nullable=False)  # e.g., signup, login, logout, request_create
    payload = db.Column(db.JSON, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Block linkage (null until included in a block)
    block_id = db.Column(db.Integer, db.ForeignKey("blocks.id"), nullable=True, index=True)
    block = db.relationship("Block", back_populates="statements")

    # User relationship
    user = db.relationship("User", backref="statements")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Statement {self.kind} id={self.id} block={self.block_id}>"


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="reset_tokens")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kind = db.Column(db.String(50), nullable=False)  # offer_received/offer_accepted/offer_rejected/task_completed/review_received
    message = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(200), nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="notifications")


class ChatbotMessage(db.Model):
    __tablename__ = "chatbot_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref="chatbot_messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatbotMessage {self.id} user={self.user_id} role={self.role}>"



class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("help_requests.id"), nullable=False, index=True)
    helper_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient_address = db.Column(db.String(42), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    tx_hash = db.Column(db.String(66), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="address_submitted")  # address_submitted / paid / refunded
    address_submitted_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    paid_at = db.Column(db.DateTime, nullable=True)

    help_request = db.relationship("HelpRequest", backref=db.backref("payment", uselist=False))
    helper = db.relationship("User", foreign_keys=[helper_id])
    requester = db.relationship("User", foreign_keys=[requester_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment req={self.request_id} status={self.status}>"


class Appeal(db.Model):
    __tablename__ = "appeals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/approved/rejected
    admin_reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="appeals")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Appeal {self.id} user={self.user_id} status={self.status}>"


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_messages")
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="received_messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message {self.id} {self.sender_id}->{self.receiver_id}>"
