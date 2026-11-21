import os, uuid, secrets, hashlib, hmac, re, json
from datetime import datetime, timedelta
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash, abort, g)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ═══════════════════════════════════════════════════════════════
#  APP SETUP
# ═══════════════════════════════════════════════════════════════

def _resolve_db_uri():
    uri = os.environ.get('DATABASE_URL', 'postgresql://postgres:Isaac224488@localhost:5432/zuricrypto')
    # Use the installed psycopg2 driver explicitly. SQLAlchemy 2.x otherwise
    # defaults PostgreSQL URLs to psycopg 3, which is not in requirements.txt.
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql+psycopg2://', 1)
    elif uri.startswith('postgresql://'):
        uri = uri.replace('postgresql://', 'postgresql+psycopg2://', 1)
    return uri

app = Flask(__name__)
app.config.update(
    # Fixed key in production so sessions/CSRF survive restarts and work across workers;
    # falls back to a random key only when SECRET_KEY isn't set (local dev).
    SECRET_KEY                 = os.environ.get('SECRET_KEY', secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI    = _resolve_db_uri(),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    SESSION_COOKIE_HTTPONLY    = True,
    SESSION_COOKIE_SAMESITE    = 'Lax',
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12),
    WTF_CSRF_TIME_LIMIT        = None,
)

db = SQLAlchemy(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# ── CSRF helper ──
def generate_csrf():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(24)
    return session['_csrf']

app.jinja_env.globals['csrf_token'] = generate_csrf

# ═══════════════════════════════════════════════════════════════
#  MODELS
# ═══════════════════════════════════════════════════════════════

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(180), unique=True, nullable=False)
    phone_country = db.Column(db.String(10),  default='+1')
    phone         = db.Column(db.String(30),  default='')
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin      = db.Column(db.Boolean,     default=False)
    is_active     = db.Column(db.Boolean,     default=True)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)
    last_login    = db.Column(db.DateTime,    nullable=True)
    avatar_color  = db.Column(db.String(20),  default='#5b6ef5')

    wallets      = db.relationship('Wallet',      back_populates='user', cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', back_populates='user', cascade='all, delete-orphan')
    active_plans = db.relationship('ActivePlan',  back_populates='user', cascade='all, delete-orphan')

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw, method='pbkdf2:sha256:600000')

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def total_usd_balance(self):
        return sum(w.usd_value for w in self.wallets)


class Wallet(db.Model):
    __tablename__ = 'wallets'
    id      = db.Column(db.Integer,    primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    symbol  = db.Column(db.String(10), nullable=False)
    balance = db.Column(db.Float,      default=0.0)
    user    = db.relationship('User',  back_populates='wallets')

    @property
    def usd_value(self):
        return round(self.balance * CRYPTO_PRICES.get(self.symbol, 1.0), 2)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id          = db.Column(db.String(16),  primary_key=True, default=lambda: str(uuid.uuid4())[:8].upper())
    user_id     = db.Column(db.String(36),  db.ForeignKey('users.id'), nullable=False)
    txn_type    = db.Column(db.String(30),  nullable=False)
    amount      = db.Column(db.Float,       nullable=False)
    currency    = db.Column(db.String(10),  default='USDT')
    to_currency = db.Column(db.String(10),  nullable=True)
    usd_value   = db.Column(db.Float,       default=0.0)
    status      = db.Column(db.String(20),  default='Completed')
    note        = db.Column(db.String(255), default='')
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow)
    user        = db.relationship('User',   back_populates='transactions')


class ActivePlan(db.Model):
    __tablename__ = 'active_plans'
    id         = db.Column(db.Integer,    primary_key=True)
    user_id    = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    plan_id    = db.Column(db.Integer,    nullable=False)
    plan_name  = db.Column(db.String(50))
    invested   = db.Column(db.Float)
    returns    = db.Column(db.Float)
    days       = db.Column(db.Integer)
    progress   = db.Column(db.Integer,    default=0)
    started_at = db.Column(db.DateTime,   default=datetime.utcnow)
    user       = db.relationship('User',  back_populates='active_plans')


class SiteSettings(db.Model):
    __tablename__ = 'site_settings'
    key   = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text,       default='')


class ResetToken(db.Model):
    __tablename__ = 'reset_tokens'
    token      = db.Column(db.String(100), primary_key=True)
    email      = db.Column(db.String(180), nullable=False)
    expires_at = db.Column(db.DateTime,    nullable=False)


# ═══════════════════════════════════════════════════════════════
#  CRYPTO DATA
# ═══════════════════════════════════════════════════════════════

