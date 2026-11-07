import os
from dotenv import load_dotenv
load_dotenv()
_u = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
DATABASE_URL = _u.replace("postgres://", "postgresql+psycopg2://", 1) if _u.startswith("postgres://") else _u
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ALLOWED_ORIGINS = [o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o]
# amounts in kobo (NGN x 100)
PLANS = {
    "basic":   {"name": "Basic - list products",          "kobo": 500_000,   "days": 30, "promo_days": 0},
    "premium": {"name": "Premium - listing + promotion",  "kobo": 1_200_000, "days": 30, "promo_days": 30},
}
