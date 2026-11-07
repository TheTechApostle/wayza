import asyncio, hashlib, hmac, json, math, secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal
import anyio, httpx
from anyio import from_thread
from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
import mimetypes, uuid, shutil
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from . import config
from .database import get_db, SessionLocal, engine, Base
from .models import *
from .security import *
from .seed import seed

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# ---------- realtime ----------
class Hub:
    def __init__(self): self.conns: dict[int, set[WebSocket]] = {}
    async def push(self, uid: int, data: dict):
        for ws in list(self.conns.get(uid, [])):
            try: await ws.send_json(data)
            except Exception: self.conns[uid].discard(ws)
hub = Hub()
def push(uid, data):
    try: from_thread.run(hub.push, uid, data)
    except Exception: pass   # not in a worker thread / no listeners
def notify(db, uid, text):
    n = Notification(user_id=uid, text=text[:300]); db.add(n); db.commit()
    push(uid, {"type": "notification", "text": n.text})

def sweep():
    """Hourly: warn 3 days before expiry, notify when lapsed (visibility is computed from expiry date)."""
    with SessionLocal() as db:
        t = now()
        for b in db.query(Business).filter(Business.subscription_expires.isnot(None)).all():
            e = b.subscription_expires
            if e <= t and b.notice_state != f"lapsed:{e.date()}":
                b.notice_state = f"lapsed:{e.date()}"; notify(db, b.owner_id, f"Your subscription for {b.name} has expired. Renew to stay visible.")
            elif t < e <= t + timedelta(days=3) and b.notice_state != f"warn:{e.date()}":
                b.notice_state = f"warn:{e.date()}"; notify(db, b.owner_id, f"Your subscription for {b.name} expires on {e.date()}.")
        db.commit()

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
        if not db.query(SubscriptionPlan).first():
            db.add_all([
                SubscriptionPlan(code="starter", name="Starter", description="Basic business listing", price_kobo=500000, duration_days=30, promo_days=0, is_active=True),
                SubscriptionPlan(code="growth", name="Growth", description="Enhanced listing and promotion", price_kobo=1200000, duration_days=30, promo_days=30, is_active=True),
            ])
            db.commit()
    async def loop():
        while True:
            await anyio.to_thread.run_sync(sweep); await asyncio.sleep(3600)
    task = asyncio.create_task(loop())
    yield
    task.cancel()

app = FastAPI(title="WAYZA", lifespan=lifespan)
if config.ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

# ---------- helpers ----------
def km(a, b, c, d):
    R = math.pi / 180; x = (d - b) * R * math.cos((a + c) / 2 * R); y = (c - a) * R
    return math.hypot(x, y) * 6371
def udict(u): return dict(id=u.id, name=u.name, email=u.email, phone=u.phone, role=u.role, is_active=u.is_active)
def sdict(s): return dict(id=s.id, name=s.name, lat=s.lat, lon=s.lon, zone=s.zone, approved=s.approved)
def active(b): return bool(b.subscription_expires and b.subscription_expires > now()) and not b.suspended
def bdict(b, db, full=False):
    avg, n = db.query(func.avg(Review.rating), func.count(Review.id)).filter(Review.business_id == b.id).one()
    d = dict(id=b.id, owner_id=b.owner_id, name=b.name, description=b.description, category=b.category, phone=b.phone,
             verified=b.verified, suspended=b.suspended, stop=sdict(b.stop) if b.stop else None,
             rating=round(float(avg), 1) if avg else None, review_count=n,
             promoted=bool(b.promoted_until and b.promoted_until > now()), subscribed=active(b),
             subscription_expires=b.subscription_expires.isoformat() if b.subscription_expires else None)
    d["media"] = [dict(id=x.id, file_name=x.file_name, file_url=x.file_url, media_type=x.media_type, caption=x.caption)
                  for x in db.query(BusinessMedia).filter_by(business_id=b.id).order_by(BusinessMedia.id.desc()).all()]
    if full:
        d["products"] = [pdict(p) for p in b.products if p.active]
        d["reviews"] = [dict(id=r.id, user=r.user.name, rating=r.rating, comment=r.comment, at=r.created_at.isoformat())
                        for r in db.query(Review).filter_by(business_id=b.id).order_by(Review.id.desc()).limit(50)]
    return d