CRYPTO_PRICES = {
    'BTC': 68000.0, 'ETH': 3500.0, 'USDT': 1.0,
    'BNB': 580.0,   'SOL': 175.0,  'XRP':  0.62,
    'DOGE': 0.18,   'TRX': 0.12,   'ADA':  0.45,
    'MATIC': 0.85,
}

CRYPTO_META = {
    'BTC':   {'name': 'Bitcoin',  'color': '#F7931A', 'icon': '₿'},
    'ETH':   {'name': 'Ethereum', 'color': '#627EEA', 'icon': 'Ξ'},
    'USDT':  {'name': 'Tether',   'color': '#26A17B', 'icon': '₮'},
    'BNB':   {'name': 'BNB',      'color': '#F3BA2F', 'icon': '◈'},
    'SOL':   {'name': 'Solana',   'color': '#9945FF', 'icon': '◎'},
    'XRP':   {'name': 'Ripple',   'color': '#00AAE4', 'icon': '✕'},
    'DOGE':  {'name': 'Dogecoin', 'color': '#C2A633', 'icon': 'Ð'},
    'TRX':   {'name': 'TRON',     'color': '#EF0027', 'icon': '◉'},
    'ADA':   {'name': 'Cardano',  'color': '#0033AD', 'icon': '₳'},
    'MATIC': {'name': 'Polygon',  'color': '#8247E5', 'icon': '⬡'},
}

PLANS_DATA = [
    {'id': 1, 'name': 'Starter',  'cost': 100,  'return': 180,  'days': 5,  'roi': 80},
    {'id': 2, 'name': 'Growth',   'cost': 200,  'return': 400,  'days': 7,  'roi': 100},
    {'id': 3, 'name': 'Advanced', 'cost': 500,  'return': 1200, 'days': 10, 'roi': 140},
    {'id': 4, 'name': 'Premium',  'cost': 1000, 'return': 2500, 'days': 14, 'roi': 150},
    {'id': 5, 'name': 'Elite',    'cost': 2000, 'return': 6000, 'days': 20, 'roi': 200},
    {'id': 6, 'name': 'Super',    'cost': 5000, 'return': 12000, 'days': 22, 'roi': 240},
    {'id': 7, 'name': 'Gold',    'cost': 10000, 'return': 26000, 'days': 35, 'roi': 260},
    {'id': 8, 'name': 'Silver',    'cost': 15000, 'return': 45000, 'days': 45, 'roi': 300},
    {'id': 9, 'name': 'Diamond',    'cost': 22000, 'return': 79200, 'days': 60, 'roi': 360},
    {'id': 10, 'name': 'Extreme',    'cost': 30000, 'return': 126000, 'days': 70, 'roi': 420},
]

SUPPORTED_COINS = list(CRYPTO_META.keys())

# ═══════════════════════════════════════════════════════════════
#  SETTINGS HELPERS
# ═══════════════════════════════════════════════════════════════

def get_setting(key, default=''):
    try:
        s = SiteSettings.query.get(key)
        return s.value if s else default
    except Exception:
        return default

def set_setting(key, value):
    s = SiteSettings.query.get(key)
    if s:
        s.value = str(value)
    else:
        db.session.add(SiteSettings(key=key, value=str(value)))
    db.session.commit()

def get_settings_dict():
    def safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    return {
        'maintenance_mode':        get_setting('maintenance_mode',   'false') == 'true',
        'allow_new_registrations': get_setting('allow_registrations', 'true') == 'true',
        'min_deposit':             safe_float(get_setting('min_deposit',  '1.0'), 1.0),
        'min_withdraw':            safe_float(get_setting('min_withdraw',  '0.0001'), 0.0001),
        'announce_msg':            get_setting('announce_msg', ''),
        'promo_enabled':           get_setting('promo_enabled', 'false') == 'true',
        'promo_code':              get_setting('promo_code', '').upper(),
        'promo_bonus':             safe_float(get_setting('promo_bonus', '0.0'), 0.0),
    }

# ═══════════════════════════════════════════════════════════════
#  SECURITY HELPERS
# ═══════════════════════════════════════════════════════════════

def validate_csrf():
    token = request.form.get('_csrf') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('_csrf'):
        abort(403)

def sanitize(s, maxlen=200):
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', '', str(s).strip())
    return s[:maxlen]

def get_wallet_or_create(user_id, symbol):
    w = Wallet.query.filter_by(user_id=user_id, symbol=symbol).first()
    if not w:
        w = Wallet(user_id=user_id, symbol=symbol, balance=0.0)
        db.session.add(w)
        db.session.commit()
    return w

def ensure_wallets(user_id):
    for sym in SUPPORTED_COINS:
        get_wallet_or_create(user_id, sym)

