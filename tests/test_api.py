import os, hmac, hashlib, json, tempfile
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/t.db"
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_x"; os.environ["ADMIN_EMAIL"] = "a@x.com"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
os.environ["SECRET_KEY"] = "test"
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import security
from app import main
from app.database import Base, engine
Base.metadata.create_all(engine)

@pytest.fixture(scope="module")
def c():
    with TestClient(app) as c: yield c
def reg(c, email, role, name="Test User"):
    security._hits.clear()
    r = c.post("/api/auth/register", json=dict(name=name, email=email, password="password123", role=role)); assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]

def test_seed_and_routes(c):
    assert len(c.get("/api/stops").json()) >= 42
    rs = c.get("/api/routes").json(); assert len(rs) >= 5
    r = next(x for x in rs if x["code"] == "IKR1"); ids = [s["id"] for s in r["stops"]]
    f = c.get(f"/api/routes/{r['id']}/fare", params=dict(from_stop=ids[0], to_stop=ids[-1])).json()
    assert f["stops_between"] == 8 and f["estimated_fare"] == 150 + 40 * 9

def test_auth_roles(c):
    h, u = reg(c, "p@x.com", "passenger")
    assert c.get("/api/me", headers=h).json()["email"] == "p@x.com"
    assert c.post("/api/auth/register", json=dict(name="Dup", email="p@x.com", password="password123")).status_code == 409
    assert c.post("/api/auth/register", json=dict(name="Bad", email="nope", password="password123")).status_code == 422
    assert c.post("/api/auth/register", json=dict(name="Hax", email="h@x.com", password="password123", role="admin")).status_code == 422
    assert c.post("/api/businesses", json=dict(name="Shop"), headers=h).status_code == 403
    assert c.get("/api/admin/stats", headers=h).status_code == 403
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/login", json=dict(email="p@x.com", password="wrong")).status_code == 401

def test_marketplace_payments_messaging(c, monkeypatch):
    hp, p = reg(c, "buyer@x.com", "passenger"); hb, b = reg(c, "seller@x.com", "business")
    stop = c.get("/api/stops", params=dict(q="Yaba")).json()[0]
    biz = c.post("/api/businesses", headers=hb, json=dict(name="Mama Put", category="Food", stop_id=stop["id"], phone="0800")).json()
    c.post(f"/api/businesses/{biz['id']}/products", headers=hb, json=dict(name="Jollof rice", price=1500))
    assert c.get("/api/businesses").json() == []                      # hidden until subscribed
    class R:
        def __init__(s, j, code=200): s._j, s.status_code = j, code
        def json(s): return s._j
    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: R({"status": True, "data": {"authorization_url": "https://paystack/x"}}))
    ini = c.post("/api/payments/initialize", headers=hb, json=dict(business_id=biz["id"], plan="growth")).json()
    assert ini["authorization_url"].startswith("https://")
    assert c.post("/api/payments/initialize", headers=hp, json=dict(business_id=biz["id"], plan="starter")).status_code == 403
    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: R({"data": {"status": "success", "amount": 1_000}}))
    assert c.get(f"/api/payments/verify/{ini['reference']}", headers=hb).json()["status"] == "pending"   # wrong amount rejected
    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: R({"data": {"status": "success", "amount": 1_200_000}}))
    assert c.get(f"/api/payments/verify/{ini['reference']}", headers=hb).json()["status"] == "success"
    c.get(f"/api/payments/verify/{ini['reference']}", headers=hb)                                          # idempotent
    l = c.get("/api/businesses", params=dict(q="jollof")).json(); assert len(l) == 1 and l[0]["promoted"]
    assert c.get("/api/businesses", params=dict(stop_id=stop["id"], category="food")).json()[0]["id"] == biz["id"]
    near = c.get("/api/businesses", params=dict(lat=stop["lat"], lon=stop["lon"], radius_km=1)).json(); assert near[0]["distance_km"] < 0.1
    # webhook
    body = json.dumps({"event": "charge.success", "data": {"reference": "nope", "amount": 1}}).encode()
    good = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()
    assert c.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": "bad"}).status_code == 401
    assert c.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": good}).status_code == 200
    # reviews, favourites
    assert c.post(f"/api/businesses/{biz['id']}/reviews", headers=hp, json=dict(rating=5, comment="Great")).json()["rating"] == 5
    assert c.post(f"/api/businesses/{biz['id']}/reviews", headers=hb, json=dict(rating=5)).status_code == 400
    assert c.post(f"/api/businesses/{biz['id']}/reviews", headers=hp, json=dict(rating=9)).status_code == 422
    c.post(f"/api/favourites/{biz['id']}", headers=hp); assert len(c.get("/api/favourites", headers=hp).json()) == 1
    # ownership
    assert c.post(f"/api/businesses/{biz['id']}/products", headers=hp, json=dict(name="x")).status_code == 403
    # messaging + realtime
    with c.websocket_connect(f"/ws?token={hb['Authorization'][7:]}") as ws:
        c.post("/api/messages", headers=hp, json=dict(to_user_id=b["id"], body="Is it spicy?", business_id=biz["id"]))
        assert ws.receive_json()["type"] == "message"
    th = c.get("/api/messages/threads", headers=hb).json(); assert th[0]["unread"] == 1
    assert c.get(f"/api/messages/{p['id']}", headers=hb).json()[0]["body"] == "Is it spicy?"
    assert any("rated" in n["text"] for n in c.get("/api/notifications", headers=hb).json())
    # websocket rejects bad token
    with pytest.raises(Exception):
        with c.websocket_connect("/ws?token=bad"): pass

def test_admin(c):
    r = c.post("/api/auth/login", json=dict(email="a@x.com", password="AdminPass123")); h = {"Authorization": "Bearer " + r.json()["token"]}
    s = c.get("/api/admin/stats", headers=h).json(); assert s["businesses"] >= 1 and s["revenue_ngn"] == 12000
    bid = c.get("/api/admin/businesses", headers=h).json()[0]["id"]
    assert c.post(f"/api/admin/businesses/{bid}?verified=true", headers=h).json()["verified"]
    assert c.post(f"/api/admin/businesses/{bid}?suspended=true", headers=h).json()["suspended"]
    assert c.get("/api/businesses").json() == []                       # suspended = hidden
    hp, _ = reg(c, "adder@x.com", "passenger")
    sid = c.post("/api/stops", headers=hp, json=dict(name="Test Stop", lat=6.5, lon=3.3)).json()["id"]
    assert all(x["name"] != "Test Stop" for x in c.get("/api/stops").json())
    c.post(f"/api/admin/stops/{sid}/approve", headers=h); assert any(x["name"] == "Test Stop" for x in c.get("/api/stops").json())
    nr = c.post("/api/admin/routes", headers=h, json=dict(code="T1", name="Test route", stop_names=["Yaba", "CMS"])); assert nr.status_code == 201
    assert c.post("/api/admin/routes", headers=h, json=dict(code="T2", name="Bad route", stop_names=["Yaba", "Nowhere"])).status_code == 400
    assert len(c.get("/api/admin/users", headers=h).json()) >= 4 and c.get("/api/admin/payments", headers=h).json()
    main.sweep()
