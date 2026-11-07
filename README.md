# WAYZA

A Lagos mobility companion for bus-stop alerts, route discovery and local marketplace services. FastAPI · PostgreSQL · SQLAlchemy 2 · Alembic · Bootstrap 5 · Leaflet/OpenStreetMap · Paystack.

## What's in it
- **Ride**: GPS tracking, pick a route and your destination stop, spoken + vibration alerts ("3 more stops…", "Get ready…", "Get down here"), live map, demo ride. Your original nearest-stop / voice / "where am I" behaviour is preserved.
- **Routes**: 5 starter routes with stop sequences, map view, search, estimated fares.
- **Market**: search by product/shop, category, bus stop or "near me"; shop pages with products, reviews, ratings, favourites, call and in-app chat.
- **Accounts**: passenger, business owner and admin roles (JWT, PBKDF2-hashed passwords, login rate-limiting).
- **Business dashboard**: create shops, list products, subscribe (Paystack). Shops are public only while subscribed; Premium adds a "Promoted" boost.
- **Realtime**: WebSocket messaging and notifications. An hourly job warns before expiry and notifies on lapse.
- **Admin**: stats, users, verify/suspend businesses, payments, approve rider-suggested stops, create/delete routes.

## Local setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
createdb busstop        # or run Postgres in Docker: postgres:16 with user/password/db = busstop
cp .env.example .env    # then edit values
alembic upgrade head    # creates all tables
uvicorn app.main:app --reload
```
Open http://localhost:8000. First start seeds 42 stops and 5 routes, and creates an admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Without `DATABASE_URL` it falls back to a local SQLite file for quick trials.
Phones need **HTTPS** for geolocation and voice (localhost is exempt).

## Paystack
1. Put your secret key in `PAYSTACK_SECRET_KEY` and your public URL in `APP_URL`.
2. Paystack redirects back to `APP_URL/?pay_ref=...` and the app verifies the payment.
3. Set the Paystack webhook (Settings → API) to `APP_URL/api/paystack/webhook`. It is signature-verified, so payments still activate if the user closes the tab.
4. Prices are in `app/config.py` (`PLANS`, in kobo). Amounts are checked against what the server created, and activation is idempotent.

## Tests
`pytest -q` runs against a temporary SQLite DB with Paystack mocked.

## Deploy (Render / Railway / VPS)
- Build: `pip install -r requirements.txt`. Pre-deploy: `alembic upgrade head`.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (a Dockerfile is included).
- Env: `DATABASE_URL`, `SECRET_KEY` (long random), `PAYSTACK_SECRET_KEY`, `APP_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
- Behind nginx/Caddy, terminate HTTPS and proxy WebSocket upgrades on `/ws`.
- With more than one worker, realtime pushes only reach sockets on the same worker; use one worker or add Redis pub/sub.

## Schema changes
`alembic revision --autogenerate -m "change"` then `alembic upgrade head`.

## Known limits
- Route lines are straight between stops; fares are **estimates** (`base + per_stop × stops`). Stop coordinates are approximate starter data, so verify on the ground.
- Alerts need the page open (wake-lock is requested); plain web pages can't track in the background.
- Product images are URLs, not uploads. No email/SMS verification or password reset yet. Rate limiting is in-memory.


## Expanded Lagos starter route catalogue and Material Design interface

The starter seed now includes **36 proposed route corridors** and **92 bus-stop/location records** covering corridors and areas such as Ikorodu, Mile 12, Ketu, Ojota, Maryland, Yaba, CMS, Ikeja, Oshodi, Agege, Abule Egba, Iyana Ipaja, Ikotun, Isolo, Surulere, Apapa, Mile 2, Festac, Ojo, Badagry, Ajah, Lekki, Sangotedo and Epe.

These are **starter planning records, not an official or field-verified Lagos route directory**. Some stop coordinates are approximate. Confirm each stop name, exact boarding point, stop order, operating direction and fare with local operators before publishing routes as authoritative. The sample fare calculation is an estimate and is not a live operator fare.

The seed process is idempotent: when the application starts, it adds missing starter stops and route codes without deleting existing user records. If a route code already exists, the seed does not overwrite that route; manage it through the admin route tools.

The public interface has been restyled with a **Material Design 3-inspired visual system** while retaining the existing FastAPI + HTML/CSS/JavaScript architecture. It uses Material Symbols icons, rounded surfaces, tonal buttons, responsive layouts and updated route cards. This is not a React/MUI migration.


## Free voice navigation

The voice guide uses the browser's built-in Web Speech API. No ElevenLabs account,
subscription, API key, or paid voice service is required. In the voice controls,
choose a female voice with Nigerian English preferred, Nigerian English, British
English, American English, or the device default. The app selects from voices
installed and exposed by the user's browser/operating system.

**Important:** A true Nigerian female voice is only available if the device/browser
has one installed. If it does not, the app automatically falls back to the closest
available English voice. The selected voice is saved in the browser on that device.
For the best free voice selection, try Microsoft Edge on Windows and check Windows
Settings > Time & language > Speech for installed voices.


## Brand

Product name: WAYZA
Tagline: Every Journey, Made Easier.

WAYZA is the user-facing product name. The Python package and project folder
remain named `busstop` to avoid breaking existing imports and deployment commands.


## WAYZA administration and business media

Configure `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` before the first startup.
The startup seed creates the admin user if that email does not already exist.
Sign in at `/admin` using those credentials. Existing database tables are retained;
the app creates the new subscription-plan and business-media tables at startup.

Admins can create, suspend/reactivate, and remove passenger or business accounts;
create, verify, suspend and remove business listings; configure subscription plans
(price, duration, promotion days and active status); and manually activate a plan
for a business. Business owners can upload JPG, PNG, WEBP images and PDF flyers/posters
(maximum 8 MB per file). Uploaded assets are served from `/uploads/` and appear in
the public business detail view. Passengers can browse active subscribed businesses
and open their listings.

**Deployment note:** For production, store uploaded media in durable object storage
or a persistent volume, configure HTTPS, rotate `SECRET_KEY`, use a strong admin
password, and back up the database and uploads. The admin delete operations are
permanent. Do not expose admin credentials in source control.

## Marketplace interface refresh
The passenger marketplace now uses a photo-first storefront layout. Uploaded business images appear directly on the listing cards before a visitor opens the business, with featured/verified markers, bus-stop context, ratings, photo counts and a product preview. Business detail views include a responsive photo and flyer gallery. The public marketplace endpoint includes a small product preview per listing. Font Awesome 6 is used for the primary navigation and refreshed marketplace/admin iconography (loaded from its CDN), with the existing WAYZA typography and green visual system retained.