def add_txn(user_id, txn_type, amount, currency='USDT', status='Completed',
            note='', to_currency=None, usd_value=0.0):
    t = Transaction(
        id          = str(uuid.uuid4())[:8].upper(),
        user_id     = user_id,
        txn_type    = txn_type,
        amount      = amount,
        currency    = currency,
        to_currency = to_currency,
        usd_value   = usd_value,
        status      = status,
        note        = sanitize(note, 255),
    )
    db.session.add(t)
    db.session.commit()
    return t

# ═══════════════════════════════════════════════════════════════
#  DECORATORS
# ═══════════════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user_id'):
            flash('Please sign in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        uid = session.get('user_id')
        if not uid:
            return redirect(url_for('login'))
        u = User.query.get(uid)
        if not u or not u.is_admin:
            abort(403)
        return f(*a, **kw)
    return dec

# ═══════════════════════════════════════════════════════════════
#  MIDDLEWARE
# ═══════════════════════════════════════════════════════════════

@app.before_request
def security_check():
    path = request.path
    bad  = ['<script', '../', '..\\', 'etc/passwd', 'SELECT ', 'UNION ']
    for b in bad:
        if b.lower() in path.lower():
            abort(400)

@app.after_request
def add_security_headers(resp):
    resp.headers['X-Content-Type-Options']  = 'nosniff'
    resp.headers['X-Frame-Options']         = 'DENY'
    resp.headers['X-XSS-Protection']        = '1; mode=block'
    resp.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy']      = 'geolocation=(), microphone=(), camera=()'

    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net "
            "https://cdn.tailwindcss.com "
            "https://embed.tawk.to "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "script-src-elem 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net "
            "https://cdn.tailwindcss.com "
            "https://embed.tawk.to "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com "
            "https://cdn.tailwindcss.com "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "font-src 'self' "
            "https://fonts.gstatic.com "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "connect-src 'self' "
            "https://api.coingecko.com "
            "https://*.tawk.to "
            "https://*.tawkcdn.com "
            "wss://*.tawk.to "
            "wss://*.tawkcdn.com; "
        "frame-src "
            "https://embed.tawk.to "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "worker-src 'self' blob: "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "media-src 'self' blob: "
            "https://*.tawk.to "
            "https://*.tawkcdn.com; "
        "img-src 'self' data: https:;"
    )
    return resp

MAINTENANCE_EXEMPT = {
    'landing', 'login', 'signup', 'logout', 'static',
    'forgot_password', 'reset_password', 'update_prices',
    'admin_dashboard', 'admin_settings', 'admin_users',
    'admin_transactions', 'admin_plans', 'admin_toggle_user',
    'admin_adjust_balance', 'admin_reset_user',
    'admin_approve_txn', 'admin_decline_txn',      # ← new routes exempt
}

@app.before_request
def check_maintenance():
    if request.endpoint and request.endpoint not in MAINTENANCE_EXEMPT:
        if get_setting('maintenance_mode', 'false') == 'true':
            uid = session.get('user_id')
            if uid:
                u = User.query.get(uid)
                if u and u.is_admin:
                    return
            return render_template('maintenance.html'), 503

# ═══════════════════════════════════════════════════════════════
#  INIT DB & SEED
# ═══════════════════════════════════════════════════════════════

# Pre-hashed admin password — never stored as plain text
# Hash of: Syjeujamwksjehe68369jsh@ejkejdj
_ADMIN_PW_HASH = generate_password_hash(
    'Syjeujamwksjehe68369jsh@ejkejdj',
    method='pbkdf2:sha256:600000'
)

def init_db():
    db.create_all()
    admin_email = 'anoldlarry302@gmail.com'
    if not User.query.filter_by(email=admin_email).first():
        a = User(
            id=str(uuid.uuid4()), name='ZURI Admin',
            email=admin_email, is_admin=True, is_active=True,
            avatar_color='#ef4444',
        )
        a.password_hash = _ADMIN_PW_HASH   # assign hash directly, never plain text
        db.session.add(a)
        db.session.commit()
        ensure_wallets(a.id)



# ═══════════════════════════════════════════════════════════════
#  MINING ENGINE  — runs every 60 seconds
# ═══════════════════════════════════════════════════════════════

