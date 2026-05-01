import logging

from flask import Flask, render_template, request
from flask_login import current_user

from extensions import db, login_manager, csrf, migrate
from web3_service import init_web3


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
    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    # Initialize Web3 client (if ETH_RPC_URL set)
    app.extensions = getattr(app, "extensions", {})
    app.extensions["web3"] = init_web3(app.config.get("ETH_RPC_URL", ""))

    @app.after_request
    def add_no_store_for_dynamic_html(response):  # noqa: ANN001
        if response.content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Flask-Login config
    login_manager.login_view = "auth.login"
    login_manager.login_message = "请先登录后再访问该页面。"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):  # noqa: ANN001
        from models import User
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # Enable SQLite WAL mode so concurrent reads don't block writes,
    # and busy_timeout so writers wait instead of immediately erroring.
    # MUST register before first connection (before create_all) or old
    # connections retain delete journal mode.
    from sqlalchemy import event
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        import models  # noqa: F401
        db.create_all()

    # ── Global template context ─────────────────────────
    @app.context_processor
    def inject_unread_count():
        if current_user.is_authenticated:
            from models import Notification, Message
            notif_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            msg_count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
            return {"unread_notifications": notif_count, "unread_messages": msg_count}
        return {"unread_notifications": 0, "unread_messages": 0}

    # ── Register Blueprints ──────────────────────────────
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.features import features_bp
    from routes.admin import admin_bp
    from routes.api import api_bp
    from routes.blockchain import blockchain_bp
    from routes.profile import profile_bp
    from routes.messages import messages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(features_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(blockchain_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(messages_bp)

    # ── Backward-compatible endpoint aliases ─────────────
    # Templates use url_for("login") etc.; blueprints register as "auth.login".
    # Map old bare endpoint names → new blueprint endpoints so all templates
    # keep working without modification.
    _ENDPOINT_ALIASES = {
        # auth
        "login": "auth.login", "signup": "auth.signup", "logout": "auth.logout",
        "forgot_password": "auth.forgot_password", "reset_password": "auth.reset_password",
        "change_password": "auth.change_password",
        # main
        "index": "main.index", "dashboard": "main.dashboard", "about": "main.about",
        "notifications": "main.notifications", "help_page": "main.help_page",
        "terms_page": "main.terms_page", "privacy_page": "main.privacy_page",
        "search_page": "main.search_page", "leaderboard": "main.leaderboard",
        "post_login_redirect": "main.post_login_redirect",
        # features
        "request_help": "features.request_help", "offer_help": "features.offer_help",
        "request_detail": "features.request_detail", "cancel_request": "features.cancel_request",
        "edit_request": "features.edit_request", "flag_content": "features.flag_content",
        "volunteer": "features.volunteer", "nearby": "features.nearby",
        "marketplace": "features.marketplace", "my_offers": "features.my_offers",
        # admin
        "admin": "admin.admin_index",
        "admin_users": "admin.admin_users",
        "admin_blacklist_user": "admin.admin_blacklist_user",
        "admin_unblacklist_user": "admin.admin_unblacklist_user",
        "admin_delete_user": "admin.admin_delete_user",
        "admin_moderation": "admin.admin_moderation",
        "admin_flag_action": "admin.admin_flag_action",
        "admin_requests": "admin.admin_requests",
        "admin_cancel_request": "admin.admin_cancel_request",
        "admin_payments": "admin.admin_payments",
        "admin_export": "admin.admin_export",
        "admin_broadcast": "admin.admin_broadcast",
        "admin_sbt": "admin.admin_sbt",
        # api / wallet / payment / sbt / escrow
        "connect_wallet": "api.connect_wallet", "wallet_me": "api.wallet_me",
        "wallet_challenge": "api.wallet_challenge", "wallet_verify": "api.wallet_verify",
        "wallet_disconnect": "api.wallet_disconnect",
        "web3_status": "api.web3_status", "web3_balance": "api.web3_balance",
        "submit_payment_address": "api.submit_payment_address",
        "record_payment": "api.record_payment",
        "api_sbt_proof": "api.api_sbt_proof", "api_sbt_status": "api.api_sbt_status",
        "api_escrow_sync": "api.api_escrow_sync",
        "api_contracts_config": "api.api_contracts_config",
        "arbitration_hall": "api.arbitration_hall",
        "chatbot": "api.chatbot", "chatbot_api": "api.chatbot_api",
        # blockchain
        "blockchain_blocks": "blockchain.blockchain_blocks",
        "blockchain_block_detail": "blockchain.blockchain_block_detail",
        "blockchain_statement_detail": "blockchain.blockchain_statement_detail",
        "reputation_proof": "blockchain.reputation_proof",
        "anchor_my_reputation": "blockchain.anchor_my_reputation",
        # profile
        "profile_view": "profile.profile_view", "profile_edit": "profile.profile_edit",
        # messages
        "messages_inbox": "messages.messages_inbox", "messages_chat": "messages.messages_chat",
    }
    def _handle_url_build_error(error, endpoint, values):
        """Resolve old bare endpoint names to new blueprint-prefixed endpoints."""
        from flask import url_for as _url_for
        new_ep = _ENDPOINT_ALIASES.get(endpoint)
        if new_ep:
            return _url_for(new_ep, **values)
        raise error

    app.url_build_error_handlers.append(_handle_url_build_error)

    # ── Error handlers ───────────────────────────────────
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
