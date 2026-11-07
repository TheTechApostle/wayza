import hashlib, hmac, os, time, jwt
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import SECRET_KEY
from .database import get_db
from .models import User, now

def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()
def verify_password(pw: str, stored: str) -> bool:
    try: salt, h = stored.split("$")
    except ValueError: return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex(), h)
def make_token(uid: int, days=7) -> str:
    return jwt.encode({"sub": str(uid), "exp": now() + timedelta(days=days)}, SECRET_KEY, algorithm="HS256")
def decode_token(t: str):
    try: return int(jwt.decode(t, SECRET_KEY, algorithms=["HS256"])["sub"])
    except Exception: return None

_bearer = HTTPBearer(auto_error=False)
def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    uid = decode_token(cred.credentials) if cred else None
    u = db.get(User, uid) if uid else None
    if not u or not u.is_active: raise HTTPException(401, "Please log in")
    return u
def require(*roles):
    def dep(u: User = Depends(current_user)):
        if u.role not in roles: raise HTTPException(403, "Not allowed for your role")
        return u
    return dep

_hits: dict = {}
def rate_limit(request: Request, limit=10, window=60):
    ip = request.client.host if request.client else "?"
    t = time.time(); q = [x for x in _hits.get(ip, []) if t - x < window]
    if len(q) >= limit: raise HTTPException(429, "Too many attempts, try again shortly")
    q.append(t); _hits[ip] = q