def _settle_if_complete(plan, log_tag='MINER'):
    """Shared completion/payout step (safe to call once progress hits 100)."""
    if plan.progress < 100:
        return
    plan.progress = 100.0
    print(f"[{log_tag}] COMPLETED → User {plan.user_id} earned {plan.returns}")

    # Prevent double payout (critical safety check)
    already_paid = Transaction.query.filter_by(
        user_id=plan.user_id,
        txn_type='Mining Return',
        note=f'{plan.plan_name} plan completed — {plan.returns} USDT credited'
    ).first()

    if not already_paid:
        wallet = get_wallet_or_create(plan.user_id, 'USDT')
        wallet.balance = round(wallet.balance + plan.returns, 8)

        add_txn(
            plan.user_id,
            'Mining Return',
            plan.returns,
            currency='USDT',
            status='Completed',
            usd_value=plan.returns,
            note=f'{plan.plan_name} plan completed — {plan.returns} USDT credited',
        )


def run_mining_engine():
    """
    Called every 60 seconds by APScheduler.
    For every active plan:
      - Progress = 100 even steps spread across the plan's real duration
        (plan.days), computed from real elapsed time since plan.started_at —
        e.g. a 5-day plan advances ~1% every ~72 minutes, a 70-day plan ~1%
        every ~16.8 hours.
      - When progress reaches 100%: credits return once only
    """

    with app.app_context():
        try:
            plans = ActivePlan.query.filter(ActivePlan.progress < 100).all()
            if not plans:
                return

            now = datetime.utcnow()
            for plan in plans:
                total_seconds = plan.days * 86400
                elapsed       = (now - plan.started_at).total_seconds()
                pct           = round(elapsed / total_seconds * 100)
                # never go backwards (clock skew safety)
                plan.progress = min(100, max(plan.progress, pct))

                print(f"[MINER] Plan {plan.id} → {plan.progress}%")
                _settle_if_complete(plan)

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[MiningEngine] Error: {e}')
# ═══════════════════════════════════════════════════════════════
#  LANDING
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def landing():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('landing.html', crypto_meta=CRYPTO_META, plans=PLANS_DATA)

