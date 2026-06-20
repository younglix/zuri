# ⬡ ZURI Crypto Wallet v3

A full-stack crypto investment wallet with PostgreSQL, live prices, and real security.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Make sure PostgreSQL is running with:
#    Database: zuricrypto
#    User:     Postgres
#    Password: Isaac224488

# 3. Run (DB tables auto-created on first start)
python app.py
```

Open http://localhost:5000

## Default Admin
- Email: admin@zuri.app
- Password: admin1234
- URL: http://localhost:5000/admin

## Deploying to Railway
1. Push this repo to GitHub and create a new Railway project from it.
2. Attach a PostgreSQL plugin — Railway injects `DATABASE_URL` into the web service automatically.
3. In the web service's Variables tab, set `SECRET_KEY` to a fixed random value (`python -c "import secrets; print(secrets.token_hex(32))"`). Without this, sessions and CSRF tokens reset on every redeploy.
4. Railway detects the `Procfile` and runs `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`. Keep it at 1 worker — the mining engine scheduler runs in-process, and multiple workers would tick it multiple times in parallel.
5. Existing tables/data are untouched — `db.create_all()` only creates tables that don't already exist.

## Features
- Landing page (Spaceship-style UI)
- Auth: Sign up, Login, Forgot/Reset password
- Bottom navigation (mobile-first)
- Dashboard: exchange-style crypto rows with live prices
- Deposit: 10 coins with QR + wallet address
- Withdraw: crypto-only with network selector
- Swap: live conversion calculator
- Mining Plans: 5 tiers, pay in any coin
- Transaction History: filterable
- Profile: edit info, change password, balances
- Admin Panel: users, transactions, plans, settings

## Security
- PBKDF2:SHA256 password hashing (600,000 iterations)
- CSRF tokens on every POST form
- HTTP security headers (X-Frame-Options, CSP, etc.)
- Session HTTPONLY + SameSite cookies
- SQL injection prevention via SQLAlchemy ORM
- Input sanitization + HTML tag stripping
- Path traversal / injection detection
