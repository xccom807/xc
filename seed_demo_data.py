"""Seed demo data for graduation defense presentation.

Usage:
    myenv\\Scripts\\activate.bat
    python seed_demo_data.py

Test user passwords: test123
Admin: admin / admin123
"""

import math
from datetime import datetime, timedelta

from app import create_app
from extensions import db
from models import (
    User, HelpRequest, HelpOffer, Review, Payment,
    Message, Notification, NGO, Flag, WalletLink,
)


def _calc_reputation(current: float, rating: int, comment: str) -> float:
    base_map = {5: 5, 4: 3, 3: 1, 2: -2, 1: -4}
    base = base_map.get(rating, 0)
    clen = len(comment)
    bonus = 1.8 if clen >= 200 else 1.5 if clen >= 50 else 1.2 if clen >= 10 else 1.0
    if base > 0:
        delta = base * (1.0 / math.log2(current + 2)) * bonus
    else:
        delta = base * bonus
    return max(0.0, min(100.0, current + round(delta, 2)))


def seed():
    app = create_app()
    with app.app_context():
        if User.query.filter_by(username="alice").first():
            print("Demo data already exists. Delete instance/app.db to re-seed.")
            return

        now = datetime.utcnow()

        # 1. Admin
        admin = User.query.filter_by(user_type="admin").first()
        if not admin:
            admin = User(username="admin", email="admin@dailyhelper.com",
                         full_name="System Administrator", user_type="admin",
                         reputation_score=100.0, created_at=now - timedelta(days=60))
            admin.set_password("admin123")
            db.session.add(admin)

        # 2. Users
        users_data = [
            ("alice", "alice@test.com", "Alice Wang", "Beijing", 39.9042, 116.4074,
             "Graduate student, needs help sometimes.", "Python, Translation", 30),
            ("bob", "bob@test.com", "Bob Li", "Beijing", 39.9142, 116.4174,
             "Freelancer, loves helping people.", "Home Repair, Math Tutoring", 28),
            ("charlie", "charlie@test.com", "Charlie Zhang", "Shanghai", 31.2304, 121.4737,
             "Tech enthusiast and volunteer.", "Computer Repair, Web Dev", 25),
            ("diana", "diana@test.com", "Diana Chen", "Beijing", 39.9242, 116.3974,
             "College student, good at cooking.", "Cooking, English, Japanese", 20),
            ("eve", "eve@test.com", "Eve Liu", "Guangzhou", 23.1291, 113.2644,
             "Social worker, community builder.", "Counseling, Event Planning", 15),
        ]
        users = {}
        for uname, email, fname, loc, lat, lng, bio, skills, days in users_data:
            u = User(username=uname, email=email, full_name=fname, location=loc,
                     latitude=lat, longitude=lng, bio=bio, skills=skills,
                     reputation_score=0.0, created_at=now - timedelta(days=days))
            u.set_password("test123")
            db.session.add(u)
            users[uname] = u

        db.session.flush()
        alice, bob, charlie, diana, eve = (
            users["alice"], users["bob"], users["charlie"], users["diana"], users["eve"]
        )
        print(f"  Users: alice={alice.id}, bob={bob.id}, charlie={charlie.id}, "
              f"diana={diana.id}, eve={eve.id}")

        # 3. Help Requests
        reqs = []
        rdata = [
            (alice.id, "Need help moving furniture", "Moving to new apartment, need help with sofa and desk.",
             "Moving", "Beijing Haidian", "Sat 10-13", 0.05, False, "completed", 20),
            (alice.id, "Math tutoring for high school student",
             "Brother needs calculus help, 2h/session twice weekly.",
             "Tutoring", "Beijing Chaoyang", "Weekday 19-21", 0.08, False, "in_progress", 15),
            (diana.id, "Free English conversation practice",
             "Exchange student looking for English practice. Will teach Japanese in return!",
             "Language", "Beijing Dongcheng", "Weekend afternoons", 0.0, True, "open", 10),
            (bob.id, "Need someone to fix my laptop",
             "Laptop running slowly, might need clean install or hardware check.",
             "IT Support", "Beijing Xicheng", "Any weekday PM", 0.03, False, "open", 7),
            (eve.id, "Community garden volunteer needed",
             "Neighborhood garden needs volunteers for spring planting.",
             "Volunteer", "Guangzhou Tianhe", "Sat 9-12", 0.0, True, "open", 5),
            (alice.id, "Help translating a research paper",
             "10-page paper Chinese to English, ML in healthcare topic.",
             "Translation", "Online", "Within one week", 0.1, False, "open", 2),
        ]
        for uid, title, desc, cat, loc, time, price, vol, status, days in rdata:
            r = HelpRequest(user_id=uid, title=title, description=desc, category=cat,
                            location=loc, time_needed=time, price=price, is_volunteer=vol,
                            status=status, created_at=now - timedelta(days=days))
            db.session.add(r)
            reqs.append(r)
        db.session.flush()
        req1, req2, req3, req4, req5, req6 = reqs
        print(f"  Requests: {req1.id}-{req6.id}")

        # 4. Offers
        odata = [
            (req1.id, bob.id, "I have a truck, can help Saturday!", "completed", 19),
            (req1.id, charlie.id, "I can help carry things.", "rejected", 18),
            (req2.id, bob.id, "Math degree + tutoring exp. Happy to help!", "accepted", 14),
            (req3.id, charlie.id, "Fluent English, want to learn Japanese!", "pending", 8),
            (req3.id, eve.id, "Native English speaker, always wanted to learn JP.", "pending", 7),
            (req4.id, charlie.id, "IT is my specialty. Can check this week.", "pending", 6),
            (req5.id, diana.id, "Love gardening! Count me in.", "pending", 4),
            (req6.id, charlie.id, "Experience translating technical papers.", "pending", 1),
        ]
        offers = []
        for rid, hid, msg, status, days in odata:
            o = HelpOffer(request_id=rid, helper_id=hid, message=msg, status=status,
                          created_at=now - timedelta(days=days))
            db.session.add(o)
            offers.append(o)
        db.session.flush()
        print(f"  Offers: {offers[0].id}-{offers[-1].id}")

        # 5. Reviews (for completed req1)
        c1 = ("Bob was amazing! Arrived on time with truck, very careful with fragile items. "
              "Highly recommended for moving help. Even helped arrange furniture in new place!")
        c2 = ("Alice was well-prepared with everything boxed up. Clear instructions. "
              "Pleasant to work with. Provided great lunch too!")
        c3 = ("Bob explains math concepts clearly and patiently. My brother's grades improved!")
        c4 = "Good student, always prepared for sessions."

        rev_data = [
            (req1.id, alice.id, bob.id, 5, c1, 17),
            (req1.id, bob.id, alice.id, 4, c2, 16),
            (req2.id, alice.id, bob.id, 5, c3, 5),
            (req2.id, bob.id, alice.id, 4, c4, 4),
        ]
        for rid, rer, ree, rating, comment, days in rev_data:
            rv = Review(request_id=rid, reviewer_id=rer, reviewee_id=ree, rating=rating,
                        comment=comment, created_at=now - timedelta(days=days))
            db.session.add(rv)
            # Update reputation
            target = User.query.get(ree)
            target.reputation_score = _calc_reputation(
                target.reputation_score, rating, comment)

        db.session.flush()
        print(f"  Reviews: 4 created. bob rep={bob.reputation_score:.2f}, alice rep={alice.reputation_score:.2f}")

        # 6. Payment (for completed req1)
        pay = Payment(
            request_id=req1.id, helper_id=bob.id, requester_id=alice.id,
            helper_address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
            amount=150.0,
            tx_hash="0xabc123def456789012345678901234567890abcdef1234567890abcdef12345678",
            status="paid",
            address_submitted_at=now - timedelta(days=18),
            paid_at=now - timedelta(days=17),
        )
        db.session.add(pay)

        # 7. Messages (alice <-> bob about req2)
        msgs = [
            (alice.id, bob.id, "Hi Bob! Thanks for accepting the tutoring offer.", 13),
            (bob.id, alice.id, "No problem! When should we start?", 13),
            (alice.id, bob.id, "How about this Wednesday at 7pm?", 12),
            (bob.id, alice.id, "Sounds good. I'll prepare some calculus materials.", 12),
            (alice.id, bob.id, "Great! My brother is excited. See you then!", 11),
        ]
        for sid, rid, content, days in msgs:
            m = Message(sender_id=sid, receiver_id=rid, content=content,
                        is_read=True, created_at=now - timedelta(days=days))
            db.session.add(m)

        # 8. Notifications (sample)
        notifs = [
            (alice.id, "offer_received", "Bob submitted an offer for your request", 19),
            (bob.id, "offer_accepted", "Alice accepted your help offer!", 19),
            (alice.id, "review_received", "Bob gave you a 4-star review", 16),
            (bob.id, "review_received", "Alice gave you a 5-star review", 17),
            (bob.id, "new_message", "Alice sent you a message", 13),
        ]
        for uid, kind, msg, days in notifs:
            n = Notification(user_id=uid, kind=kind, message=msg, is_read=True,
                             created_at=now - timedelta(days=days))
            db.session.add(n)

        # 9. NGOs
        ngo1 = NGO(name="Green Earth Foundation", category="Environment",
                    description="Dedicated to urban greening and environmental education.",
                    location="Beijing", contact_email="info@greenearth.org",
                    website="https://greenearth.org", verified_status=True,
                    created_at=now - timedelta(days=40))
        ngo2 = NGO(name="Youth Coding Initiative", category="Education",
                    description="Teaching programming to underprivileged youth.",
                    location="Shanghai", contact_email="hello@youthcode.cn",
                    website="https://youthcode.cn", verified_status=False,
                    created_at=now - timedelta(days=10))
        db.session.add_all([ngo1, ngo2])

        # 10. Flag (pending for admin to review)
        flag = Flag(content_type="request", content_id=req4.id,
                    reason="Suspicious pricing, might be a scam.", status="pending",
                    created_at=now - timedelta(days=3))
        db.session.add(flag)

        # 11. Expert Users (high reputation for DAO arbitration demo)
        experts_data = [
            ("expert1", "expert1@test.com", "Frank Expert", "Beijing", 39.91, 116.41,
             "Blockchain specialist, community arbitrator.", "Solidity, Audit", 50),
            ("expert2", "expert2@test.com", "Grace Judge", "Shanghai", 31.23, 121.47,
             "Senior mediator with years of experience.", "Mediation, Law", 45),
            ("expert3", "expert3@test.com", "Henry Arbiter", "Shenzhen", 22.54, 114.06,
             "Professional dispute resolution expert.", "Arbitration, DeFi", 40),
        ]
        experts = {}
        for uname, email, fname, loc, lat, lng, bio, skills, days in experts_data:
            u = User(username=uname, email=email, full_name=fname, location=loc,
                     latitude=lat, longitude=lng, bio=bio, skills=skills,
                     reputation_score=85.0,  # Gold tier (>=80)
                     created_at=now - timedelta(days=days))
            u.set_password("test123")
            db.session.add(u)
            experts[uname] = u
        db.session.flush()
        print(f"  Experts: {experts['expert1'].id}-{experts['expert3'].id} (rep=85, Gold tier)")

        # 12. Wallet Links (MetaMask bindings for key users)
        # These are demo addresses on Sepolia testnet
        wallet_data = [
            (alice.id,  "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
            (bob.id,    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"),
            (charlie.id,"0x90F79bf6EB2c4f870365E785982E1f101E93b906"),
            (experts["expert1"].id, "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"),
            (experts["expert2"].id, "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"),
            (experts["expert3"].id, "0x976EA74026E726554dB657fA54763abd0C3a0aa9"),
        ]
        for uid, addr in wallet_data:
            wl = WalletLink(user_id=uid, address=addr,
                            verified_at=now - timedelta(days=10),
                            created_at=now - timedelta(days=10))
            db.session.add(wl)
        db.session.flush()
        print(f"  Wallet links: {len(wallet_data)} created")

        # 13. Disputed Task (for DAO arbitration demo)
        disputed_req = HelpRequest(
            user_id=diana.id,
            title="Website redesign - disputed quality",
            description="Paid for a website redesign, but the result did not meet expectations. "
                        "Need DAO arbitration to resolve this dispute.",
            category="IT Support", location="Online", time_needed="1 week",
            price=0.05, is_volunteer=False, status="disputed",
            created_at=now - timedelta(days=3),
        )
        db.session.add(disputed_req)
        db.session.flush()

        # Offer for disputed task
        disputed_offer = HelpOffer(
            request_id=disputed_req.id, helper_id=charlie.id,
            message="I can redesign your site.", status="accepted",
            created_at=now - timedelta(days=2),
        )
        db.session.add(disputed_offer)
        print(f"  Disputed task: #{disputed_req.id} (for arbitration hall demo)")

        db.session.commit()
        print("\nDemo data seeded successfully!")
        print("=" * 50)
        print("Test accounts (password: test123):")
        print("  alice, bob, charlie, diana, eve")
        print("  expert1, expert2, expert3 (Gold tier, rep=85)")
        print("Admin account: admin / admin123")
        print("=" * 50)
        print("\nNew Web3 features:")
        print("  - SBT: alice/bob/charlie have wallets, experts have Gold tier")
        print("  - Arbitration: disputed task #%d ready for voting" % disputed_req.id)
        print("  - Escrow: create paid tasks to test fund locking")


if __name__ == "__main__":
    seed()
