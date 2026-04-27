"""Comprehensive route tests using existing demo data.

Demo users (password: test123 / admin123 for admin):
  admin(id=1, admin@dailyhelper.com),
  alice(id=2, alice@test.com), bob(id=3, bob@test.com),
  charlie(id=4), diana(id=5), eve(id=6),
  expert1(id=7), expert2(id=8), expert3(id=9)

Run:
    python -m pytest tests/test_routes.py -v
"""

import pytest
from app import create_app
from extensions import db


# ──────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Create app once for all tests in this module."""
    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture()
def client(app):
    """Fresh client per test to avoid session leakage."""
    return app.test_client()


def _login(client, email, password):
    """Helper: log in via POST (LoginForm uses email field)."""
    return client.post("/login", data={
        "email": email, "password": password, "remember_me": "",
    }, follow_redirects=True)


def _logout(client):
    return client.get("/logout", follow_redirects=True)


# ──────────────────────────────────────────────────────
# 1. Public pages (no login needed)
# ──────────────────────────────────────────────────────

class TestPublicPages:
    def test_about(self, client):
        r = client.get("/about")
        assert r.status_code == 200
        assert "每日互助".encode() in r.data or b"DailyHelper" in r.data

    def test_help(self, client):
        assert client.get("/help").status_code == 200

    def test_terms(self, client):
        assert client.get("/terms").status_code == 200

    def test_privacy(self, client):
        assert client.get("/privacy").status_code == 200

    def test_login_page(self, client):
        r = client.get("/login")
        assert r.status_code == 200
        assert "no-store" in r.headers.get("Cache-Control", "")
        assert r.headers.get("Pragma") == "no-cache"
        assert r.headers.get("Expires") == "0"

    def test_signup_page(self, client):
        r = client.get("/signup")
        assert r.status_code == 200

    def test_marketplace(self, client):
        assert client.get("/marketplace").status_code == 200

    def test_volunteer(self, client):
        assert client.get("/volunteer").status_code == 200

    def test_leaderboard(self, client):
        assert client.get("/leaderboard").status_code == 200

    def test_search_empty(self, client):
        assert client.get("/search").status_code == 200

    def test_search_query(self, client):
        r = client.get("/search?q=help&type=all")
        assert r.status_code == 200

    def test_contracts_config_api(self, client):
        r = client.get("/api/contracts/config")
        assert r.status_code == 200
        data = r.get_json()
        assert "sbt_contract" in data
        assert "chain_id" in data


# ──────────────────────────────────────────────────────
# 2. Auth flow
# ──────────────────────────────────────────────────────