def pdict(p): return dict(id=p.id, business_id=p.business_id, name=p.name, description=p.description, price=p.price, image_url=p.image_url)
def rdict(r, full=True):
    d = dict(id=r.id, code=r.code, name=r.name, base_fare=r.base_fare, per_stop_fare=r.per_stop_fare, active=r.active, stop_count=len(r.stops))
    if full: d["stops"] = [dict(sdict(rs.stop), seq=rs.seq) for rs in r.stops]
    return d
def own_business(db, bid, u):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "Business not found")
    if b.owner_id != u.id and u.role != "admin": raise HTTPException(403, "Not your business")
    return b

# ---------- auth ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120); email: str = Field(pattern=EMAIL, max_length=255)
    password: str = Field(min_length=8, max_length=128); phone: str = Field("", max_length=32)
    role: Literal["passenger", "business"] = "passenger"
class LoginIn(BaseModel): email: str; password: str
class ProfileIn(BaseModel): name: str | None = Field(None, min_length=2, max_length=120); phone: str | None = Field(None, max_length=32)

@app.post("/api/auth/register", status_code=201)
def register(d: RegisterIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(request)
    if db.query(User).filter_by(email=d.email.lower()).first(): raise HTTPException(409, "Email already registered")
    u = User(email=d.email.lower(), name=d.name, phone=d.phone, role=d.role, password_hash=hash_password(d.password))
    db.add(u); db.commit()
    return {"token": make_token(u.id), "user": udict(u)}
@app.post("/api/auth/login")
def login(d: LoginIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(request)
    u = db.query(User).filter_by(email=d.email.lower()).first()
    if not u or not verify_password(d.password, u.password_hash) or not u.is_active: raise HTTPException(401, "Wrong email or password")
    return {"token": make_token(u.id), "user": udict(u)}
@app.get("/api/me")
def me(u: User = Depends(current_user)): return udict(u)
@app.patch("/api/me")
def update_me(d: ProfileIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    for k, v in d.model_dump(exclude_none=True).items(): setattr(u, k, v)
    db.commit(); return udict(u)

# ---------- stops & routes ----------
class StopIn(BaseModel): name: str = Field(min_length=2, max_length=120); lat: float = Field(ge=-90, le=90); lon: float = Field(ge=-180, le=180); zone: str = Field("", max_length=80)
@app.get("/api/stops")
def stops(q: str = "", db: Session = Depends(get_db)):
    qs = db.query(Stop).filter(Stop.approved.is_(True))
    if q: qs = qs.filter(or_(Stop.name.ilike(f"%{q}%"), Stop.zone.ilike(f"%{q}%")))
    return [sdict(s) for s in qs.order_by(Stop.name).limit(500)]
@app.post("/api/stops", status_code=201)
def add_stop(d: StopIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = Stop(**d.model_dump(), approved=(u.role == "admin"), added_by=u.id); db.add(s); db.commit(); return sdict(s)
@app.get("/api/routes")
def routes(q: str = "", db: Session = Depends(get_db)):
    qs = db.query(Route).filter(Route.active.is_(True))
    if q: qs = qs.filter(Route.name.ilike(f"%{q}%"))
    return [rdict(r) for r in qs.order_by(Route.name)]
@app.get("/api/routes/{rid}")
def route(rid: int, db: Session = Depends(get_db)):
    r = db.get(Route, rid)
    if not r: raise HTTPException(404, "Route not found")
    return rdict(r)
@app.get("/api/routes/{rid}/fare")
def fare(rid: int, from_stop: int, to_stop: int, db: Session = Depends(get_db)):
    r = db.get(Route, rid)
    if not r: raise HTTPException(404, "Route not found")
    idx = {rs.stop_id: rs.seq for rs in r.stops}
    if from_stop not in idx or to_stop not in idx: raise HTTPException(400, "Both stops must be on this route")
    n = abs(idx[to_stop] - idx[from_stop])
    return dict(stops_between=max(n - 1, 0), stops_travelled=n, estimated_fare=r.base_fare + r.per_stop_fare * n, currency="NGN", estimate=True)

# ---------- businesses & marketplace ----------
class BizIn(BaseModel):
    name: str = Field(min_length=2, max_length=160); description: str = Field("", max_length=2000)
    category: str = Field("General", max_length=60); phone: str = Field("", max_length=32); stop_id: int | None = None
class BizPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160); description: str | None = Field(None, max_length=2000)
    category: str | None = Field(None, max_length=60); phone: str | None = Field(None, max_length=32); stop_id: int | None = None
class ProdIn(BaseModel):
    name: str = Field(min_length=1, max_length=160); description: str = Field("", max_length=2000)
    price: int = Field(0, ge=0, le=100_000_000); image_url: str = Field("", max_length=500, pattern=r"^(https?://.*)?$"); active: bool = True
class ProdPatch(BaseModel):
    name: str | None = None; description: str | None = None; price: int | None = Field(None, ge=0); image_url: str | None = Field(None, pattern=r"^(https?://.*)?$"); active: bool | None = None

@app.get("/api/businesses")
def marketplace(q: str = "", category: str = "", stop_id: int | None = None, lat: float | None = None, lon: float | None = None,
                radius_km: float | None = None, db: Session = Depends(get_db)):
    qs = db.query(Business).filter(Business.subscription_expires > now(), Business.suspended.is_(False))
    if category: qs = qs.filter(Business.category.ilike(category))
    if stop_id: qs = qs.filter(Business.stop_id == stop_id)
    if q:
        ids = [x[0] for x in db.query(Product.business_id).filter(Product.active.is_(True), Product.name.ilike(f"%{q}%"))]
        qs = qs.filter(or_(Business.name.ilike(f"%{q}%"), Business.description.ilike(f"%{q}%"), Business.id.in_(ids)))
    out = []
    for b in qs.limit(300):
        d = bdict(b, db)
        d["products_preview"] = [pdict(x) for x in db.query(Product).filter_by(business_id=b.id, active=True).order_by(Product.id.desc()).limit(2).all()]
        d["distance_km"] = round(km(lat, lon, b.stop.lat, b.stop.lon), 2) if lat is not None and lon is not None and b.stop else None
        if radius_km and (d["distance_km"] is None or d["distance_km"] > radius_km): continue
        out.append(d)
    out.sort(key=lambda d: (not d["promoted"], d["distance_km"] if d["distance_km"] is not None else 1e9, not d["verified"], -(d["rating"] or 0)))
    return out
@app.get("/api/categories")
def categories(db: Session = Depends(get_db)):
    return sorted({c for (c,) in db.query(Business.category).filter(Business.subscription_expires > now()).distinct()})
@app.get("/api/businesses/{bid}")
def business(bid: int, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b or not active(b): raise HTTPException(404, "Business not found")
    return bdict(b, db, full=True)
@app.get("/api/my/businesses")
def my_businesses(u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    return [bdict(b, db, full=True) for b in db.query(Business).filter_by(owner_id=u.id)]
@app.post("/api/businesses", status_code=201)
def create_business(d: BizIn, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    if d.stop_id and not db.get(Stop, d.stop_id): raise HTTPException(400, "Unknown bus stop")
    b = Business(owner_id=u.id, **d.model_dump()); db.add(b); db.commit(); return bdict(b, db, full=True)
@app.patch("/api/businesses/{bid}")
def edit_business(bid: int, d: BizPatch, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    b = own_business(db, bid, u)
    for k, v in d.model_dump(exclude_unset=True).items(): setattr(b, k, v)
    db.commit(); return bdict(b, db, full=True)
@app.post("/api/businesses/{bid}/products", status_code=201)
def add_product(bid: int, d: ProdIn, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    own_business(db, bid, u); p = Product(business_id=bid, **d.model_dump()); db.add(p); db.commit(); return pdict(p)
@app.patch("/api/products/{pid}")
def edit_product(pid: int, d: ProdPatch, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p: raise HTTPException(404, "Product not found")
    own_business(db, p.business_id, u)
    for k, v in d.model_dump(exclude_unset=True).items():
        if v is not None: setattr(p, k, v)
    db.commit(); return pdict(p)
@app.delete("/api/products/{pid}", status_code=204)
def del_product(pid: int, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p: raise HTTPException(404, "Product not found")
    own_business(db, p.business_id, u); db.delete(p); db.commit()

# ---------- reviews & favourites ----------
class ReviewIn(BaseModel): rating: int = Field(ge=1, le=5); comment: str = Field("", max_length=1000)
@app.post("/api/businesses/{bid}/reviews", status_code=201)
def review(bid: int, d: ReviewIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "Business not found")
    if b.owner_id == u.id: raise HTTPException(400, "You cannot review your own business")
    r = db.query(Review).filter_by(business_id=bid, user_id=u.id).first()
    if r: r.rating, r.comment = d.rating, d.comment
    else: db.add(Review(business_id=bid, user_id=u.id, rating=d.rating, comment=d.comment))
    db.commit(); notify(db, b.owner_id, f"{u.name} rated {b.name} {d.rating}/5")
    return bdict(b, db, full=True)
@app.get("/api/favourites")
def favourites(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [bdict(f_b, db) for f_b in db.query(Business).join(Favourite, Favourite.business_id == Business.id).filter(Favourite.user_id == u.id)]
@app.post("/api/favourites/{bid}", status_code=201)
def fav(bid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Business, bid): raise HTTPException(404, "Business not found")
    if not db.query(Favourite).filter_by(user_id=u.id, business_id=bid).first(): db.add(Favourite(user_id=u.id, business_id=bid)); db.commit()
    return {"ok": True}
@app.delete("/api/favourites/{bid}", status_code=204)
def unfav(bid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Favourite).filter_by(user_id=u.id, business_id=bid).delete(); db.commit()

# ---------- messaging & notifications ----------
class MsgIn(BaseModel): to_user_id: int; body: str = Field(min_length=1, max_length=2000); business_id: int | None = None
def mdict(m): return dict(id=m.id, sender_id=m.sender_id, receiver_id=m.receiver_id, business_id=m.business_id, body=m.body, at=m.created_at.isoformat())
@app.post("/api/messages", status_code=201)
def send(d: MsgIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    to = db.get(User, d.to_user_id)
    if not to or to.id == u.id: raise HTTPException(400, "Invalid recipient")
    m = Message(sender_id=u.id, receiver_id=to.id, business_id=d.business_id, body=d.body); db.add(m); db.commit()
    push(to.id, {"type": "message", "message": mdict(m), "from_name": u.name})
    return mdict(m)
@app.get("/api/messages/threads")
def threads(u: User = Depends(current_user), db: Session = Depends(get_db)):
    ms = db.query(Message).filter(or_(Message.sender_id == u.id, Message.receiver_id == u.id)).order_by(Message.id.desc()).all()
    seen, out = set(), []
    for m in ms:
        o = m.receiver_id if m.sender_id == u.id else m.sender_id
        if o in seen: continue
        seen.add(o); ou = db.get(User, o)
        out.append(dict(user_id=o, name=ou.name, last=m.body[:80], at=m.created_at.isoformat(),
                        unread=db.query(Message).filter_by(sender_id=o, receiver_id=u.id, is_read=False).count()))
    return out
@app.get("/api/messages/{other_id}")
def conversation(other_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    ms = db.query(Message).filter(or_((Message.sender_id == u.id) & (Message.receiver_id == other_id),
                                      (Message.sender_id == other_id) & (Message.receiver_id == u.id))).order_by(Message.id).limit(500).all()
    for m in ms:
        if m.receiver_id == u.id: m.is_read = True
    db.commit(); return [mdict(m) for m in ms]
@app.get("/api/notifications")
def notifications(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [dict(id=n.id, text=n.text, read=n.is_read, at=n.created_at.isoformat())
            for n in db.query(Notification).filter_by(user_id=u.id).order_by(Notification.id.desc()).limit(50)]
@app.post("/api/notifications/read")
def read_notifications(u: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=u.id, is_read=False).update({"is_read": True}); db.commit(); return {"ok": True}
@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    uid = decode_token(token)
    if not uid: await websocket.close(code=4401); return
    await websocket.accept(); hub.conns.setdefault(uid, set()).add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: pass
    finally: hub.conns.get(uid, set()).discard(websocket)

# ---------- Paystack ----------
PS = "https://api.paystack.co"
class PayIn(BaseModel): business_id: int; plan: str = Field(min_length=2, max_length=40)
@app.get("/api/plans")
def plans(db: Session = Depends(get_db)):
    rows = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active.is_(True)).order_by(SubscriptionPlan.price_kobo).all()
    return [dict(id=p.code, name=p.name, description=p.description, price_ngn=p.price_kobo // 100,
                 days=p.duration_days, promo_days=p.promo_days) for p in rows]
@app.post("/api/payments/initialize")
def pay_init(d: PayIn, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    if not config.PAYSTACK_SECRET: raise HTTPException(503, "Payments are not configured")
    b = own_business(db, d.business_id, u)
    plan_row = db.query(SubscriptionPlan).filter_by(code=d.plan, is_active=True).first()
    if not plan_row: raise HTTPException(404, "Subscription plan not found or inactive")
    plan = {"kobo": plan_row.price_kobo, "days": plan_row.duration_days, "promo_days": plan_row.promo_days}
    ref = "WAYZA-" + secrets.token_hex(10)
    try:
        r = httpx.post(f"{PS}/transaction/initialize", headers={"Authorization": f"Bearer {config.PAYSTACK_SECRET}"}, timeout=20,
                       json=dict(email=u.email, amount=plan["kobo"], reference=ref, currency="NGN",
                                 callback_url=f"{config.APP_URL}/?pay_ref={ref}", metadata=dict(business_id=b.id, plan=d.plan)))
        data = r.json()
    except Exception: raise HTTPException(502, "Could not reach Paystack")
    if r.status_code != 200 or not data.get("status"): raise HTTPException(502, data.get("message", "Paystack error"))
    db.add(Payment(user_id=u.id, business_id=b.id, reference=ref, plan=d.plan, amount_kobo=plan["kobo"])); db.commit()
    return dict(reference=ref, authorization_url=data["data"]["authorization_url"])
def fulfil(db, p: Payment):
    if p.status == "success": return
    plan_row = db.query(SubscriptionPlan).filter_by(code=p.plan).first()
    plan = ({"days": plan_row.duration_days, "promo_days": plan_row.promo_days} if plan_row
            else config.PLANS.get(p.plan, {"days": 30, "promo_days": 0}))
    b = db.get(Business, p.business_id); t = now()
    base = b.subscription_expires if b.subscription_expires and b.subscription_expires > t else t
    b.subscription_expires = base + timedelta(days=plan["days"])
    if plan["promo_days"]:
        pb = b.promoted_until if b.promoted_until and b.promoted_until > t else t
        b.promoted_until = pb + timedelta(days=plan["promo_days"])
    p.status = "success"; db.commit()
    notify(db, p.user_id, f"Payment received. {b.name} is live until {b.subscription_expires.date()}.")
@app.get("/api/payments/verify/{reference}")
def pay_verify(reference: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.query(Payment).filter_by(reference=reference).first()
    if not p or (p.user_id != u.id and u.role != "admin"): raise HTTPException(404, "Payment not found")
    if p.status != "success":
        try: data = httpx.get(f"{PS}/transaction/verify/{reference}", headers={"Authorization": f"Bearer {config.PAYSTACK_SECRET}"}, timeout=20).json()
        except Exception: raise HTTPException(502, "Could not reach Paystack")
        d = data.get("data") or {}
        if d.get("status") == "success" and d.get("amount") == p.amount_kobo: fulfil(db, p)
        elif d.get("status") in ("failed", "abandoned"): p.status = "failed"; db.commit()
    return dict(reference=reference, status=p.status)
@app.post("/api/paystack/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    sig = hmac.new(config.PAYSTACK_SECRET.encode(), raw, hashlib.sha512).hexdigest() if config.PAYSTACK_SECRET else ""
    if not sig or not hmac.compare_digest(sig, request.headers.get("x-paystack-signature", "")): raise HTTPException(401, "Bad signature")
    ev = json.loads(raw)
    if ev.get("event") == "charge.success":
        d = ev["data"]; p = db.query(Payment).filter_by(reference=d.get("reference")).first()
        if p and d.get("amount") == p.amount_kobo: await anyio.to_thread.run_sync(fulfil, db, p)
    return {"ok": True}
@app.get("/api/my/payments")
def my_payments(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [dict(reference=p.reference, plan=p.plan, amount_ngn=p.amount_kobo // 100, status=p.status, at=p.created_at.isoformat())
            for p in db.query(Payment).filter_by(user_id=u.id).order_by(Payment.id.desc()).limit(50)]

# ---------- admin ----------
adm = Depends(require("admin"))
class AdminUserPatch(BaseModel): is_active: bool | None = None; role: Literal["passenger", "business", "admin"] | None = None
class RouteIn(BaseModel):
    code: str = Field(min_length=2, max_length=20); name: str = Field(min_length=3, max_length=160)
    stop_names: list[str] = Field(min_length=2); base_fare: int = Field(150, ge=0); per_stop_fare: int = Field(40, ge=0)
@app.get("/api/admin/stats")
def stats(u=adm, db: Session = Depends(get_db)):
    c = lambda m, *f: db.query(func.count(m.id)).filter(*f).scalar()
    rev = db.query(func.coalesce(func.sum(Payment.amount_kobo), 0)).filter(Payment.status == "success").scalar() // 100
    return dict(users=c(User), passengers=c(User, User.role == "passenger"), business_owners=c(User, User.role == "business"),
                businesses=c(Business), active_subscriptions=c(Business, Business.subscription_expires > now()),
                unverified=c(Business, Business.verified.is_(False)), stops=c(Stop), pending_stops=c(Stop, Stop.approved.is_(False)),
                routes=c(Route), reviews=c(Review), messages=c(Message), revenue_ngn=rev)
@app.get("/api/admin/users")
def a_users(q: str = "", u=adm, db: Session = Depends(get_db)):
    qs = db.query(User)
    if q: qs = qs.filter(or_(User.email.ilike(f"%{q}%"), User.name.ilike(f"%{q}%")))
    return [udict(x) for x in qs.order_by(User.id.desc()).limit(200)]
@app.patch("/api/admin/users/{uid}")
def a_user(uid: int, d: AdminUserPatch, u=adm, db: Session = Depends(get_db)):
    t = db.get(User, uid)
    if not t: raise HTTPException(404, "User not found")
    if t.id == u.id: raise HTTPException(400, "You cannot change your own account here")
    for k, v in d.model_dump(exclude_none=True).items(): setattr(t, k, v)
    db.commit(); return udict(t)
@app.get("/api/admin/businesses")
def a_biz(u=adm, db: Session = Depends(get_db)): return [bdict(b, db) for b in db.query(Business).order_by(Business.id.desc()).limit(300)]
@app.post("/api/admin/businesses/{bid}")
def a_biz_set(bid: int, verified: bool | None = None, suspended: bool | None = None, u=adm, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "Business not found")
    if verified is not None: b.verified = verified
    if suspended is not None: b.suspended = suspended
    db.commit()
    if verified: notify(db, b.owner_id, f"{b.name} is now verified.")
    return bdict(b, db)
@app.get("/api/admin/payments")
def a_pay(u=adm, db: Session = Depends(get_db)):
    return [dict(reference=p.reference, business_id=p.business_id, plan=p.plan, amount_ngn=p.amount_kobo // 100, status=p.status, at=p.created_at.isoformat())
            for p in db.query(Payment).order_by(Payment.id.desc()).limit(300)]
@app.get("/api/admin/stops/pending")
def a_pending(u=adm, db: Session = Depends(get_db)): return [sdict(s) for s in db.query(Stop).filter(Stop.approved.is_(False))]
@app.post("/api/admin/stops/{sid}/approve")
def a_approve(sid: int, approve: bool = True, u=adm, db: Session = Depends(get_db)):
    s = db.get(Stop, sid)
    if not s: raise HTTPException(404, "Stop not found")
    if approve: s.approved = True
    else: db.delete(s)
    db.commit(); return {"ok": True}
@app.post("/api/admin/routes", status_code=201)
def a_route(d: RouteIn, u=adm, db: Session = Depends(get_db)):
    if db.query(Route).filter_by(code=d.code).first(): raise HTTPException(409, "Route code exists")
    by = {s.name.lower(): s for s in db.query(Stop).filter(Stop.approved.is_(True))}
    missing = [n for n in d.stop_names if n.lower() not in by]
    if missing: raise HTTPException(400, f"Unknown stops: {', '.join(missing)}")
    r = Route(code=d.code, name=d.name, base_fare=d.base_fare, per_stop_fare=d.per_stop_fare)
    r.stops = [RouteStop(stop_id=by[n.lower()].id, seq=i) for i, n in enumerate(d.stop_names)]
    db.add(r); db.commit(); return rdict(r)
@app.delete("/api/admin/routes/{rid}", status_code=204)
def a_route_del(rid: int, u=adm, db: Session = Depends(get_db)):
    r = db.get(Route, rid)
    if r: db.delete(r); db.commit()


# ---------- WAYZA admin: account, business media and subscription management ----------
class AdminUserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=EMAIL, max_length=255)
    phone: str = Field("", max_length=32)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["passenger", "business", "admin"] = "passenger"

class AdminBusinessCreate(BaseModel):
    owner_id: int
    name: str = Field(min_length=2, max_length=160)
    description: str = ""
    category: str = "General"
    phone: str = ""
    stop_id: int | None = None

class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    price_ngn: int = Field(ge=0)
    duration_days: int = Field(ge=1, le=3660)
    promo_days: int = Field(ge=0, le=3660)
    is_active: bool = True

@app.post("/api/admin/users", status_code=201)
def admin_create_user(d: AdminUserCreate, u=adm, db: Session = Depends(get_db)):
    email = d.email.lower()
    if db.query(User).filter_by(email=email).first(): raise HTTPException(409, "Email already exists")
    x = User(name=d.name, email=email, phone=d.phone, password_hash=hash_password(d.password), role=d.role, is_active=True)
    db.add(x); db.commit(); db.refresh(x)
    return udict(x)

@app.delete("/api/admin/users/{uid}", status_code=204)
def admin_delete_user(uid: int, u=adm, db: Session = Depends(get_db)):
    target = db.get(User, uid)
    if not target: raise HTTPException(404, "User not found")
    if target.id == u.id: raise HTTPException(400, "You cannot delete your own admin account")
    # Remove dependent records explicitly so this works with existing databases too.
    owned = db.query(Business).filter_by(owner_id=uid).all()
    for b in owned:
        shutil.rmtree(Path("uploads/businesses") / str(b.id), ignore_errors=True)
        db.query(BusinessMedia).filter_by(business_id=b.id).delete()
        db.query(Product).filter_by(business_id=b.id).delete()
        db.query(Review).filter_by(business_id=b.id).delete()
        db.query(Favourite).filter_by(business_id=b.id).delete()
        db.query(Payment).filter_by(business_id=b.id).delete()
        db.query(Message).filter_by(business_id=b.id).update({"business_id": None})
        db.delete(b)
    db.query(Message).filter(or_(Message.sender_id == uid, Message.receiver_id == uid)).delete(synchronize_session=False)
    db.query(Notification).filter_by(user_id=uid).delete()
    db.query(Favourite).filter_by(user_id=uid).delete()
    db.query(Review).filter_by(user_id=uid).delete()
    db.query(Payment).filter_by(user_id=uid).delete()
    db.query(Stop).filter_by(added_by=uid).update({"added_by": None})
    db.delete(target); db.commit()

@app.delete("/api/admin/businesses/{bid}", status_code=204)
def admin_delete_business(bid: int, u=adm, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "Business not found")
    shutil.rmtree(Path("uploads/businesses") / str(bid), ignore_errors=True)
    db.query(BusinessMedia).filter_by(business_id=bid).delete()
    db.query(Product).filter_by(business_id=bid).delete()
    db.query(Review).filter_by(business_id=bid).delete()
    db.query(Favourite).filter_by(business_id=bid).delete()
    db.query(Payment).filter_by(business_id=bid).delete()
    db.query(Message).filter_by(business_id=bid).update({"business_id": None})
    db.delete(b); db.commit()

@app.post("/api/admin/businesses", status_code=201)
def admin_create_business(d: AdminBusinessCreate, u=adm, db: Session = Depends(get_db)):
    owner = db.get(User, d.owner_id)
    if not owner: raise HTTPException(404, "Owner account not found")
    if owner.role == "passenger": owner.role = "business"
    b = Business(owner_id=owner.id, name=d.name, description=d.description, category=d.category,
                 phone=d.phone, stop_id=d.stop_id, verified=False, suspended=False)
    db.add(b); db.commit(); db.refresh(b)
    return bdict(b, db, full=True)

@app.post("/api/admin/businesses/{bid}/subscription")
def admin_assign_subscription(bid: int, plan_code: str = Form(...), days_override: int | None = Form(None),
                               u=adm, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "Business not found")
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan: raise HTTPException(404, "Plan not found")
    days = days_override if days_override is not None else plan.duration_days
    if days < 1 or days > 3660: raise HTTPException(400, "Subscription duration must be 1–3660 days")
    base = b.subscription_expires if b.subscription_expires and b.subscription_expires > now() else now()
    b.subscription_expires = base + timedelta(days=days)
    b.notice_state = ""
    if plan.promo_days:
        pb = b.promoted_until if b.promoted_until and b.promoted_until > now() else now()
        b.promoted_until = pb + timedelta(days=plan.promo_days)
    db.commit()
    notify(db, b.owner_id, f"WAYZA admin activated {plan.name} for {days} days.")
    return bdict(b, db, full=True)

@app.get("/api/admin/plans")
def admin_plans(u=adm, db: Session = Depends(get_db)):
    return [dict(id=p.id, code=p.code, name=p.name, description=p.description, price_ngn=p.price_kobo//100,
                 duration_days=p.duration_days, promo_days=p.promo_days, is_active=p.is_active)
            for p in db.query(SubscriptionPlan).order_by(SubscriptionPlan.id).all()]

@app.post("/api/admin/plans", status_code=201)
def admin_create_plan(d: PlanIn, u=adm, db: Session = Depends(get_db)):
    if db.query(SubscriptionPlan).filter_by(code=d.code).first(): raise HTTPException(409, "Plan code already exists")
    p = SubscriptionPlan(code=d.code, name=d.name, description=d.description, price_kobo=d.price_ngn*100,
                         duration_days=d.duration_days, promo_days=d.promo_days, is_active=d.is_active)
    db.add(p); db.commit(); db.refresh(p)
    return {"id":p.id,"code":p.code,"name":p.name,"description":p.description,"price_ngn":p.price_kobo//100,
            "duration_days":p.duration_days,"promo_days":p.promo_days,"is_active":p.is_active}

@app.patch("/api/admin/plans/{pid}")
def admin_update_plan(pid: int, d: PlanIn, u=adm, db: Session = Depends(get_db)):
    p = db.get(SubscriptionPlan, pid)
    if not p: raise HTTPException(404, "Plan not found")
    conflict = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == d.code, SubscriptionPlan.id != pid).first()
    if conflict: raise HTTPException(409, "Plan code already exists")
    for k,v in d.model_dump().items():
        setattr(p, "price_kobo" if k=="price_ngn" else k, v*100 if k=="price_ngn" else v)
    db.commit()
    return {"id":p.id,"code":p.code,"name":p.name,"description":p.description,"price_ngn":p.price_kobo//100,
            "duration_days":p.duration_days,"promo_days":p.promo_days,"is_active":p.is_active}

@app.delete("/api/admin/plans/{pid}", status_code=204)
def admin_delete_plan(pid: int, u=adm, db: Session = Depends(get_db)):
    p = db.get(SubscriptionPlan, pid)
    if not p: raise HTTPException(404, "Plan not found")
    if db.query(Payment).filter_by(plan=p.code).first(): p.is_active = False
    else: db.delete(p)
    db.commit()

@app.post("/api/businesses/{bid}/media", status_code=201)
async def upload_business_media(bid: int, file: UploadFile = File(...), caption: str = Form(""),
                                u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    b = own_business(db, bid, u)
    allowed = {"image/jpeg":"jpg","image/png":"png","image/webp":"webp","application/pdf":"pdf"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed: raise HTTPException(415, "Upload JPG, PNG, WEBP images or PDF flyers/posters only")
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024: raise HTTPException(413, "Maximum upload size is 8 MB")
    ext = allowed[content_type]
    folder = Path("uploads/businesses") / str(bid)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (folder / filename).write_bytes(data)
    media = BusinessMedia(business_id=bid, file_name=file.filename or filename,
                          file_url=f"/uploads/businesses/{bid}/{filename}",
                          media_type="document" if ext=="pdf" else "image", caption=caption[:200])
    db.add(media); db.commit(); db.refresh(media)
    return dict(id=media.id, file_name=media.file_name, file_url=media.file_url, media_type=media.media_type, caption=media.caption)

@app.delete("/api/businesses/{bid}/media/{mid}", status_code=204)
def delete_business_media(bid: int, mid: int, u: User = Depends(require("business", "admin")), db: Session = Depends(get_db)):
    own_business(db, bid, u)
    media = db.query(BusinessMedia).filter_by(id=mid, business_id=bid).first()
    if not media: raise HTTPException(404, "Media not found")
    path = Path(media.file_url.lstrip("/"))
    if path.exists(): path.unlink()
    db.delete(media); db.commit()


@app.get("/api/health")
def health(): return {"ok": True}
Path("uploads/businesses").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/admin")
def admin_page(): return FileResponse("static/admin.html")
@app.get("/")
def index(): return FileResponse("static/index.html")
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

@app.middleware("http")
async def security_headers(request, call_next):
    r = await call_next(request)
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    r.headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=()")
    return r
