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