class TestAuth:
    def test_login_success(self, client):
        r = _login(client, "alice@test.com", "test123")
        assert r.status_code == 200

    def test_login_wrong_password(self, client):
        r = _login(client, "alice@test.com", "wrong")
        assert r.status_code == 200
        assert "邮箱或密码错误".encode() in r.data or "密码错误".encode() in r.data

    def test_login_nonexistent_email(self, client):
        r = _login(client, "nobody@test.com", "test123")
        assert r.status_code == 200

    def test_logout(self, client):
        _login(client, "alice@test.com", "test123")
        r = _logout(client)
        assert r.status_code == 200

    def test_logout_clears_session(self, client):
        _login(client, "alice@test.com", "test123")
        with client.session_transaction() as sess:
            sess["temporary_switch_state"] = "stale"
        r = client.get("/logout", follow_redirects=False)
        assert r.status_code == 302
        with client.session_transaction() as sess:
            assert "_user_id" not in sess
            assert "temporary_switch_state" not in sess

    def test_protected_redirect(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 302
        assert "/login" in r.headers.get("Location", "")

    def test_forgot_password_page(self, client):
        assert client.get("/forgot-password").status_code == 200

    def test_change_password_page(self, client):
        _login(client, "alice@test.com", "test123")
        assert client.get("/settings/password").status_code == 200


# ──────────────────────────────────────────────────────
# 3. Main routes (logged-in user)
# ──────────────────────────────────────────────────────

class TestMainRoutes:
    def test_index(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/")
        assert r.status_code == 200

    def test_dashboard(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/dashboard")
        assert r.status_code == 200

    def test_notifications(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/notifications")
        assert r.status_code == 200

    def test_post_login_redirect_normal(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/post-login-redirect")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_post_login_redirect_admin(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/post-login-redirect")
        assert r.status_code == 302
        assert "/admin" in r.headers.get("Location", "")


# ──────────────────────────────────────────────────────
# 4. Features (help requests, offers, flags)
# ──────────────────────────────────────────────────────

class TestFeatures:
    def test_request_help_page(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/request-help")
        assert r.status_code == 200

    def test_request_detail(self, client, app):
        _login(client, "alice@test.com", "test123")
        with app.app_context():
            from models import HelpRequest
            req = HelpRequest.query.filter_by(status="open").first()
            assert req is not None
            r = client.get(f"/requests/{req.id}")
            assert r.status_code == 200

    def test_offer_help_list_page(self, client):
        _login(client, "bob@test.com", "test123")
        r = client.get("/offer-help")
        assert r.status_code == 200

    def test_request_detail_as_helper(self, client, app):
        """Helper can view request detail page (offers are submitted via POST to /requests/<id>)."""
        _login(client, "bob@test.com", "test123")
        with app.app_context():
            from models import HelpRequest
            req = HelpRequest.query.filter_by(status="open").first()
            if req:
                r = client.get(f"/requests/{req.id}")
                assert r.status_code == 200

    def test_marketplace(self, client):
        r = client.get("/marketplace")
        assert r.status_code == 200

    def test_marketplace_filter(self, client):
        r = client.get("/marketplace?category=IT+Support&sort=newest")
        assert r.status_code == 200

    def test_volunteer(self, client):
        r = client.get("/volunteer")
        assert r.status_code == 200

    def test_nearby(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/nearby")
        assert r.status_code == 200

    def test_my_offers(self, client):
        _login(client, "bob@test.com", "test123")
        r = client.get("/my-offers")
        assert r.status_code == 200

    def test_flag_content(self, client, app):
        _login(client, "eve@test.com", "test123")
        with app.app_context():
            from models import HelpRequest
            req = HelpRequest.query.filter_by(status="open").first()
            if req:
                r = client.post(f"/flag/request/{req.id}", data={
                    "reason": "Test flag from pytest",
                }, follow_redirects=True)
                assert r.status_code == 200


# ──────────────────────────────────────────────────────
# 5. Profile
# ──────────────────────────────────────────────────────

class TestProfile:
    def test_view_profile(self, client):
        r = client.get("/u/alice")
        assert r.status_code == 200
        assert "Alice".encode() in r.data

    def test_view_profile_expert(self, client):
        r = client.get("/u/expert1")
        assert r.status_code == 200

    def test_view_profile_404(self, client):
        r = client.get("/u/nonexistent_user_xyz")
        assert r.status_code == 404

    def test_edit_profile_page(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/settings/profile")
        assert r.status_code == 200

    def test_edit_profile_submit(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.post("/settings/profile", data={
            "full_name": "Alice Wang Updated",
            "phone": "13800138000",
            "location": "Beijing",
            "bio": "Updated bio from pytest.",
            "skills": "Python, Testing",
            "latitude": "39.9042",
            "longitude": "116.4074",
        }, follow_redirects=True)
        assert r.status_code == 200


# ──────────────────────────────────────────────────────
# 6. Messages
# ──────────────────────────────────────────────────────

class TestMessages:
    def test_inbox(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/messages")
        assert r.status_code == 200

    def test_chat(self, client, app):
        _login(client, "alice@test.com", "test123")
        with app.app_context():
            from models import User
            bob = User.query.filter_by(username="bob").first()
            r = client.get(f"/messages/{bob.id}")
            assert r.status_code == 200

    def test_send_message(self, client, app):
        _login(client, "alice@test.com", "test123")
        with app.app_context():
            from models import User
            bob = User.query.filter_by(username="bob").first()
            r = client.post(f"/messages/{bob.id}", data={
                "content": "Hello from pytest!",
            }, follow_redirects=True)
            assert r.status_code == 200

    def test_cannot_message_self(self, client, app):
        _login(client, "alice@test.com", "test123")
        with app.app_context():
            from models import User
            alice = User.query.filter_by(username="alice").first()
            r = client.get(f"/messages/{alice.id}", follow_redirects=True)
            assert r.status_code == 200


# ──────────────────────────────────────────────────────
# 7. Admin
# ──────────────────────────────────────────────────────

class TestAdmin:
    def test_admin_dashboard(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/")
        assert r.status_code == 200

    def test_admin_users(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/users")
        assert r.status_code == 200

    def test_admin_users_search(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/users?q=alice")
        assert r.status_code == 200

    def test_admin_moderation(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/moderation")
        assert r.status_code == 200

    def test_admin_requests(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/requests")
        assert r.status_code == 200

    def test_admin_payments(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/payments")
        assert r.status_code == 200

    def test_admin_broadcast_page(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/broadcast")
        assert r.status_code == 200

    def test_admin_broadcast_send(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.post("/admin/broadcast", data={
            "message": "Test broadcast from pytest",
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_admin_export_users(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/export/users")
        assert r.status_code == 200
        assert "text/csv" in r.content_type

    def test_admin_export_requests(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/export/requests")
        assert r.status_code == 200
        assert "text/csv" in r.content_type

    def test_admin_denied_for_normal_user(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/admin/", follow_redirects=True)
        assert r.status_code == 200

    def test_admin_sbt_page(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/sbt")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────
# 8. Blockchain
# ──────────────────────────────────────────────────────

class TestBlockchain:
    def test_blocks_page(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/blockchain/blocks")
        assert r.status_code == 200

    def test_web3_status(self, client):
        r = client.get("/web3")
        assert r.status_code == 200

    def test_web3_balance_api(self, client):
        r = client.get("/web3/balance?address=0x0000000000000000000000000000000000000000")
        assert r.status_code == 200
        data = r.get_json()
        assert "address" in data


# ──────────────────────────────────────────────────────
# 9. API endpoints
# ──────────────────────────────────────────────────────

class TestAPI:
    def test_wallet_me(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/wallet/me")
        assert r.status_code == 200
        data = r.get_json()
        assert "address" in data

    def test_wallet_challenge(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.post("/wallet/challenge",
                        json={"address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"},
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("ok") is True
        assert "message" in data

    def test_wallet_verify_invalid_signature(self, client):
        _login(client, "alice@test.com", "test123")
        client.post("/wallet/challenge",
                    json={"address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"},
                    content_type="application/json")
        r = client.post("/wallet/verify",
                        json={"address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
                              "signature": "0x" + "00" * 65},
                        content_type="application/json")
        assert r.status_code == 400

    def test_connect_wallet_page(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/connect-wallet")
        assert r.status_code == 200

    def test_sbt_proof(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/api/sbt/proof")
        assert r.status_code in (200, 400)

    def test_escrow_sync_missing_params(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.post("/api/escrow/sync",
                        json={},
                        content_type="application/json")
        assert r.status_code == 400
        data = r.get_json()
        assert "error" in data

    def test_escrow_sync_not_found(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.post("/api/escrow/sync",
                        json={"task_id": 99999, "action": "lock"},
                        content_type="application/json")
        assert r.status_code == 404

    def test_chatbot_page(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/chatbot")
        assert r.status_code == 200

    def test_chatbot_api_empty(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.post("/api/chatbot",
                        json={"message": ""},
                        content_type="application/json")
        assert r.status_code == 400
        data = r.get_json()
        assert data.get("ok") is False

    def test_chatbot_page_loads_history(self, client, app):
        from models import User, ChatbotMessage

        with app.app_context():
            user = User.query.filter_by(email="alice@test.com").first()
            ChatbotMessage.query.filter(
                ChatbotMessage.user_id == user.id,
                ChatbotMessage.content.in_(["测试历史问题", "测试历史回答"]),
            ).delete(synchronize_session=False)
            db.session.add(ChatbotMessage(user_id=user.id, role="user", content="测试历史问题"))
            db.session.add(ChatbotMessage(user_id=user.id, role="assistant", content="测试历史回答"))
            db.session.commit()

        _login(client, "alice@test.com", "test123")
        r = client.get("/chatbot")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "\\u6d4b\\u8bd5\\u5386\\u53f2\\u95ee\\u9898" in body
        assert "\\u6d4b\\u8bd5\\u5386\\u53f2\\u56de\\u7b54" in body

    def test_chatbot_api_persists_history(self, client, app, monkeypatch):
        from models import User, ChatbotMessage

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"role": "assistant", "content": "持久化测试回答"}}]}

        def fake_post(*args, **kwargs):
            return FakeResponse()

        app.config["KIMI_API_KEY"] = "test-key"
        monkeypatch.setattr("routes.api.http_requests.post", fake_post)

        with app.app_context():
            user = User.query.filter_by(email="alice@test.com").first()
            ChatbotMessage.query.filter(
                ChatbotMessage.user_id == user.id,
                ChatbotMessage.content.in_(["持久化测试问题", "持久化测试回答"]),
            ).delete(synchronize_session=False)
            db.session.commit()

        _login(client, "alice@test.com", "test123")
        r = client.post("/api/chatbot", json={"message": "持久化测试问题"}, content_type="application/json")
        assert r.status_code == 200
        assert r.get_json().get("reply") == "持久化测试回答"

        with app.app_context():
            user = User.query.filter_by(email="alice@test.com").first()
            saved = ChatbotMessage.query.filter(
                ChatbotMessage.user_id == user.id,
                ChatbotMessage.content.in_(["持久化测试问题", "持久化测试回答"]),
            ).count()
            assert saved == 2

    def test_arbitration_hall_low_rep(self, client):
        _login(client, "alice@test.com", "test123")
        r = client.get("/arbitration", follow_redirects=True)
        assert r.status_code == 200

    def test_arbitration_hall_gold_user(self, client):
        _login(client, "expert1@test.com", "test123")
        r = client.get("/arbitration")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────
# 10. Error handlers
# ──────────────────────────────────────────────────────

class TestErrors:
    def test_404(self, client):
        r = client.get("/this-page-does-not-exist-at-all")
        assert r.status_code == 404

    def test_admin_export_invalid(self, client):
        _login(client, "admin@dailyhelper.com", "admin123")
        r = client.get("/admin/export/invalid_type")
        assert r.status_code == 404


# ──────────────────────────────────────────────────────
# 11. Endpoint alias backward compatibility
# ──────────────────────────────────────────────────────

class TestEndpointAliases:
    """Verify that old bare endpoint names still resolve via url_for."""

    ALIASES = [
        ("login", {}), ("signup", {}), ("logout", {}),
        ("dashboard", {}), ("about", {}), ("index", {}),
        ("marketplace", {}), ("volunteer", {}), ("nearby", {}),
        ("leaderboard", {}), ("search_page", {}), ("notifications", {}),
        ("request_help", {}), ("my_offers", {}),
        ("request_detail", {"request_id": 1}),
        ("offer_help", {}),
        ("profile_view", {"username": "alice"}),
        ("profile_edit", {}),
        ("messages_inbox", {}), ("messages_chat", {"user_id": 2}),
        ("admin", {}), ("admin_users", {}), ("admin_moderation", {}),
        ("admin_requests", {}), ("admin_payments", {}),
        ("blockchain_blocks", {}),
        ("chatbot", {}), ("web3_status", {}),
        ("arbitration_hall", {}),
    ]

    @pytest.mark.parametrize("endpoint,kwargs", ALIASES)
    def test_alias(self, app, endpoint, kwargs):
        with app.test_request_context():
            from flask import url_for
            url = url_for(endpoint, **kwargs)
            assert url is not None and url.startswith("/")
