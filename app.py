from datetime import datetime, timedelta
import hashlib
import json
from flask import Flask, render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import (
    AnonymousUserMixin,
    login_required,
    login_user,
    logout_user,
    current_user,
)
from extensions import db, login_manager, csrf
from web3_service import init_web3, get_web3, submit_anchor_transaction, get_signer_address
import logging
import secrets
from flask_scss import Scss
from blockchain_service import append_statement, maybe_seal_block
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


def create_app() -> Flask:
    """Application factory."""
    app = Flask(__name__, static_folder="static", template_folder="templates")
    # Optional: load .env if present
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass
    app.config.from_object("config.Config")
    # Logging setup
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(level)
    # SCSS configuration
    app.config.setdefault("SCSS_ASSET_DIR", "assets/scss")

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    # Initialize Web3 client (if ETH_RPC_URL set)
    app.extensions = getattr(app, "extensions", {})
    app.extensions["web3"] = init_web3(app.config.get("ETH_RPC_URL", ""))

    # Blockchain HTTP request logging
    @app.before_request
    def log_http_request():
        # Skip logging for static files and certain endpoints
        if (request.endpoint in ['static'] or
            request.path.startswith('/static/') or
            request.endpoint in ['web3_status', 'web3_balance'] or
            request.method in ['OPTIONS', 'HEAD']):
            return

        user_id = getattr(current_user, 'id', None) if current_user.is_authenticated else None

        try:
            append_statement(
                kind="http_request",
                payload={
                    "method": request.method,
                    "path": request.path,
                    "query_string": request.query_string.decode('utf-8') if request.query_string else "",
                    "user_agent": request.headers.get('User-Agent', '')[:200],  # Limit length
                    "remote_addr": request.remote_addr,
                    "referrer": request.headers.get('Referer', '')[:200],  # Limit length
                },
                user_id=user_id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            # Silently fail to not break the request flow
            pass

    # Flask-Login config
    class _AnonymousUser(AnonymousUserMixin):
        pass

    login_manager.anonymous_user = _AnonymousUser
    login_manager.login_view = "login"
    login_manager.login_message = "请先登录后再访问该页面。"
    login_manager.login_message_category = "info"

    # ------------------
    # Admin utilities
    # ------------------
    from functools import wraps

    def admin_required(view_func):
        @wraps(view_func)
        def _wrapped(*args, **kwargs):
            if not current_user.is_authenticated or getattr(current_user, "user_type", "user") != "admin":
                flash("需要管理员权限。", "error")
                return redirect(url_for("dashboard"))
            return view_func(*args, **kwargs)
        return _wrapped

    @login_manager.user_loader
    def load_user(user_id):  # noqa: ANN001
        # Lazy import to avoid circular imports
        from models import User
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # Auto-create tables on first run
    with app.app_context():
        # Import models so SQLAlchemy is aware before create_all
        import models  # noqa: F401
        db.create_all()

    # Basic index route
    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.route("/about")
    def about():
        return render_template("about.html")

    # Web3 routes
    @app.route("/web3", methods=["GET", "POST"])
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
            if app.config.get("ETH_SIGNER_PRIVATE_KEY") and not signer_address:
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
                            payload={
                                "tx_hash": anchor_result.get("tx_hash"),
                                "chain_id": anchor_result.get("chain_id"),
                                "tx_status": anchor_result.get("status"),
                                "tx_url": anchor_result.get("tx_url"),
                                "payload_size": len(anchor_text),
                            },
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
                    net_info = {
                        "client": w3.client_version,
                    }
                    latest_block = w3.eth.block_number
                    chain_id = int(w3.eth.chain_id)
            except Exception as e:  # noqa: BLE001
                error = str(e)
        return render_template(
            "web3/status.html",
            ok=ok,
            net_info=net_info,
            latest_block=latest_block,
            chain_id=chain_id,
            signer_address=signer_address,
            signer_error=signer_error,
            anchor_result=anchor_result,
            rpc_url=("configured" if app.config.get("ETH_RPC_URL") else "not set"),
            error=error,
        )

    @app.route("/web3/balance")
    def web3_balance():
        from flask import request as flask_request
        w3 = get_web3()
        addr = flask_request.args.get("address", "").strip()
        balance_eth = None
        error = None
        if w3 and addr:
            try:
                balance_wei = w3.eth.get_balance(addr)
                balance_eth = w3.from_wei(balance_wei, "ether")
            except Exception as e:
                error = str(e)
        return jsonify({"address": addr, "balance_eth": str(balance_eth) if balance_eth is not None else None, "error": error})
    @app.route("/connect-wallet")
    @login_required
    def connect_wallet():
        from models import WalletLink

        wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
        return render_template("wallet/connect.html", wallet_link=wallet_link)

    @app.route("/wallet/me")
    @login_required
    def wallet_me():
        from models import WalletLink

        wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
        return jsonify(
            {
                "address": wallet_link.address if wallet_link and wallet_link.verified_at else None,
                "verified": bool(wallet_link and wallet_link.verified_at),
                "verified_at": wallet_link.verified_at.isoformat() if wallet_link and wallet_link.verified_at else None,
            }
        )

    @app.route("/wallet/challenge", methods=["POST"])
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
        issued_at = datetime.utcnow()
        message = (
            "DailyHelper Wallet Verification\n\n"
            f"User ID: {current_user.id}\n"
            f"Address: {address}\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {issued_at.isoformat()}Z\n"
            f"Domain: {request.host}"
        )

        wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
        if wallet_link is None:
            wallet_link = WalletLink(user_id=current_user.id, address=address)
            db.session.add(wallet_link)
        wallet_link.address = address
        wallet_link.challenge_nonce = nonce
        wallet_link.challenge_issued_at = issued_at
        wallet_link.verified_at = None
        db.session.commit()

        return jsonify({"ok": True, "address": address, "message": message, "nonce": nonce})

    @app.route("/wallet/verify", methods=["POST"])
    @csrf.exempt
    @login_required
    def wallet_verify():
        from models import WalletLink

        payload = request.get_json(silent=True) or {}
        raw_address = str(payload.get("address", "")).strip()
        signature = str(payload.get("signature", "")).strip()
        chain_id = payload.get("chain_id")

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
        if datetime.utcnow() - wallet_link.challenge_issued_at > timedelta(minutes=10):
            wallet_link.challenge_nonce = None
            wallet_link.challenge_issued_at = None
            db.session.commit()
            return jsonify({"ok": False, "error": "Challenge expired. Please reconnect wallet."}), 400

        challenge_message = (
            "DailyHelper Wallet Verification\n\n"
            f"User ID: {current_user.id}\n"
            f"Address: {wallet_link.address}\n"
            f"Nonce: {wallet_link.challenge_nonce}\n"
            f"Issued At: {wallet_link.challenge_issued_at.isoformat()}Z\n"
            f"Domain: {request.host}"
        )

        try:
            recovered = Account.recover_message(
                encode_defunct(text=challenge_message),
                signature=signature,
            )
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"Invalid signature: {e}"}), 400

        if Web3.to_checksum_address(recovered) != wallet_link.address:
            return jsonify({"ok": False, "error": "Signature does not match the wallet address."}), 400

        wallet_link.verified_at = datetime.utcnow()
        wallet_link.challenge_nonce = None
        wallet_link.challenge_issued_at = None
        db.session.commit()

        try:
            append_statement(
                kind="wallet_linked",
                payload={
                    "address": wallet_link.address,
                    "chain_id": chain_id,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        return jsonify(
            {
                "ok": True,
                "address": wallet_link.address,
                "verified_at": wallet_link.verified_at.isoformat() if wallet_link.verified_at else None,
            }
        )

    @app.route("/wallet/disconnect", methods=["POST"])
    @csrf.exempt
    @login_required
    def wallet_disconnect():
        from models import WalletLink

        wallet_link = WalletLink.query.filter_by(user_id=current_user.id).one_or_none()
        if wallet_link is None:
            return jsonify({"ok": True, "address": None})

        removed_address = wallet_link.address
        db.session.delete(wallet_link)
        db.session.commit()

        try:
            append_statement(
                kind="wallet_unlinked",
                payload={"address": removed_address},
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        return jsonify({"ok": True, "address": None})

    @app.route("/blockchain/blocks")
    @login_required
    def blockchain_blocks():
        from models import Block, Statement

        # Get pagination parameters
        page = int(request.args.get("page", 1) or 1)
        per_page = 10

        # Query blocks with statements count
        blocks_query = db.session.query(
            Block,
            db.func.count(Statement.id).label('statement_count')
        ).outerjoin(Statement, Block.id == Statement.block_id)\
         .group_by(Block.id)\
         .order_by(Block.index.desc())

        pagination = blocks_query.paginate(page=page, per_page=per_page, error_out=False)
        blocks_with_counts = pagination.items

        # Get total blocks count
        total_blocks = db.session.query(Block).count()

        return render_template(
            "blockchain/blocks.html",
            blocks_with_counts=blocks_with_counts,
            pagination=pagination,
            total_blocks=total_blocks,
        )
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        from models import User
        from forms import SignUpForm

        form = SignUpForm()
        if form.validate_on_submit():
            # Check existing user by email/username
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
            # Blockchain log: signup
            try:
                append_statement(
                    kind="signup",
                    payload={
                        "username": user.username,
                        "email": user.email,
                    },
                    user_id=user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass
            flash("账号创建成功，请登录。", "success")
            return redirect(url_for("login"))

        # If POST with errors, surface them
        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")
        return render_template("auth/signup.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("post_login_redirect"))

        from models import User
        from forms import LoginForm

        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data.lower()).first()
            if user and user.check_password(form.password.data):
                login_user(user, remember=form.remember_me.data)
                # Blockchain log: login
                try:
                    append_statement(
                        kind="login",
                        payload={"remember": bool(form.remember_me.data)},
                        user_id=user.id,
                    )
                    maybe_seal_block()
                except Exception:  # noqa: BLE001
                    pass
                flash("登录成功。", "success")
                return redirect(url_for("post_login_redirect"))
            flash("邮箱或密码错误。", "error")
        # If POST with errors, surface them
        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")
        return render_template("auth/login.html", form=form)

    @app.route("/logout")
    @login_required
    def logout():
        uid = getattr(current_user, "id", None)
        logout_user()
        # Blockchain log: logout
        try:
            append_statement(
                kind="logout",
                payload={},
                user_id=uid,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass
        flash("您已退出登录。", "info")
        return redirect(url_for("login"))

    # ------------------
    # Password reset
    # ------------------
    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        from models import User, PasswordResetToken
        from forms import ForgotPasswordForm
        import secrets

        form = ForgotPasswordForm()
        reset_link = None
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data.lower()).first()
            if user:
                # Invalidate old unused tokens
                PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({"used": True})
                token = secrets.token_urlsafe(32)
                prt = PasswordResetToken(user_id=user.id, token=token)
                db.session.add(prt)
                db.session.commit()
                reset_link = url_for("reset_password", token=token, _external=True)
            else:
                # Don't reveal whether email exists
                flash("如果该邮箱已注册，重置链接已生成。", "info")
                return redirect(url_for("forgot_password"))
        return render_template("auth/forgot_password.html", form=form, reset_link=reset_link)

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token: str):
        from models import PasswordResetToken
        from forms import ResetPasswordForm
        from datetime import timedelta

        prt = PasswordResetToken.query.filter_by(token=token, used=False).first()
        if prt is None:
            flash("重置链接无效或已过期。", "error")
            return redirect(url_for("forgot_password"))
        # Expire after 1 hour
        if (datetime.utcnow() - prt.created_at).total_seconds() > 3600:
            flash("重置链接已过期，请重新申请。", "error")
            return redirect(url_for("forgot_password"))

        form = ResetPasswordForm()
        if form.validate_on_submit():
            prt.user.set_password(form.password.data)
            prt.used = True
            db.session.commit()
            flash("密码已重置，请登录。", "success")
            return redirect(url_for("login"))
        return render_template("auth/reset_password.html", form=form, token=token)

    # ------------------
    # Notifications
    # ------------------
    def _notify(user_id: int, kind: str, message: str, link: str = None):
        """Create a notification for a user."""
        from models import Notification
        n = Notification(user_id=user_id, kind=kind, message=message, link=link)
        db.session.add(n)
        # Don't commit here — caller commits

    @app.route("/notifications")
    @login_required
    def notifications():
        from models import Notification
        items = (
            Notification.query.filter_by(user_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )
        # Mark all as read
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
        db.session.commit()
        return render_template("notifications.html", items=items)

    @app.context_processor
    def inject_unread_count():
        if current_user.is_authenticated:
            from models import Notification, Message
            notif_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            msg_count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
            return {"unread_notifications": notif_count, "unread_messages": msg_count}
        return {"unread_notifications": 0, "unread_messages": 0}

    @app.route("/dashboard")
    @login_required
    def dashboard():
        from models import HelpRequest, HelpOffer, Statement

        # Stats for the current user
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

        # Recent activity: last 5 combined items from requests/offers
        recent_requests = (
            HelpRequest.query.filter_by(user_id=current_user.id)
            .order_by(HelpRequest.created_at.desc())
            .limit(5)
            .all()
        )
        recent_offers = (
            HelpOffer.query.filter_by(helper_id=current_user.id)
            .order_by(HelpOffer.created_at.desc())
            .limit(5)
            .all()
        )
        my_requests = (
            HelpRequest.query.filter_by(user_id=current_user.id)
            .order_by(HelpRequest.created_at.desc())
            .limit(20)
            .all()
        )
        my_offers = (
            HelpOffer.query.filter_by(helper_id=current_user.id)
            .order_by(HelpOffer.created_at.desc())
            .limit(20)
            .all()
        )
        latest_reputation_anchor = (
            Statement.query.filter_by(user_id=current_user.id, kind="reputation_snapshot_anchored")
            .order_by(Statement.created_at.desc())
            .first()
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
            recent={
                "requests": recent_requests,
                "offers": recent_offers,
            },
            my_requests=my_requests,
            my_offers=my_offers,
            latest_reputation_anchor=latest_reputation_anchor,
        )

    

    @app.route("/post-login-redirect")
    @login_required
    def post_login_redirect():
        # Check for specific admin credentials
        if (getattr(current_user, "username", "") == "admin" and
            getattr(current_user, "email", "") == "admin@dailyhelper.com"):
            return redirect(url_for("blockchain_blocks"))
        return redirect(url_for("dashboard"))

    # ------------------
    # Cancel request
    # ------------------
    @app.route("/requests/<int:request_id>/cancel", methods=["POST"])
    @login_required
    def cancel_request(request_id: int):
        from models import HelpRequest, HelpOffer
        from forms import CancelRequestForm

        form = CancelRequestForm()
        req = HelpRequest.query.get_or_404(request_id)

        # Only the requester can cancel
        if req.user_id != current_user.id:
            flash("您无权取消该求助。", "error")
            return redirect(url_for("request_detail", request_id=req.id))

        # Can only cancel open or in_progress requests
        if req.status not in ("open", "in_progress"):
            flash("该求助当前状态无法取消。", "error")
            return redirect(url_for("request_detail", request_id=req.id))

        if form.validate_on_submit():
            old_status = req.status
            req.status = "cancelled"
            # Reject all pending offers
            HelpOffer.query.filter_by(request_id=req.id, status="pending").update({"status": "rejected"})
            # If in_progress, also reject accepted offers
            if old_status == "in_progress":
                accepted_offers = HelpOffer.query.filter_by(request_id=req.id, status="accepted").all()
                for offer in accepted_offers:
                    offer.status = "rejected"
                    _notify(
                        offer.helper_id,
                        "request_cancelled",
                        f"求助「{req.title[:40]}」已被求助者取消。",
                        url_for("request_detail", request_id=req.id),
                    )
            db.session.commit()

            # Blockchain log
            try:
                append_statement(
                    kind="request_cancelled",
                    payload={
                        "request_id": req.id,
                        "previous_status": old_status,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass

            flash("求助已取消。", "success")
        return redirect(url_for("request_help"))

    # ------------------
    # Edit request
    # ------------------
    @app.route("/requests/<int:request_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_request(request_id: int):
        from models import HelpRequest
        from forms import EditRequestForm

        req = HelpRequest.query.get_or_404(request_id)

        # Only the requester can edit
        if req.user_id != current_user.id:
            flash("您无权编辑该求助。", "error")
            return redirect(url_for("request_detail", request_id=req.id))

        # Can only edit open requests
        if req.status != "open":
            flash("只有状态为「开放」的求助可以编辑。", "error")
            return redirect(url_for("request_detail", request_id=req.id))

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
            req.time_needed = (
                form.datetime_needed.data.strftime("%Y-%m-%d %H:%M")
                if form.datetime_needed.data
                else form.duration_estimate.data or None
            )
            req.price = (
                float(form.price_offered.data)
                if (form.price_offered.data and not form.is_volunteer.data)
                else None
            )
            req.is_volunteer = bool(form.is_volunteer.data)
            db.session.commit()

            # Blockchain log
            try:
                append_statement(
                    kind="request_edited",
                    payload={
                        "request_id": req.id,
                        "title": req.title,
                        "category": req.category,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass

            flash("求助已更新。", "success")
            return redirect(url_for("request_detail", request_id=req.id))

        # If POST with errors, flash them
        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        return render_template("features/edit_request.html", form=form, req=req)

    # ------------------
    # Change password
    # ------------------
    @app.route("/settings/password", methods=["GET", "POST"])
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

            # Blockchain log
            try:
                append_statement(
                    kind="password_changed",
                    payload={},
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass

            flash("密码修改成功。", "success")
            return redirect(url_for("profile_view", username=current_user.username))

        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        return render_template("auth/change_password.html", form=form)

    # ------------------
    # Flag / Report
    # ------------------
    @app.route("/flag/<string:content_type>/<int:content_id>", methods=["GET", "POST"])
    @login_required
    def flag_content(content_type: str, content_id: int):
        from models import Flag, HelpRequest, User
        from forms import FlagForm

        # Validate content_type
        if content_type not in ("request", "user", "review"):
            abort(400)

        # Verify the content exists
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

        # Check if already flagged by this user
        existing = Flag.query.filter_by(
            content_type=content_type,
            content_id=content_id,
        ).filter(Flag.status == "pending").first()

        form = FlagForm()
        if form.validate_on_submit():
            if existing:
                flash("该内容已被举报，正在等待审核。", "info")
                return redirect(request.referrer or url_for("index"))

            reason_text = form.reason.data
            if form.detail.data:
                reason_text += f" — {form.detail.data}"

            flag = Flag(
                content_type=content_type,
                content_id=content_id,
                reason=reason_text,
                status="pending",
            )
            db.session.add(flag)
            db.session.commit()

            # Blockchain log
            try:
                append_statement(
                    kind="content_flagged",
                    payload={
                        "content_type": content_type,
                        "content_id": content_id,
                        "reason": form.reason.data,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass

            flash("举报已提交，管理员将进行审核。", "success")
            return redirect(request.referrer or url_for("index"))

        return render_template(
            "flag.html",
            form=form,
            content_type=content_type,
            content_id=content_id,
            content_label=content_label,
        )

    # Feature pages (placeholders)
    @app.route("/request-help", methods=["GET", "POST"])
    @login_required
    def request_help():
        from models import HelpRequest
        from forms import RequestHelpForm

        if getattr(current_user, "is_blacklisted", False):
            flash("您的账号已被列入黑名单，无法发布求助。", "error")
            return redirect(url_for("dashboard"))

        form = RequestHelpForm()
        if form.validate_on_submit():
            desc = form.description.data
            # Append skills and notes for now to description to avoid schema changes
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

            # Blockchain log: request creation
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
            return redirect(url_for("request_help"))

        # If POST with errors, flash them
        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        # List user's existing requests
        my_requests = (
            HelpRequest.query.filter_by(user_id=current_user.id)
            .order_by(HelpRequest.created_at.desc())
            .all()
        )
        return render_template("features/request_help.html", form=form, my_requests=my_requests)

    @app.route("/offer-help")
    @login_required
    def offer_help():
        from models import HelpRequest, HelpOffer
        from sqlalchemy import func

        # 获取当前用户已提交 offer 的 request_id 集合
        my_offer_ids = set(
            r[0] for r in db.session.query(HelpOffer.request_id).filter_by(helper_id=current_user.id).all()
        )

        # 可帮助的请求：开放状态、非自己发布的
        q = HelpRequest.query.filter(
            HelpRequest.status == "open",
            HelpRequest.user_id != current_user.id,
        ).order_by(HelpRequest.created_at.desc())

        page = int(request.args.get("page", 1) or 1)
        per_page = 12
        pagination = q.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items

        # 我的帮助记录
        my_active_offers = (
            HelpOffer.query.filter_by(helper_id=current_user.id)
            .filter(HelpOffer.status.in_(["pending", "accepted"]))
            .order_by(HelpOffer.created_at.desc())
            .limit(10)
            .all()
        )

        return render_template(
            "features/offer_help.html",
            items=items,
            pagination=pagination,
            my_offer_ids=my_offer_ids,
            my_active_offers=my_active_offers,
        )

    @app.route("/volunteer")
    def volunteer():
        from models import HelpRequest, HelpOffer
        from sqlalchemy import func
        from datetime import datetime, timedelta

        # Base query: volunteer-only open requests
        q = HelpRequest.query.filter(
            HelpRequest.is_volunteer.is_(True), HelpRequest.status == "open"
        )

        # Filters
        category = request.args.get("category", "").strip()
        location_q = request.args.get("location", "").strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()
        sort = request.args.get("sort", "newest")
        page = int(request.args.get("page", 1) or 1)
        per_page = 9

        if category:
            q = q.filter(HelpRequest.category == category)
        if location_q:
            q = q.filter(HelpRequest.location.ilike(f"%{location_q}%"))

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

        # Featured urgent: oldest open volunteer requests (top 3)
        featured = (
            HelpRequest.query.filter(HelpRequest.is_volunteer.is_(True), HelpRequest.status == "open")
            .order_by(HelpRequest.created_at.asc())
            .limit(3)
            .all()
        )

        # Sorting
        if sort == "newest":
            q = q.order_by(HelpRequest.created_at.desc())
        else:
            q = q.order_by(HelpRequest.created_at.asc())

        pagination = q.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items

        # Community impact stats (estimates)
        completed_volunteer = (
            HelpRequest.query.filter(HelpRequest.is_volunteer.is_(True), HelpRequest.status == "completed").count()
        )
        # Active volunteers = distinct helpers on accepted/completed offers for volunteer requests
        active_volunteers = (
            db.session.query(func.count(func.distinct(HelpOffer.helper_id)))
            .join(HelpRequest, HelpOffer.request_id == HelpRequest.id)
            .filter(
                HelpRequest.is_volunteer.is_(True),
                HelpOffer.status.in_(["accepted", "completed"]),
            )
            .scalar()
            or 0
        )
        people_helped = completed_volunteer
        est_hours = completed_volunteer * 2  # simple placeholder estimate

        volunteer_categories = [
            "老年关怀",
            "社区清洁",
            "教学辅导",
            "食物分发",
            "动物福利",
            "医疗支持",
            "其他",
        ]

        return render_template(
            "features/volunteer.html",
            items=items,
            featured=featured,
            pagination=pagination,
            stats={
                "est_hours": est_hours,
                "people_helped": people_helped,
                "active_volunteers": active_volunteers,
            },
            filters={
                "category": category,
                "location": location_q,
                "start_date": start_date,
                "end_date": end_date,
                "sort": sort,
            },
            categories=volunteer_categories,
        )

    @app.route("/ngos")
    def ngos():
        from models import NGO

        q = NGO.query
        category = request.args.get("category", "").strip()
        location_q = request.args.get("location", "").strip()
        sort = request.args.get("sort", "newest")
        page = int(request.args.get("page", 1) or 1)
        per_page = 9

        if category:
            q = q.filter(NGO.category == category)
        if location_q:
            q = q.filter(NGO.location.ilike(f"%{location_q}%"))

        if sort == "newest":
            q = q.order_by(NGO.created_at.desc())
        else:
            q = q.order_by(NGO.name.asc())

        pagination = q.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items

        categories = [
            "教育",
            "医疗健康",
            "环境保护",
            "扶贫",
            "动物福利",
            "妇女儿童",
            "灾害救援",
            "其他",
        ]

        return render_template(
            "features/ngos.html",
            items=items,
            pagination=pagination,
            categories=categories,
            filters={
                "category": category,
                "location": location_q,
                "sort": sort,
            },
        )

    @app.route("/ngos/<int:ngo_id>")
    def ngo_detail(ngo_id: int):
        from models import NGO
        ngo = NGO.query.get_or_404(ngo_id)
        # Placeholder campaigns/needs
        campaigns = [
            {"title": "每月食物捐赠", "need": "需要分发志愿者"},
            {"title": "学习用品捐赠", "need": "需要笔记本和笔的捐赠"},
        ]
        return render_template("features/ngo_detail.html", ngo=ngo, campaigns=campaigns)

    @app.route("/ngos/submit", methods=["GET", "POST"])
    @login_required
    def ngo_submit():
        from models import NGO
        from forms import NGOForm

        form = NGOForm()
        if form.validate_on_submit():
            ngo = NGO(
                name=form.name.data,
                description=form.description.data,
                category=form.category.data or None,
                location=form.location.data or None,
                contact_email=form.contact_email.data or None,
                website=form.website.data or None,
                verified_status=False,
            )
            db.session.add(ngo)
            db.session.commit()

            # Blockchain log: NGO submission
            try:
                append_statement(
                    kind="ngo_submit",
                    payload={
                        "ngo_id": ngo.id,
                        "name": ngo.name,
                        "category": ngo.category,
                        "location": ngo.location,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass

            flash("公益组织已提交审核，我们的团队将进行验证并发布。", "success")
            return redirect(url_for("ngos"))

        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        return render_template("features/ngo_submit.html", form=form)

    @app.route("/nearby")
    @login_required
    def nearby():
        from models import User
        import math

        # Require current user location
        if current_user.latitude is None or current_user.longitude is None:
            flash("请在个人资料中设置您的位置（经纬度）以查看附近的人。", "info")
            return redirect(url_for("profile_edit"))

        # Filters
        try:
            radius_km = float(request.args.get("radius", 5))
        except Exception:
            radius_km = 5.0
        skill_q = (request.args.get("skills", "").strip() or None)
        try:
            rep_min = float(request.args.get("rep_min", 0))
        except Exception:
            rep_min = 0.0

        candidates = (
            User.query.filter(
                User.id != current_user.id,
                User.latitude.isnot(None),
                User.longitude.isnot(None),
                User.is_blacklisted.is_(False),
                (User.reputation_score >= rep_min),
            ).all()
        )

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371.0
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi/2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2) ** 2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        results = []
        for u in candidates:
            dist = haversine(current_user.latitude, current_user.longitude, float(u.latitude), float(u.longitude))
            if dist <= radius_km:
                if skill_q:
                    if not (u.skills and skill_q.lower() in u.skills.lower()):
                        continue
                results.append({
                    "user": u,
                    "distance": round(dist, 2),
                })
        results.sort(key=lambda x: (x["distance"], -(x["user"].reputation_score or 0)))

        filters = {
            "radius": radius_km,
            "skills": skill_q or "",
            "rep_min": rep_min,
        }

        return render_template("features/nearby.html", results=results, filters=filters)

    # Static pages
    @app.route("/help")
    def help_page():
        return render_template("help.html")

    @app.route("/terms")
    def terms_page():
        return render_template("terms.html")

    @app.route("/privacy")
    def privacy_page():
        return render_template("privacy.html")

    @app.route("/marketplace")
    def marketplace():
        from models import HelpRequest, User
        from sqlalchemy import or_, and_

        q = HelpRequest.query.filter(HelpRequest.status == "open")

        # Filters
        category = request.args.get("category", "").strip()
        location_q = request.args.get("location", "").strip()
        min_price = request.args.get("min_price", "").strip()
        max_price = request.args.get("max_price", "").strip()
        include_volunteer = request.args.get("include_volunteer", "on")  # default include
        start_date = request.args.get("start_date", "").strip()  # YYYY-MM-DD
        end_date = request.args.get("end_date", "").strip()      # YYYY-MM-DD
        sort = request.args.get("sort", "newest")
        page = int(request.args.get("page", 1) or 1)
        per_page = 9

        if category:
            q = q.filter(HelpRequest.category == category)
        if location_q:
            q = q.filter(HelpRequest.location.ilike(f"%{location_q}%"))

        # Price / volunteer
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

        # Date range (use created_at since time_needed is free text)
        from datetime import datetime
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
            from datetime import timedelta
            q = q.filter(HelpRequest.created_at < ed + timedelta(days=1))

        # Sorting
        if sort == "price_high_low":
            q = q.order_by(HelpRequest.price.desc().nullslast(), HelpRequest.created_at.desc())
        elif sort == "price_low_high":
            q = q.order_by(HelpRequest.price.asc().nullsfirst(), HelpRequest.created_at.desc())
        elif sort == "urgent":
            q = q.order_by(HelpRequest.created_at.asc())
        else:  # newest
            q = q.order_by(HelpRequest.created_at.desc())

        pagination = q.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items

        categories = ["烹饪", "清洁", "搬运", "辅导", "跑腿", "技术支持", "其他"]

        return render_template(
            "features/marketplace.html",
            items=items,
            pagination=pagination,
            categories=categories,
            filters={
                "category": category,
                "location": location_q,
                "min_price": min_price,
                "max_price": max_price,
                "include_volunteer": include_volunteer,
                "start_date": start_date,
                "end_date": end_date,
                "sort": sort,
            },
        )

    @app.route("/requests/<int:request_id>", methods=["GET", "POST"])
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

        # Get all offers for this request
        all_offers = HelpOffer.query.filter_by(request_id=request_id).order_by(HelpOffer.created_at.desc()).all()

        # Check if current user is the requester
        is_requester = current_user.id == req.user_id

        # Handle offer submit
        if getattr(current_user, "is_blacklisted", False) and offer_form.submit.data:
            flash("您的账号已被列入黑名单，无法提供帮助。", "error")
            return redirect(url_for("request_detail", request_id=req.id))
        if offer_form.submit.data and offer_form.validate_on_submit():
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

            # Blockchain log: offer submission
            try:
                append_statement(
                    kind="offer_submit",
                    payload={
                        "request_id": req.id,
                        "offer_id": offer.id,
                        "message_length": len(offer.message or ""),
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass

            flash("帮助提议已发送给求助者。", "success")
            # Notify requester
            _notify(
                req.user_id,
                "offer_received",
                f"{current_user.username} 对您的求助「{req.title[:40]}」提交了帮助提议",
                url_for("request_detail", request_id=req.id),
            )
            db.session.commit()
            return redirect(url_for("request_detail", request_id=req.id))

        # Handle offer acceptance (only by requester)
        if is_requester and accept_form.submit.data:
            offer_id = request.form.get('offer_id')
            if offer_id:
                offer = HelpOffer.query.get_or_404(offer_id)
                if offer.request_id == req.id and offer.status == "pending":
                    # Reject all other offers
                    HelpOffer.query.filter_by(request_id=req.id, status="pending").update({"status": "rejected"})

                    # Accept the selected offer
                    offer.status = "accepted"
                    req.status = "in_progress"
                    db.session.commit()

                    # Blockchain log: offer acceptance
                    try:
                        append_statement(
                            kind="offer_accepted",
                            payload={
                                "request_id": req.id,
                                "offer_id": offer.id,
                                "helper_id": offer.helper_id,
                                "requester_id": current_user.id,
                            },
                            user_id=current_user.id,
                        )
                        maybe_seal_block()
                    except Exception:  # noqa: BLE001
                        pass

                    flash(f"已接受来自 {offer.helper.full_name or offer.helper.username} 的帮助！", "success")
                    # Notify accepted helper
                    _notify(
                        offer.helper_id,
                        "offer_accepted",
                        f"您对「{req.title[:40]}」的帮助提议已被接受！",
                        url_for("request_detail", request_id=req.id),
                    )
                    # Notify rejected helpers
                    rejected = HelpOffer.query.filter_by(request_id=req.id, status="rejected").filter(HelpOffer.helper_id != offer.helper_id).all()
                    for ro in rejected:
                        _notify(
                            ro.helper_id,
                            "offer_rejected",
                            f"您对「{req.title[:40]}」的帮助提议未被选中",
                            url_for("request_detail", request_id=req.id),
                        )
                    db.session.commit()
                    return redirect(url_for("request_detail", request_id=req.id))

        # Handle task completion (only by requester)
        if is_requester and complete_form.submit.data and req.status == "in_progress":
            accepted_offer = HelpOffer.query.filter_by(request_id=req.id, status="accepted").first()
            if accepted_offer:
                req.status = "completed"
                accepted_offer.status = "completed"
                db.session.commit()

                # Blockchain log: task completion
                onchain_result = None
                onchain_error = None
                anchor_payload = json.dumps(
                    {
                        "source": "task_completed",
                        "request_id": req.id,
                        "requester_id": current_user.id,
                        "helper_id": accepted_offer.helper_id,
                        "completed_at": datetime.utcnow().isoformat() + "Z",
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
                # Notify helper
                _notify(
                    accepted_offer.helper_id,
                    "task_completed",
                    f"求助者已将「{req.title[:40]}」标记为完成，请互相评价！",
                    url_for("request_detail", request_id=req.id),
                )
                db.session.commit()
                return redirect(url_for("request_detail", request_id=req.id))

        # Handle review submit (only for completed tasks and participants)
        if review_form.submit.data and review_form.validate_on_submit():
            # Only allow reviews when a completed offer exists for this request
            completed = (
                HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
            )
            if not completed or req.status != "completed":
                flash("仅已完成的任务可以评价。", "error")
                return redirect(url_for("request_detail", request_id=req.id))

            # Determine counterpart
            if current_user.id == req.user_id:
                reviewee_id = completed.helper_id
            elif current_user.id == completed.helper_id:
                reviewee_id = req.user_id
            else:
                flash("您不是该任务的参与者。", "error")
                return redirect(url_for("request_detail", request_id=req.id))

            # Prevent duplicate per task per reviewer
            exists = (
                Review.query.filter_by(request_id=req.id, reviewer_id=current_user.id).first()
            )
            if exists:
                flash("您已经评价过该任务。", "error")
                return redirect(url_for("request_detail", request_id=req.id))

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

            # Simple reputation update for the reviewee
            reviewee = User.query.get(reviewee_id)
            delta = 0
            if reviewee is not None:
                delta = rating * 3
                if rating == 5:
                    delta += 2
                if rating <= 2:
                    delta -= 5
                new_score = max(0.0, min(100.0, float(reviewee.reputation_score or 0.0) + delta))
                reviewee.reputation_score = new_score

            # Blockchain log: review submission
            try:
                append_statement(
                    kind="review_submit",
                    payload={
                        "request_id": req.id,
                        "review_id": rv.id,
                        "rating": rating,
                        "reviewee_id": reviewee_id,
                        "reputation_change": delta,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass

            db.session.commit()
            flash("评价已提交。", "success")
            # Notify reviewee
            stars = "★" * rating + "☆" * (5 - rating)
            _notify(
                reviewee_id,
                "review_received",
                f"{current_user.username} 给您留下了评价 {stars}（任务：{req.title[:30]}）",
                url_for("request_detail", request_id=req.id),
            )
            db.session.commit()
            return redirect(url_for("request_detail", request_id=req.id))

        if request.method == "POST" and (offer_form.errors or review_form.errors or accept_form.errors or complete_form.errors):
            for field, errs in offer_form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")
            for field, errs in review_form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")
            for field, errs in accept_form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")
            for field, errs in complete_form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        # Existing offers by current user for this request
        my_offer = None
        if current_user.is_authenticated:
            my_offer = (
                HelpOffer.query.filter_by(request_id=req.id, helper_id=current_user.id)
                .order_by(HelpOffer.created_at.desc())
                .first()
            )

        # Reviews for this request
        request_reviews = Review.query.filter_by(request_id=req.id).order_by(Review.created_at.desc()).all()

        # Eligibility to review
        can_review = False
        if req.status == "completed":
            completed_offer = HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
            if completed_offer and (
                current_user.id in (req.user_id, completed_offer.helper_id)
            ):
                already = (
                    db.session.query(Review.id)
                    .filter_by(request_id=req.id, reviewer_id=current_user.id)
                    .first()
                )
                can_review = already is None

        # Payment info for completed paid tasks
        helper_wallet_address = None
        requester_wallet_linked = False
        payment_needed = False
        if req.status == "completed" and req.price and not req.is_volunteer:
            completed_offer = HelpOffer.query.filter_by(request_id=req.id, status="completed").first()
            if completed_offer:
                from models import WalletLink
                helper_wl = WalletLink.query.filter_by(user_id=completed_offer.helper_id).one_or_none()
                if helper_wl and helper_wl.verified_at:
                    helper_wallet_address = helper_wl.address
                requester_wl = WalletLink.query.filter_by(user_id=req.user_id).one_or_none()
                requester_wallet_linked = bool(requester_wl and requester_wl.verified_at)
                payment_needed = is_requester

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
            helper_wallet_address=helper_wallet_address,
            requester_wallet_linked=requester_wallet_linked,
            payment_needed=payment_needed,
        )

    @app.route("/api/record-payment", methods=["POST"])
    @csrf.exempt
    @login_required
    def record_payment():
        from models import HelpRequest, HelpOffer
        payload = request.get_json(silent=True) or {}
        request_id = payload.get("request_id")
        tx_hash = payload.get("tx_hash", "").strip()
        if not request_id or not tx_hash:
            return jsonify({"ok": False, "error": "Missing request_id or tx_hash"}), 400

        req_obj = HelpRequest.query.get(request_id)
        if not req_obj or req_obj.user_id != current_user.id:
            return jsonify({"ok": False, "error": "Unauthorized"}), 403
        if req_obj.status != "completed":
            return jsonify({"ok": False, "error": "Task not completed"}), 400

        completed_offer = HelpOffer.query.filter_by(request_id=req_obj.id, status="completed").first()
        if not completed_offer:
            return jsonify({"ok": False, "error": "No completed offer found"}), 400

        try:
            append_statement(
                kind="payment_sent",
                payload={
                    "request_id": req_obj.id,
                    "helper_id": completed_offer.helper_id,
                    "requester_id": current_user.id,
                    "tx_hash": tx_hash,
                    "amount": req_obj.price,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:
            pass

        db.session.commit()
        return jsonify({"ok": True, "tx_hash": tx_hash})

    @app.route("/my-offers")
    @login_required
    def my_offers():
        from models import HelpOffer, HelpRequest

        offers = (
            HelpOffer.query.filter_by(helper_id=current_user.id)
            .order_by(HelpOffer.created_at.desc())
            .all()
        )
        grouped = {
            "pending": [o for o in offers if o.status == "pending"],
            "accepted": [o for o in offers if o.status == "accepted"],
            "rejected": [o for o in offers if o.status == "rejected"],
            "completed": [o for o in offers if o.status == "completed"],
        }
        badge_counts = {k: len(v) for k, v in grouped.items()}
        return render_template("features/my_offers.html", grouped=grouped, badge_counts=badge_counts)

    # ------------------
    # Admin: dashboard & users
    # ------------------
    @app.route("/admin")
    @login_required
    @admin_required
    def admin():
        from models import User, HelpRequest, Flag, NGO, Statement
        total_users = db.session.query(User).count()
        total_requests = db.session.query(HelpRequest).count()
        open_requests = db.session.query(HelpRequest).filter_by(status="open").count()
        completed_requests = db.session.query(HelpRequest).filter_by(status="completed").count()
        flagged_pending = db.session.query(Flag).filter_by(status="pending").count()
        recent_signups = User.query.order_by(User.created_at.desc()).limit(8).all()
        recent_activity = (
            Statement.query.order_by(Statement.created_at.desc()).limit(12).all()
        )
        return render_template(
            "admin/index.html",
            totals={
                "users": total_users,
                "requests": total_requests,
                "open_requests": open_requests,
                "completed_requests": completed_requests,
                "flagged": flagged_pending,
            },
            recent_signups=recent_signups,
            recent_activity=recent_activity,
        )

    @app.route("/admin/users")
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

    @app.post("/admin/users/<int:user_id>/blacklist")
    @login_required
    @admin_required
    def admin_blacklist_user(user_id: int):
        from models import User
        reason = (request.form.get("reason") or "").strip() or None
        u = User.query.get_or_404(user_id)
        u.is_blacklisted = True
        u.blacklist_reason = reason
        db.session.commit()

        # Blockchain log: user blacklisted
        try:
            append_statement(
                kind="admin_blacklist",
                payload={
                    "target_user_id": user_id,
                    "reason": reason,
                    "admin_id": current_user.id,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("用户已拉黑。", "success")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<int:user_id>/unblacklist")
    @login_required
    @admin_required
    def admin_unblacklist_user(user_id: int):
        from models import User
        u = User.query.get_or_404(user_id)
        u.is_blacklisted = False
        u.blacklist_reason = None
        db.session.commit()

        # Blockchain log: user unblacklisted
        try:
            append_statement(
                kind="admin_unblacklist",
                payload={
                    "target_user_id": user_id,
                    "admin_id": current_user.id,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("用户已取消拉黑。", "success")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<int:user_id>/delete")
    @login_required
    @admin_required
    def admin_delete_user(user_id: int):
        from models import User
        u = User.query.get_or_404(user_id)
        db.session.delete(u)
        db.session.commit()

        # Blockchain log: user deleted
        try:
            append_statement(
                kind="admin_delete_user",
                payload={
                    "target_user_id": user_id,
                    "deleted_username": u.username,
                    "admin_id": current_user.id,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("用户已删除。", "success")
        return redirect(url_for("admin_users"))

    # ------------------
    # Admin: moderation (flags and NGO approvals)
    # ------------------
    @app.route("/admin/moderation")
    @login_required
    @admin_required
    def admin_moderation():
        from models import Flag, NGO
        flags = Flag.query.order_by(Flag.created_at.desc()).limit(50).all()
        pending_ngos = NGO.query.filter_by(verified_status=False).order_by(NGO.created_at.desc()).all()
        return render_template("admin/moderation.html", flags=flags, pending_ngos=pending_ngos)

    @app.post("/admin/flags/<int:flag_id>/<string:action>")
    @login_required
    @admin_required
    def admin_flag_action(flag_id: int, action: str):
        from models import Flag, HelpRequest, User, Review
        fl = Flag.query.get_or_404(flag_id)
        if action not in ("approve", "reject"):
            abort(400)

        if fl.status != "pending":
            flash("该举报已被处理。", "info")
            return redirect(url_for("admin_moderation"))

        fl.status = "approved" if action == "approve" else "rejected"

        # 如果通过举报，对被举报内容执行处理动作
        if action == "approve":
            if fl.content_type == "request":
                req = HelpRequest.query.get(fl.content_id)
                if req and req.status in ("open", "in_progress"):
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

            # Blockchain log
            try:
                append_statement(
                    kind="flag_approved",
                    payload={
                        "flag_id": fl.id,
                        "content_type": fl.content_type,
                        "content_id": fl.content_id,
                        "reason": fl.reason,
                        "admin_id": current_user.id,
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass
        else:
            flash("举报已驳回。", "success")

        db.session.commit()
        return redirect(url_for("admin_moderation"))

    @app.post("/admin/ngos/<int:ngo_id>/verify")
    @login_required
    @admin_required
    def admin_verify_ngo(ngo_id: int):
        from models import NGO
        n = NGO.query.get_or_404(ngo_id)
        n.verified_status = True
        db.session.commit()

        # Blockchain log: NGO verified
        try:
            append_statement(
                kind="admin_verify_ngo",
                payload={
                    "ngo_id": ngo_id,
                    "ngo_name": n.name,
                    "admin_id": current_user.id,
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
        except Exception:  # noqa: BLE001
            pass

        flash("公益组织已认证。", "success")
        return redirect(url_for("admin_moderation"))

    # Profiles
    @app.route("/u/<string:username>")
    def profile_view(username: str):
        from models import User, HelpRequest, HelpOffer, Review, Statement
        user = User.query.filter_by(username=username).first_or_404()

        # Stats
        requests_completed = HelpRequest.query.filter_by(user_id=user.id, status="completed").count()
        helps_completed = HelpOffer.query.filter_by(helper_id=user.id, status="completed").count()

        # Success rate: completed offers / all offers (accepted or completed considered attempts)
        total_offers_attempted = HelpOffer.query.filter(HelpOffer.helper_id == user.id, HelpOffer.status.in_(["accepted", "completed", "rejected"]))
        total_offers_attempted_count = total_offers_attempted.count() or 0
        success_rate = 0
        if total_offers_attempted_count:
            success_rate = int((helps_completed / total_offers_attempted_count) * 100)

        # Reputation tier (simple mapping)
        score = float(getattr(user, "reputation_score", 0.0) or 0.0)
        if score >= 80:
            tier = "专家"
        elif score >= 50:
            tier = "可信赖"
        elif score >= 20:
            tier = "帮助者"
        else:
            tier = "新手"

        # Reviews received (paginated)
        page = int(request.args.get("page", 1) or 1)
        per_page = 5
        reviews_q = Review.query.filter_by(reviewee_id=user.id).order_by(Review.created_at.desc())
        reviews = reviews_q.paginate(page=page, per_page=per_page, error_out=False)
        latest_reputation_anchor = (
            Statement.query.filter_by(user_id=user.id, kind="reputation_snapshot_anchored")
            .order_by(Statement.created_at.desc())
            .first()
        )

        return render_template(
            "profile/view.html",
            profile_user=user,
            stats={
                "requests_completed": requests_completed,
                "helps_completed": helps_completed,
                "success_rate": success_rate,
            },
            tier=tier,
            reviews=reviews,
            latest_reputation_anchor=latest_reputation_anchor,
            can_anchor_reputation=(current_user.is_authenticated and current_user.id == user.id),
        )

    def _build_reputation_snapshot(user) -> dict:
        from models import HelpRequest, HelpOffer

        requests_completed = HelpRequest.query.filter_by(user_id=user.id, status="completed").count()
        helps_completed = HelpOffer.query.filter_by(helper_id=user.id, status="completed").count()
        total_offers_attempted = HelpOffer.query.filter(
            HelpOffer.helper_id == user.id,
            HelpOffer.status.in_(["accepted", "completed", "rejected"]),
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
            "user_id": user.id,
            "username": user.username,
            "reputation_score": score,
            "tier": tier,
            "requests_completed": requests_completed,
            "helps_completed": helps_completed,
            "success_rate": success_rate,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        snapshot_blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        snapshot["snapshot_hash"] = hashlib.sha256(snapshot_blob).hexdigest()
        return snapshot

    @app.route("/blockchain/reputation/proof/<string:username>")
    @login_required
    def reputation_proof(username: str):
        from models import User, Statement

        user = User.query.filter_by(username=username).first_or_404()
        snapshot = _build_reputation_snapshot(user)
        latest_anchor = (
            Statement.query.filter_by(user_id=user.id, kind="reputation_snapshot_anchored")
            .order_by(Statement.created_at.desc())
            .first()
        )
        return jsonify(
            {
                "ok": True,
                "snapshot": snapshot,
                "latest_anchor": latest_anchor.payload if latest_anchor else None,
            }
        )

    @app.route("/blockchain/reputation/anchor", methods=["POST"])
    @login_required
    def anchor_my_reputation():
        snapshot = _build_reputation_snapshot(current_user)
        anchor_text = json.dumps(
            {
                "source": "dailyhelper_reputation_anchor",
                "snapshot_hash": snapshot["snapshot_hash"],
                "snapshot": snapshot,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            tx = submit_anchor_transaction(anchor_text)
            append_statement(
                kind="reputation_snapshot_anchored",
                payload={
                    "snapshot_hash": snapshot["snapshot_hash"],
                    "reputation_score": snapshot["reputation_score"],
                    "tier": snapshot["tier"],
                    "tx_hash": tx.get("tx_hash"),
                    "chain_id": tx.get("chain_id"),
                    "tx_status": tx.get("status"),
                    "tx_url": tx.get("tx_url"),
                    "anchored_at": datetime.utcnow().isoformat() + "Z",
                },
                user_id=current_user.id,
            )
            maybe_seal_block()
            flash(f"信誉快照已上链：{tx.get('tx_hash')}", "success")
        except Exception as e:  # noqa: BLE001
            try:
                append_statement(
                    kind="reputation_snapshot_anchor_failed",
                    payload={
                        "snapshot_hash": snapshot["snapshot_hash"],
                        "error": str(e)[:500],
                        "failed_at": datetime.utcnow().isoformat() + "Z",
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:
                pass
            flash(f"信誉快照上链失败：{e}", "error")
        return redirect(url_for("profile_view", username=current_user.username))

    @app.route("/settings/profile", methods=["GET", "POST"])
    @login_required
    def profile_edit():
        import os
        import uuid
        from werkzeug.utils import secure_filename
        from models import User
        from forms import ProfileForm

        user = current_user
        form = ProfileForm(obj=user)
        if form.validate_on_submit():
            user.full_name = form.full_name.data or None
            user.phone = form.phone.data or None
            user.location = form.location.data or None
            user.bio = form.bio.data or None
            user.skills = form.skills.data or None

            # Handle avatar file upload
            if form.avatar.data:
                file = form.avatar.data
                if hasattr(file, 'filename') and file.filename:
                    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    upload_dir = os.path.join(app.static_folder, 'uploads', 'avatars')
                    os.makedirs(upload_dir, exist_ok=True)
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    # Delete old avatar file if exists
                    if user.avatar_url and user.avatar_url.startswith('/static/uploads/avatars/'):
                        old_path = os.path.join(app.root_path, user.avatar_url.lstrip('/'))
                        if os.path.exists(old_path):
                            try:
                                os.remove(old_path)
                            except Exception:
                                pass
                    user.avatar_url = f"/static/uploads/avatars/{filename}"

            # Save lat/lng if provided
            try:
                user.latitude = float(form.latitude.data) if form.latitude.data is not None else None
            except Exception:
                user.latitude = None
            try:
                user.longitude = float(form.longitude.data) if form.longitude.data is not None else None
            except Exception:
                user.longitude = None
            db.session.commit()

            # Blockchain log: profile update
            try:
                append_statement(
                    kind="profile_update",
                    payload={
                        "updated_fields": [
                            field for field in ["full_name", "phone", "location", "bio", "skills", "avatar", "latitude", "longitude"]
                            if getattr(form, field).data is not None
                        ],
                    },
                    user_id=current_user.id,
                )
                maybe_seal_block()
            except Exception:  # noqa: BLE001
                pass

            flash("个人资料已更新。", "success")
            return redirect(url_for("profile_view", username=user.username))

        if request.method == "POST" and form.errors:
            for field, errs in form.errors.items():
                for e in errs:
                    flash(f"{field}: {e}", "error")

        return render_template("profile/edit.html", form=form)

    # ── #1 消息系统 ──────────────────────────────────────────
    @app.route("/messages")
    @login_required
    def messages_inbox():
        from models import Message, User
        from sqlalchemy import or_, and_, func

        # 获取所有对话伙伴（最近消息排序）
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
        # 未读消息计数
        unread_counts = {}
        for msg, partner in conversations:
            cnt = Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False).count()
            unread_counts[partner.id] = cnt

        return render_template("messages/inbox.html", conversations=conversations, unread_counts=unread_counts)

    @app.route("/messages/<int:user_id>", methods=["GET", "POST"])
    @login_required
    def messages_chat(user_id: int):
        from models import Message, User
        from forms import MessageForm
        from sqlalchemy import or_, and_

        partner = User.query.get_or_404(user_id)
        if partner.id == current_user.id:
            flash("不能给自己发消息。", "error")
            return redirect(url_for("messages_inbox"))

        form = MessageForm()
        if form.validate_on_submit():
            msg = Message(
                sender_id=current_user.id,
                receiver_id=partner.id,
                content=form.content.data.strip(),
            )
            db.session.add(msg)
            db.session.commit()
            # 通知对方
            _notify(
                partner.id,
                "new_message",
                f"{current_user.username} 给你发了一条私信",
                url_for("messages_chat", user_id=current_user.id),
            )
            db.session.commit()
            return redirect(url_for("messages_chat", user_id=partner.id))

        # 标记该对话中对方发来的消息为已读
        Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False).update({"is_read": True})
        db.session.commit()

        # 获取对话消息
        chat_messages = (
            Message.query.filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == partner.id),
                    and_(Message.sender_id == partner.id, Message.receiver_id == current_user.id),
                )
            )
            .order_by(Message.created_at.asc())
            .limit(200)
            .all()
        )
        return render_template("messages/chat.html", partner=partner, chat_messages=chat_messages, form=form)

    # ── #2 搜索功能 ──────────────────────────────────────────
    @app.route("/search")
    def search_page():
        from models import HelpRequest, User
        from sqlalchemy import or_

        q = request.args.get("q", "").strip()
        search_type = request.args.get("type", "all")  # all / requests / users
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

        return render_template(
            "search.html",
            q=q,
            search_type=search_type,
            results_requests=results_requests,
            results_users=results_users,
            pagination_requests=pagination_requests,
            pagination_users=pagination_users,
        )

    # ── #8 排行榜 ──────────────────────────────────────────
    @app.route("/leaderboard")
    def leaderboard():
        from models import User, HelpRequest, HelpOffer
        from sqlalchemy import func

        # 信誉排行
        top_reputation = User.query.filter(User.user_type != "admin").order_by(User.reputation_score.desc()).limit(20).all()

        # 帮助次数排行
        top_helpers = (
            db.session.query(User, func.count(HelpOffer.id).label("help_count"))
            .join(HelpOffer, HelpOffer.helper_id == User.id)
            .filter(HelpOffer.status == "completed")
            .group_by(User.id)
            .order_by(func.count(HelpOffer.id).desc())
            .limit(20)
            .all()
        )

        # 求助完成排行
        top_requesters = (
            db.session.query(User, func.count(HelpRequest.id).label("req_count"))
            .join(HelpRequest, HelpRequest.user_id == User.id)
            .filter(HelpRequest.status == "completed")
            .group_by(User.id)
            .order_by(func.count(HelpRequest.id).desc())
            .limit(20)
            .all()
        )

        return render_template(
            "leaderboard.html",
            top_reputation=top_reputation,
            top_helpers=top_helpers,
            top_requesters=top_requesters,
        )

    # ── #12 区块链详情 ──────────────────────────────────────
    @app.route("/blockchain/blocks/<int:block_id>")
    @login_required
    def blockchain_block_detail(block_id: int):
        from models import Block, Statement
        block = Block.query.get_or_404(block_id)
        statements = Statement.query.filter_by(block_id=block.id).order_by(Statement.created_at.asc()).all()
        # 前后区块
        prev_block = Block.query.filter(Block.index < block.index).order_by(Block.index.desc()).first()
        next_block = Block.query.filter(Block.index > block.index).order_by(Block.index.asc()).first()
        return render_template(
            "blockchain/block_detail.html",
            block=block,
            statements=statements,
            prev_block=prev_block,
            next_block=next_block,
        )

    @app.route("/blockchain/statements/<int:statement_id>")
    @login_required
    def blockchain_statement_detail(statement_id: int):
        from models import Statement
        stmt = Statement.query.get_or_404(statement_id)
        return render_template("blockchain/statement_detail.html", stmt=stmt)

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):  # noqa: ANN001
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):  # noqa: ANN001
        return render_template("errors/500.html"), 500

    return app


# Optional: allow `python app.py` to run a dev server
if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=True)