# ═══════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    if get_setting('allow_registrations', 'true') != 'true':
        flash('New registrations are temporarily closed.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        validate_csrf()
        name          = sanitize(request.form.get('name', ''),          120)
        email         = sanitize(request.form.get('email', ''),         180).lower()
        phone_country = sanitize(request.form.get('phone_country', '+1'), 10)
        phone         = sanitize(request.form.get('phone', ''),          30)
        promo_code    = sanitize(request.form.get('promo_code', ''),       50).upper().replace(' ', '')
        pw            = request.form.get('password', '')
        confirm       = request.form.get('confirm', '')

        if not name or not email or not pw:
            flash('All fields are required.', 'error')
            return render_template('auth/signup.html')
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            flash('Invalid email address.', 'error')
            return render_template('auth/signup.html')
        if len(pw) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('auth/signup.html')
        if pw != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/signup.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
            return render_template('auth/signup.html')

        import random
        colors = ['#5b6ef5', '#8b5cf6', '#06b6d4', '#10b981', '#f97316', '#ec4899']
        u = User(
            id=str(uuid.uuid4()), name=name, email=email,
            phone_country=phone_country, phone=phone,
            is_admin=False, is_active=True,
            avatar_color=random.choice(colors),
        )
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        ensure_wallets(u.id)

        welcome_message = f'Welcome to ZURI, {name}!'
        if get_setting('promo_enabled', 'false') == 'true':
            active_code = get_setting('promo_code', '').upper().replace(' ', '')
            try:
                bonus_amount = float(get_setting('promo_bonus', '0.0') or 0.0)
            except Exception:
                bonus_amount = 0.0

            if promo_code and active_code and promo_code == active_code and bonus_amount > 0:
                wallet = get_wallet_or_create(u.id, 'USDT')
                wallet.balance = round(wallet.balance + bonus_amount, 8)
                add_txn(
                    u.id,
                    'Signup Bonus',
                    bonus_amount,
                    currency='USDT',
                    status='Completed',
                    usd_value=bonus_amount,
                    note=f'Promotion code {promo_code} applied — {bonus_amount} USDT bonus',
                )
                welcome_message += f' Promo code applied: {bonus_amount} USDT bonus credited.'

        session.permanent   = True
        session['user_id']  = u.id
        session['user_name']  = u.name
        session['user_email'] = u.email
        session['is_admin']   = False
        flash(welcome_message, 'success')
        return redirect(url_for('dashboard'))

    return render_template('auth/signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        validate_csrf()
        email = sanitize(request.form.get('email', ''), 180).lower()
        pw    = request.form.get('password', '')
        u     = User.query.filter_by(email=email).first()

        if not u or not u.check_password(pw):
            flash('Invalid email or password.', 'error')
            return render_template('auth/login.html')
        if not u.is_active:
            flash('Your account has been suspended. Contact support.', 'error')
            return render_template('auth/login.html')

        u.last_login = datetime.utcnow()
        db.session.commit()
        ensure_wallets(u.id)

        session.permanent     = True
        session['user_id']    = u.id
        session['user_name']  = u.name
        session['user_email'] = u.email
        session['is_admin']   = u.is_admin
        flash(f'Welcome back, {u.name}!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('auth/login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('landing'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        validate_csrf()
        email = sanitize(request.form.get('email', ''), 180).lower()
        u     = User.query.filter_by(email=email).first()
        if u:
            ResetToken.query.filter_by(email=email).delete()
            tok = secrets.token_urlsafe(32)
            db.session.add(ResetToken(
                token=tok, email=email,
                expires_at=datetime.utcnow() + timedelta(hours=1),
            ))
            db.session.commit()
            link = url_for('reset_password', token=tok, _external=True)
            flash(f'[DEMO] Reset link: {link}', 'info')
        else:
            flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('auth/forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    rt = ResetToken.query.get(token)
    if not rt or rt.expires_at < datetime.utcnow():
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        validate_csrf()
        pw      = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if len(pw) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('auth/reset_password.html', token=token)
        if pw != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html', token=token)
        u = User.query.filter_by(email=rt.email).first()
        if u:
            u.set_password(pw)
            db.session.delete(rt)
            db.session.commit()
        flash('Password updated! Please sign in.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/reset_password.html', token=token)

# ═══════════════════════════════════════════════════════════════
#  APP ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    u       = User.query.get(session['user_id'])
    txns    = Transaction.query.filter_by(user_id=u.id).order_by(
              Transaction.created_at.desc()).limit(10).all()
    wallets = Wallet.query.filter_by(user_id=u.id).all()
    plans   = ActivePlan.query.filter_by(user_id=u.id).order_by(
              ActivePlan.started_at.desc()).all()
    ann     = get_setting('announce_msg', '')
    return render_template('dashboard.html',
        user=u, transactions=txns, wallets=wallets,
        active_plans=plans, announce=ann,
        crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES,
    )


@app.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        symbol  = sanitize(request.form.get('currency', 'USDT'), 10).upper()
        amount  = float(request.form.get('amount', 0) or 0)
        min_dep = float(get_setting('min_deposit', '1.0'))

        if symbol not in SUPPORTED_COINS:
            flash('Invalid currency.', 'error')
            return redirect(url_for('deposit'))
        if amount <= 0 or amount < min_dep:
            flash(f'Minimum deposit is {min_dep}.', 'error')
            return redirect(url_for('deposit'))

        price   = CRYPTO_PRICES.get(symbol, 1.0)
        usd_val = round(amount * price, 2)

        # ── CHANGED: do NOT credit balance yet; wait for admin approval ──
        add_txn(u.id, 'Deposit', amount, currency=symbol,
                status='Processing', usd_value=usd_val,
                note='Awaiting admin approval')

        flash(f'Deposit of {amount} {symbol} submitted and is awaiting approval.', 'success')
        return redirect(url_for('dashboard'))

    wallets = Wallet.query.filter_by(user_id=u.id).all()
    return render_template('deposit.html', user=u, wallets=wallets,
                           crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES,
                           coins=SUPPORTED_COINS)


@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        symbol     = sanitize(request.form.get('currency', 'USDT'), 10).upper()
        amount     = float(request.form.get('amount', 0) or 0)
        to_address = sanitize(request.form.get('to_address', ''), 200)
        network    = sanitize(request.form.get('network', ''),      30)
        min_with   = float(get_setting('min_withdraw', '0.0001'))

        if symbol not in SUPPORTED_COINS:
            return jsonify({'success': False, 'error': 'Invalid currency.'})
        if amount < min_with:
            return jsonify({'success': False, 'error': f'Minimum withdrawal is {min_with} {symbol}.'})

        w = get_wallet_or_create(u.id, symbol)
        if amount > w.balance:
            return jsonify({'success': False, 'error': 'Insufficient balance.'})

        # ── Deduct immediately so user cannot double-spend while pending ──
        w.balance = round(w.balance - amount, 8)
        price     = CRYPTO_PRICES.get(symbol, 1.0)
        usd_val   = round(amount * price, 2)
        add_txn(u.id, 'Withdrawal', amount, currency=symbol,
                status='Processing', usd_value=usd_val,
                note=f'To: {to_address[:60]} | Net: {network} | Awaiting admin approval')
        db.session.commit()
        return jsonify({'success': True, 'balance': w.balance})

    wallets = Wallet.query.filter_by(user_id=u.id).all()
    return render_template('withdraw.html', user=u, wallets=wallets,
                           crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES,
                           coins=SUPPORTED_COINS)


@app.route('/swap', methods=['GET', 'POST'])
@login_required
def swap():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        from_sym = sanitize(request.form.get('from_currency', ''), 10).upper()
        to_sym   = sanitize(request.form.get('to_currency',   ''), 10).upper()
        amount   = float(request.form.get('amount', 0) or 0)

        if from_sym not in SUPPORTED_COINS or to_sym not in SUPPORTED_COINS:
            return jsonify({'success': False, 'error': 'Invalid currency.'})
        if from_sym == to_sym:
            return jsonify({'success': False, 'error': 'Cannot swap same currency.'})
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid amount.'})

        from_w = get_wallet_or_create(u.id, from_sym)
        if amount > from_w.balance:
            return jsonify({'success': False, 'error': 'Insufficient balance.'})

        from_price = CRYPTO_PRICES.get(from_sym, 1.0)
        to_price   = CRYPTO_PRICES.get(to_sym,   1.0)
        usd_val    = round(amount * from_price, 2)
        fee_pct    = 0.001
        to_amount  = round((usd_val * (1 - fee_pct)) / to_price, 8)

        from_w.balance = round(from_w.balance - amount, 8)
        to_w = get_wallet_or_create(u.id, to_sym)
        to_w.balance = round(to_w.balance + to_amount, 8)

        add_txn(u.id, 'Swap', amount, currency=from_sym,
                to_currency=to_sym, status='Completed', usd_value=usd_val,
                note=f'Swapped {amount} {from_sym} → {to_amount} {to_sym}')
        db.session.commit()
        return jsonify({'success': True, 'to_amount': to_amount,
                        'from_balance': from_w.balance,
                        'to_balance':   to_w.balance})

    wallets = Wallet.query.filter_by(user_id=u.id).all()
    return render_template('swap.html', user=u, wallets=wallets,
                           crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES,
                           coins=SUPPORTED_COINS)


@app.route('/plans', methods=['GET', 'POST'])
@login_required
def plans():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        plan_id  = int(request.form.get('plan_id', 0))
        currency = sanitize(request.form.get('currency', 'USDT'), 10).upper()
        plan     = next((p for p in PLANS_DATA if p['id'] == plan_id), None)
        if not plan:
            return jsonify({'success': False, 'error': 'Plan not found.'})

        price        = CRYPTO_PRICES.get(currency, 1.0)
        cost_crypto  = round(plan['cost'] / price, 8)
        w = get_wallet_or_create(u.id, currency)
        if w.balance < cost_crypto:
            return jsonify({'success': False, 'error': f'Insufficient {currency} balance.'})

        w.balance = round(w.balance - cost_crypto, 8)
        ap = ActivePlan(
            user_id=u.id, plan_id=plan_id, plan_name=plan['name'],
            invested=plan['cost'], returns=plan['return'],
            days=plan['days'], progress=0,
        )
        db.session.add(ap)
        add_txn(u.id, 'Investment', cost_crypto, currency=currency,
                status='Active', usd_value=plan['cost'],
                note=f'{plan["name"]} Plan')
        db.session.commit()
        return jsonify({'success': True, 'balance': w.balance, 'plan_name': plan['name']})

    wallets = Wallet.query.filter_by(user_id=u.id).all()
    active  = ActivePlan.query.filter_by(user_id=u.id).order_by(
              ActivePlan.started_at.desc()).all()
    return render_template('plans.html', user=u, wallets=wallets,
                           active_plans=active, plans_data=PLANS_DATA,
                           crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES,
                           coins=SUPPORTED_COINS)


@app.route('/transactions')
@login_required
def transactions():
    u    = User.query.get(session['user_id'])
    txns = Transaction.query.filter_by(user_id=u.id).order_by(
           Transaction.created_at.desc()).all()
    return render_template('transactions.html', user=u,
                           transactions=txns, crypto_meta=CRYPTO_META)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        action = request.form.get('action', '')

        if action == 'update_profile':
            name          = sanitize(request.form.get('name', ''),          120)
            phone_country = sanitize(request.form.get('phone_country', '+1'), 10)
            phone         = sanitize(request.form.get('phone', ''),           30)
            if not name:
                flash('Name is required.', 'error')
                return redirect(url_for('profile'))
            u.name          = name
            u.phone_country = phone_country
            u.phone         = phone
            session['user_name'] = name
            db.session.commit()
            flash('Profile updated.', 'success')

        elif action == 'change_password':
            old_pw  = request.form.get('old_password', '')
            new_pw  = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')
            if not u.check_password(old_pw):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('profile'))
            if len(new_pw) < 8:
                flash('New password must be at least 8 characters.', 'error')
                return redirect(url_for('profile'))
            if new_pw != confirm:
                flash('Passwords do not match.', 'error')
                return redirect(url_for('profile'))
            u.set_password(new_pw)
            db.session.commit()
            flash('Password changed successfully.', 'success')

        return redirect(url_for('profile'))

    wallets = Wallet.query.filter_by(user_id=u.id).all()
    txns    = Transaction.query.filter_by(user_id=u.id).order_by(
              Transaction.created_at.desc()).limit(5).all()
    total_deposited = db.session.query(db.func.sum(Transaction.usd_value)).filter_by(
        user_id=u.id, txn_type='Deposit', status='Completed').scalar() or 0
    return render_template('profile.html', user=u, wallets=wallets,
                           recent_txns=txns, total_deposited=total_deposited,
                           crypto_meta=CRYPTO_META, prices=CRYPTO_PRICES)


@app.route('/api/prices', methods=['POST'])
@login_required
def update_prices():
    validate_csrf()
    data = request.get_json(silent=True) or {}
    for sym, price in data.items():
        sym = sym.upper()
        if sym in CRYPTO_PRICES and isinstance(price, (int, float)) and price > 0:
            CRYPTO_PRICES[sym] = float(price)
    return jsonify({'ok': True})


@app.route('/api/convert')
@login_required
def api_convert():
    frm = request.args.get('from', '').upper()
    to  = request.args.get('to',   '').upper()
    amt = float(request.args.get('amount', 1) or 1)
    if frm not in CRYPTO_PRICES or to not in CRYPTO_PRICES:
        return jsonify({'error': 'Unknown currency'})
    result = round(amt * CRYPTO_PRICES[frm] / CRYPTO_PRICES[to], 8)
    return jsonify({'result': result, 'rate': CRYPTO_PRICES[frm] / CRYPTO_PRICES[to]})

# ═══════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    u             = User.query.get(session['user_id'])
    total_users   = User.query.count()
    total_dep     = db.session.query(db.func.sum(Transaction.usd_value)).filter_by(
                        txn_type='Deposit', status='Completed').scalar() or 0
    total_with    = db.session.query(db.func.sum(Transaction.usd_value)).filter_by(
                        txn_type='Withdrawal', status='Completed').scalar() or 0
    active_plans  = ActivePlan.query.count()

    # Count pending items for the badge
    pending_count = Transaction.query.filter_by(status='Processing').filter(
        Transaction.txn_type.in_(['Deposit', 'Withdrawal'])).count()

    recent_txns = (Transaction.query.join(User)
                   .order_by(Transaction.created_at.desc()).limit(20).all())
    all_users   = User.query.order_by(User.created_at.desc()).all()
    settings    = get_settings_dict()

    return render_template('admin/dashboard.html',
        user=u, total_users=total_users,
        total_deposits=total_dep, total_withdrawals=total_with,
        active_plans_count=active_plans, pending_count=pending_count,
        recent_txns=recent_txns, settings=settings,
        all_users=all_users, plans=PLANS_DATA,
    )


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    u     = User.query.get(session['user_id'])
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', user=u, users=users,
                           crypto_meta=CRYPTO_META)


@app.route('/admin/users/<user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def admin_toggle_user(user_id):
    validate_csrf()
    target = User.query.get_or_404(user_id)
    if target.is_admin:
        return jsonify({'success': False, 'error': 'Cannot suspend an admin.'})
    target.is_active = not target.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': target.is_active})


@app.route('/admin/users/<user_id>/adjust', methods=['POST'])
@login_required
@admin_required
def admin_adjust_balance(user_id):
    validate_csrf()
    User.query.get_or_404(user_id)
    symbol  = sanitize(request.form.get('currency', 'USDT'), 10).upper()
    amount  = float(request.form.get('amount', 0) or 0)
    action  = request.form.get('action', 'add')
    w       = get_wallet_or_create(user_id, symbol)
    usd_val = round(amount * CRYPTO_PRICES.get(symbol, 1.0), 2)

    if action == 'add':
        w.balance = round(w.balance + amount, 8)
        add_txn(user_id, 'Admin Credit', amount, currency=symbol,
                status='Completed', usd_value=usd_val)
    else:
        w.balance = max(0, round(w.balance - amount, 8))
        add_txn(user_id, 'Admin Debit', amount, currency=symbol,
                status='Completed', usd_value=usd_val)
    db.session.commit()
    return jsonify({'success': True, 'balance': w.balance})


@app.route('/admin/users/<user_id>/reset', methods=['POST'])
@login_required
@admin_required
def admin_reset_user(user_id):
    validate_csrf()
    User.query.get_or_404(user_id)
    Wallet.query.filter_by(user_id=user_id).update({'balance': 0.0})
    Transaction.query.filter_by(user_id=user_id).delete()
    ActivePlan.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/transactions')
@login_required
@admin_required
def admin_transactions():
    u    = User.query.get(session['user_id'])
    txns = (Transaction.query.join(User)
            .order_by(Transaction.created_at.desc()).all())

    # Pending count for badge highlight
    pending_count = Transaction.query.filter_by(status='Processing').filter(
        Transaction.txn_type.in_(['Deposit', 'Withdrawal'])).count()

    return render_template('admin/transactions.html', user=u,
                           transactions=txns, crypto_meta=CRYPTO_META,
                           pending_count=pending_count)


@app.route('/admin/transactions/<txn_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_txn(txn_id):
    """
    Approve a pending Deposit or Withdrawal.

    Deposit  → credit the amount to the user's wallet, mark Completed.
    Withdrawal → already deducted at request time; just mark Completed.
    """
    validate_csrf()
    t = Transaction.query.get_or_404(txn_id)

    if t.status != 'Processing':
        return jsonify({'success': False, 'error': 'Transaction is not pending.'})
    if t.txn_type not in ('Deposit', 'Withdrawal'):
        return jsonify({'success': False, 'error': 'Only deposits and withdrawals can be approved.'})

    if t.txn_type == 'Deposit':
        # Credit the wallet now that admin has confirmed
        w = get_wallet_or_create(t.user_id, t.currency)
        w.balance = round(w.balance + t.amount, 8)

    # For Withdrawal: balance was already deducted — nothing extra to do.

    t.status = 'Completed'
    t.note   = (t.note or '') + ' | Approved by admin'
    db.session.commit()
    return jsonify({'success': True, 'status': 'Completed'})


@app.route('/admin/transactions/<txn_id>/decline', methods=['POST'])
@login_required
@admin_required
def admin_decline_txn(txn_id):
    """
    Decline a pending Deposit or Withdrawal.

    Deposit    → nothing was credited; just mark Declined.
    Withdrawal → refund the amount back to the user's wallet.
    """
    validate_csrf()
    t = Transaction.query.get_or_404(txn_id)

    if t.status != 'Processing':
        return jsonify({'success': False, 'error': 'Transaction is not pending.'})
    if t.txn_type not in ('Deposit', 'Withdrawal'):
        return jsonify({'success': False, 'error': 'Only deposits and withdrawals can be declined.'})

    if t.txn_type == 'Withdrawal':
        # Refund — balance was deducted when the user requested
        w = get_wallet_or_create(t.user_id, t.currency)
        w.balance = round(w.balance + t.amount, 8)

    # For Deposit: nothing was ever credited, so nothing to reverse.

    t.status = 'Declined'
    t.note   = (t.note or '') + ' | Declined by admin'
    db.session.commit()
    return jsonify({'success': True, 'status': 'Declined'})


@app.route('/admin/plans')
@login_required
@admin_required
def admin_plans():
    u = User.query.get(session['user_id'])
    return render_template('admin/plans.html', user=u, plans=PLANS_DATA)


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    u = User.query.get(session['user_id'])
    if request.method == 'POST':
        validate_csrf()
        set_setting('maintenance_mode',
                    'true' if 'maintenance_mode' in request.form else 'false')
        set_setting('allow_registrations',
                    'true' if 'allow_registrations' in request.form else 'false')
        set_setting('min_deposit',  request.form.get('min_deposit',  '1.0'))
        set_setting('min_withdraw', request.form.get('min_withdraw', '0.0001'))
        set_setting('promo_enabled',
                    'true' if 'promo_enabled' in request.form else 'false')
        set_setting('promo_code', sanitize(request.form.get('promo_code', ''), 50).upper().replace(' ', ''))
        set_setting('promo_bonus', request.form.get('promo_bonus', '0.0') or '0.0')
        set_setting('announce_msg', sanitize(request.form.get('announce_msg', ''), 300))
        flash('Settings saved.', 'success')
        return redirect(url_for('admin_settings'))
    settings = get_settings_dict()
    return render_template('admin/settings.html', user=u, settings=settings)

# ═══════════════════════════════════════════════════════════════
#  ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(400)
def bad_request(e):
    return render_template('errors/400.html'), 400

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500

# ═══════════════════════════════════════════════════════════════
#  SCHEDULER INITIALIZATION (runs on import, not just on __main__)
# ═══════════════════════════════════════════════════════════════

with app.app_context():
    init_db()

# Start the mining engine scheduler (must be outside __main__ for Passenger WSGI)
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    func=run_mining_engine,
    trigger='interval',
    seconds=60,
    id='mining_engine',
    replace_existing=True,
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))

# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
