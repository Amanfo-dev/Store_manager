import calendar
import json
import math
import os
import re
import secrets
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from functools import wraps

from email_validator import EmailNotValidError, validate_email
from flask import (Flask, abort, flash, g, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from fpdf import FPDF
from sqlalchemy import func, text
from werkzeug.security import check_password_hash, generate_password_hash

from models import (Expense, Invoice, Item, PendingSignup, PriceHistory,
                    RolePermission, Sale, User, db)


def database_url():
    """Postgres when DATABASE_URL is set (the live host), SQLite file otherwise."""
    url = os.environ.get("DATABASE_URL", "sqlite:///store.db")
    # Hosts give postgres:// or postgresql://. Name the driver explicitly, because
    # newer SQLAlchemy picks psycopg (v3) for a bare postgresql:// URL, not psycopg2.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


IS_PRODUCTION = bool(os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT")
                     or os.environ.get("PRODUCTION"))
if IS_PRODUCTION:
    # A free host's disk is wiped on every restart, so SQLite there would lose all data.
    for _name in ("SECRET_KEY", "DATABASE_URL"):
        if not os.environ.get(_name):
            raise RuntimeError(f"Set the {_name} environment variable on your host before deploying.")


app = Flask(__name__)
app.config.update(
    APP_NAME="Store Manager",
    CURRENCY="GH₵",          # shown on screen
    CURRENCY_CODE="GHS",     # used in PDF invoices (the PDF font has no ₵)
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SQLALCHEMY_DATABASE_URI=database_url(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
    MAIL_FROM=os.environ.get("MAIL_FROM") or "Store Manager <onboarding@resend.dev>",
    CHECK_EMAIL_DNS=os.environ.get("CHECK_EMAIL_DNS", "1") == "1",
)
db.init_app(app)

ROLES = ("admin", "manager", "employee")
PERMS = {
    "edit_delete": "Edit and delete items",
    "settings": "Open the Settings page",
    "change_privileges": "Change role privileges",
    "add_item": "Add new items",
    "analytics": "View the Analytics tab",
    "change_roles": "Change the roles of other users",
}
DEFAULTS = {
    "manager": {"edit_delete", "settings", "change_privileges", "add_item", "change_roles"},
    "employee": set(),
}


def seed_permissions():
    for role, on in DEFAULTS.items():
        for perm in PERMS:
            if not db.session.get(RolePermission, (role, perm)):
                db.session.add(RolePermission(role=role, perm=perm, enabled=perm in on))
    db.session.commit()


def init_db():
    """Create tables and seed privileges. A Postgres advisory lock makes this safe when
    several workers (or app copies) start at the same moment. It is a transaction-level
    lock, so it also works through a pooled connection such as Neon's."""
    with app.app_context():
        with db.engine.begin() as lock_conn:  # the lock lives as long as this transaction
            if lock_conn.dialect.name == "postgresql":
                lock_conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
            db.create_all()
            seed_permissions()
        # With gunicorn --preload this runs once before workers fork, so drop the
        # connections made here and let each worker open its own.
        db.engine.dispose()


init_db()


# ---------- auth and permissions ----------

PUBLIC = {"login", "signup", "signup_verify", "signup_resend", "health", "static"}


@app.before_request
def load_user():
    g.user = db.session.get(User, session["uid"]) if "uid" in session else None
    if g.user is None and request.endpoint not in PUBLIC:
        session.clear()
        return redirect(url_for("login", next=request.path))


def can(perm):
    user = g.get("user")
    if not user:
        return False
    if user.role == "admin":
        return True
    row = db.session.get(RolePermission, (user.role, perm))
    return bool(row and row.enabled)


def needs(perm):
    def deco(view):
        @wraps(view)
        def wrapper(*a, **k):
            if not can(perm):
                abort(403)
            return view(*a, **k)
        return wrapper
    return deco


def admin_only(view):
    @wraps(view)
    def wrapper(*a, **k):
        if g.user.role != "admin":
            abort(403)
        return view(*a, **k)
    return wrapper


@app.errorhandler(403)
def forbidden(_):
    return render_template(
        "placeholder.html", title="Not allowed",
        text="Your role doesn't have access to this. Ask an admin if you think it should."), 403


@app.context_processor
def inject_globals():
    return {"app_name": app.config["APP_NAME"], "currency": app.config["CURRENCY"], "can": can}


@app.template_filter("money")
def money(value):
    return f"{value:,.2f}"


def clean_email(raw):
    try:
        found = validate_email(raw.strip(), check_deliverability=app.config["CHECK_EMAIL_DNS"], timeout=5)
    except EmailNotValidError as e:
        raise ValueError(f"That email can't be used: {e}")
    return found.normalized.lower()


def make_user(email, first, last, password, role):
    email = clean_email(email)
    first, last = first.strip(), last.strip()
    if not first or not last:
        raise ValueError("Enter a first and last name.")
    if len(password) < 8:
        raise ValueError("The password must be at least 8 characters.")
    if role not in ROLES:
        raise ValueError("Pick a valid role.")
    if User.query.filter_by(email=email).first():
        raise ValueError("An account with that email already exists.")
    user = User(email=email, first_name=first, last_name=last, role=role,
                password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    return user


# ---------- sign-up with an emailed code ----------

RESEND_URL = "https://api.resend.com/emails"
CODE_MINUTES, MAX_CODE_TRIES, RESEND_WAIT = 15, 5, 60


class MailError(Exception):
    pass


def send_email(to, subject, text):
    """Send through Resend's HTTPS API (free hosts block SMTP).
    With no RESEND_API_KEY, local runs print the email to the terminal instead."""
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        if IS_PRODUCTION:
            raise MailError("Email isn't set up on this server yet. Add RESEND_API_KEY on your host.")
        print(f"\n[dev mail, no RESEND_API_KEY] To: {to}\n{subject}\n{text}\n", flush=True)
        return
    payload = json.dumps({
        "from": app.config["MAIL_FROM"],
        "to": [to], "subject": subject, "text": text,
    }).encode()
    req = urllib.request.Request(RESEND_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "User-Agent": "store-manager/1.0"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("message", "")
        except Exception:
            detail = ""
        app.logger.error("Resend refused the email (%s): %s", e.code, detail)
        raise MailError(f"The email service refused to send the code. {detail}".strip())
    except (urllib.error.URLError, OSError):
        raise MailError("Couldn't reach the email service. Try again in a minute.")


def issue_code(pending):
    code = f"{secrets.randbelow(10**6):06d}"
    now = datetime.now()
    pending.code_hash = generate_password_hash(code)
    pending.expires_at = now + timedelta(minutes=CODE_MINUTES)
    pending.sent_at, pending.attempts = now, 0
    return code


def mail_code(email, code):
    send_email(email, "Your Store Manager sign-up code",
               f"Your sign-up code is {code}\n\nIt works for {CODE_MINUTES} minutes. "
               "If you didn't try to create an account, ignore this email.")


CLOSED_MESSAGE = ("Sign-up is only for the shop owner. Staff accounts are created by your admin "
                  "under Account, then Add role users.")


def owner_emails():
    # Forgiving on purpose: addresses may be separated by commas, semicolons or spaces,
    # and stray quotes or <angle brackets> around an address are ignored.
    parts = re.split(r"[,;\s]+", os.environ.get("ADMIN_EMAIL", ""))
    return {p.strip("\"'<>").lower() for p in parts if p.strip("\"'<>")}


def signup_open():
    """Sign-up makes admin accounts only. It is open on a brand-new install, or to
    the owner emails listed in ADMIN_EMAIL (so an owner can always get back in)."""
    return User.query.count() == 0 or bool(owner_emails())


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("index"))
    email = ""
    if request.method == "POST":
        f = request.form
        email = f.get("email", "")
        try:
            if f.get("password") != f.get("confirm"):
                raise ValueError("The two passwords don't match.")
            clean = clean_email(email)
            first, last = f.get("first_name", "").strip(), f.get("last_name", "").strip()
            if not first or not last:
                raise ValueError("Enter a first and last name.")
            if len(f.get("password", "")) < 8:
                raise ValueError("The password must be at least 8 characters.")
            owners = owner_emails()
            if owners and clean not in owners:
                # Visible only in the server logs, so the owner can see what ADMIN_EMAIL was read as.
                app.logger.warning("Sign-up refused for %s. ADMIN_EMAIL currently allows: %s", clean, sorted(owners))
                raise ValueError("Only the owner's email address can create an admin account. "
                                 "Staff accounts are made by your admin under Account, then Add role users. "
                                 "If you are the owner, check that the ADMIN_EMAIL setting on your host is exactly this email.")
            if not signup_open():
                raise ValueError(CLOSED_MESSAGE)
            if User.query.filter_by(email=clean).first():
                raise ValueError("That email already has an account. Log in instead.")
            pending = PendingSignup.query.filter_by(email=clean).first() or PendingSignup(email=clean)
            pending.first_name, pending.last_name = first, last
            pending.password_hash = generate_password_hash(f["password"])
            mail_code(clean, issue_code(pending))
        except (ValueError, MailError) as e:
            db.session.rollback()
            flash(str(e), "error")
        else:
            db.session.add(pending)
            db.session.commit()
            session.clear()
            session["pending_email"] = clean
            return redirect(url_for("signup_verify"))
    return render_template("auth.html", signup=True, email=email, closed=not signup_open())


def current_pending():
    email = session.get("pending_email")
    return PendingSignup.query.filter_by(email=email).first() if email else None


@app.route("/signup/verify", methods=["GET", "POST"])
def signup_verify():
    if g.user:
        return redirect(url_for("index"))
    pending = current_pending()
    if pending is None:
        email = session.get("pending_email")
        if email and User.query.filter_by(email=email).first():
            # Usually a double click on Confirm: the first click already made the account.
            session.pop("pending_email", None)
            flash("Your account is already created. Log in with your email and password.", "success")
            return redirect(url_for("login"))
        flash("Start the sign-up again.", "error")
        return redirect(url_for("signup"))
    if request.method == "POST":
        if pending.expires_at < datetime.now():
            db.session.delete(pending)
            db.session.commit()
            flash("That code expired. Sign up again to get a new one.", "error")
            return redirect(url_for("signup"))
        pending.attempts += 1
        if check_password_hash(pending.code_hash, request.form.get("code", "").strip()):
            if User.query.filter_by(email=pending.email).first() or not signup_open():
                db.session.delete(pending)
                db.session.commit()
                flash("That email already has an account, or sign-up has closed. Try logging in.", "error")
                return redirect(url_for("login"))
            user = User(email=pending.email, first_name=pending.first_name, last_name=pending.last_name,
                        password_hash=pending.password_hash, role="admin")
            db.session.add(user)
            db.session.delete(pending)
            db.session.commit()
            session.clear()
            session["uid"] = user.id
            flash("Email confirmed. Admin account created. Welcome!", "success")
            return redirect(url_for("index"))
        if pending.attempts >= MAX_CODE_TRIES:
            db.session.delete(pending)
            db.session.commit()
            flash("Too many wrong codes. Sign up again to get a new one.", "error")
            return redirect(url_for("signup"))
        left = MAX_CODE_TRIES - pending.attempts
        db.session.commit()
        flash(f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.", "error")
    return render_template("verify.html", email=pending.email,
                           dev_mail=not os.environ.get("RESEND_API_KEY") and not IS_PRODUCTION)


@app.post("/signup/resend")
def signup_resend():
    pending = current_pending()
    if pending is None:
        return redirect(url_for("signup"))
    wait = RESEND_WAIT - (datetime.now() - pending.sent_at).total_seconds()
    if wait > 0:
        flash(f"Wait {int(wait) + 1} seconds before asking for another code.", "error")
    else:
        try:
            mail_code(pending.email, issue_code(pending))
        except MailError as e:
            db.session.rollback()
            flash(str(e), "error")
        else:
            db.session.commit()
            flash("A new code is on its way.", "success")
    return redirect(url_for("signup_verify"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            session.clear()
            session["uid"] = user.id
            flash(f"Signed in as {user.role}.", "success")
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
        flash("Wrong email or password.", "error")
    return render_template("auth.html", signup=False, email=email)


@app.post("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("login"))


@app.after_request
def no_cache_for_signed_in_pages(resp):
    # So the Back button after logging out can't show a cached page.
    if g.get("user"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/health")
def health():
    # Deliberately does not touch the database, so an uptime pinger can keep the app
    # awake without keeping a free database awake too.
    return "ok"


# ---------- helpers ----------

def today_range():
    start = datetime.combine(date.today(), time.min)
    return start, start + timedelta(days=1)


def todays_totals():
    start, end = today_range()
    revenue = db.session.query(
        func.coalesce(func.sum(Sale.quantity * Sale.unit_price), 0)
    ).filter(Sale.sold_at >= start, Sale.sold_at < end).scalar()
    expenses = db.session.query(
        func.coalesce(func.sum(Expense.amount), 0)
    ).filter(Expense.spent_at >= start, Expense.spent_at < end).scalar()
    return {"revenue": revenue, "expenses": expenses, "net": revenue - expenses}


def read_item_form():
    name = request.form.get("name", "").strip()
    try:
        price = float(request.form["price"])
        stock = int(request.form["stock"])
    except (KeyError, ValueError):
        raise ValueError("Price and stock must be numbers.")
    if not name or not math.isfinite(price) or price < 0 or stock < 0:
        raise ValueError("Enter a name, and a price and stock that are not negative.")
    return name, price, stock


def parse_day(text):
    try:
        return datetime.strptime(text or "", "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------- home and items ----------

SORT_OPTIONS = {"name": Item.name.asc(), "stock": Item.stock.asc(), "price": Item.price.asc()}


@app.get("/")
def index():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "name")
    if sort not in SORT_OPTIONS:
        sort = "name"
    query = Item.query
    if q:
        query = query.filter(Item.name.ilike(f"%{q}%"))
    items = query.order_by(SORT_OPTIONS[sort]).all()
    return render_template("index.html", items=items, totals=todays_totals(), q=q, sort=sort)


@app.get("/add")
@needs("add_item")
def add_page():
    return render_template("add.html")


@app.post("/items")
@needs("add_item")
def add_item():
    try:
        name, price, stock = read_item_form()
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("add_page"))
    db.session.add(Item(name=name, price=price, stock=stock))
    db.session.commit()
    flash(f"Added {name}.", "success")
    return redirect(url_for("index"))


@app.post("/items/<int:item_id>/edit")
@needs("edit_delete")
def edit_item(item_id):
    item = db.get_or_404(Item, item_id)
    try:
        name, price, stock = read_item_form()
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("index"))
    if price != item.price:
        db.session.add(PriceHistory(item=item, old_price=item.price, new_price=price))
        # TODO (notifications stage): trigger the price-change alert here.
    item.name, item.price, item.stock = name, price, stock
    db.session.commit()
    flash(f"Updated {name}.", "success")
    return redirect(url_for("index"))


@app.post("/items/<int:item_id>/delete")
@needs("edit_delete")
def delete_item(item_id):
    item = db.get_or_404(Item, item_id)
    name = item.name
    db.session.delete(item)
    db.session.commit()
    flash(f"Deleted {name}.", "success")
    return redirect(url_for("index"))


@app.post("/expenses")
def record_expense():
    description = request.form.get("description", "").strip()
    amount = request.form.get("amount", type=float)
    if not description or amount is None or not math.isfinite(amount) or amount <= 0:
        flash("Enter a description and an amount above 0.", "error")
    else:
        db.session.add(Expense(description=description, amount=amount))
        db.session.commit()
        flash("Expense recorded.", "success")
    return redirect(url_for("index"))


# ---------- cart checkout and invoices ----------

@app.post("/checkout")
def checkout():
    lines = (request.get_json(silent=True) or {}).get("items") or []
    if not lines:
        return jsonify(error="Your cart is empty."), 400
    wanted = defaultdict(int)
    try:
        for line in lines:
            qty = int(line["qty"])
            if qty < 1:
                raise ValueError
            wanted[int(line["id"])] += qty
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Something is wrong with the cart. Refresh and try again."), 400

    # with_for_update() locks these rows on Postgres until we commit, so two checkouts
    # of the last unit can't both succeed. (SQLite ignores it; it writes one at a time.)
    items = {i.id: i for i in Item.query.filter(Item.id.in_(list(wanted))).with_for_update().all()}
    for item_id, qty in wanted.items():
        item = items.get(item_id)
        if item is None:
            return jsonify(error="An item in your cart no longer exists. Remove it and try again."), 400
        if qty > item.stock:
            return jsonify(error=f"Only {item.stock} of {item.name} left in stock."), 400

    invoice = Invoice(cashier=g.user.full_name)
    for item_id, qty in wanted.items():
        item = items[item_id]
        item.stock -= qty
        # Prices come from the database, never from the browser.
        invoice.sales.append(Sale(item=item, item_name=item.name, unit_price=item.price, quantity=qty))
    db.session.add(invoice)
    db.session.commit()
    flash(f"Sale recorded as invoice {invoice.number}.", "success")
    return jsonify(ok=True, invoice=invoice.number)


@app.get("/invoices/<int:invoice_id>/print")
def invoice_print(invoice_id):
    return render_template("invoice.html", inv=db.get_or_404(Invoice, invoice_id))


def latin(text):
    return str(text).encode("latin-1", "replace").decode("latin-1")


@app.get("/invoices/<int:invoice_id>.pdf")
def invoice_pdf(invoice_id):
    inv = db.get_or_404(Invoice, invoice_id)
    code = app.config["CURRENCY_CODE"]
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, latin(app.config["APP_NAME"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, f"Invoice {inv.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, inv.created_at.strftime("%d %b %Y, %H:%M"), new_x="LMARGIN", new_y="NEXT")
    if inv.cashier:
        pdf.cell(0, 6, latin(f"Served by {inv.cashier}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    for w, label, align in ((90, "Item", "L"), (20, "Qty", "R"), (40, f"Price ({code})", "R"), (40, f"Total ({code})", "R")):
        pdf.cell(w, 8, label, border="B", align=align)
    pdf.ln()
    pdf.set_font("Helvetica", "", 11)
    for s in inv.sales:
        pdf.cell(90, 8, latin(s.item_name)[:42])
        pdf.cell(20, 8, str(s.quantity), align="R")
        pdf.cell(40, 8, f"{s.unit_price:,.2f}", align="R")
        pdf.cell(40, 8, f"{s.total:,.2f}", align="R")
        pdf.ln()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(150, 10, "Total", border="T", align="R")
    pdf.cell(40, 10, f"{code} {inv.total:,.2f}", border="T", align="R")
    resp = make_response(bytes(pdf.output()))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename={inv.number}.pdf"
    return resp


# ---------- records ----------

@app.get("/history")
def history():
    changes = PriceHistory.query.order_by(PriceHistory.changed_at.desc()).all()
    return render_template("history.html", changes=changes)


@app.get("/records")
def records():
    a = request.args
    start, end = parse_day(a.get("date_from")), parse_day(a.get("date_to"))
    low, high = a.get("min", type=float), a.get("max", type=float)
    kind = a.get("type", "all")
    rows = []
    if kind in ("all", "invoice"):
        rows += [{"kind": "invoice", "at": i.created_at, "amount": i.total, "inv": i}
                 for i in Invoice.query.all()]
    if kind in ("all", "expense"):
        rows += [{"kind": "expense", "at": e.spent_at, "amount": e.amount, "desc": e.description}
                 for e in Expense.query.all()]
    rows = [r for r in rows
            if (not start or r["at"].date() >= start) and (not end or r["at"].date() <= end)
            and (low is None or r["amount"] >= low) and (high is None or r["amount"] <= high)]
    rows.sort(key=lambda r: r["at"], reverse=True)
    return render_template("records.html", rows=rows, f=a)


# ---------- analytics ----------

@app.get("/analytics")
@needs("analytics")
def analytics():
    today = date.today()
    sales = [(s.sold_at.date(), s.total) for s in Sale.query.all()]
    spend = [(e.spent_at.date(), e.amount) for e in Expense.query.all()]
    years = sorted({d.year for d, _ in sales + spend} | {today.year})
    year = request.args.get("year", today.year, type=int)
    month_text = request.args.get("month") or today.strftime("%Y-%m")
    try:
        my, mm = (int(x) for x in month_text.split("-"))
        days = calendar.monthrange(my, mm)[1]
    except (ValueError, calendar.IllegalMonthError):
        my, mm, days = today.year, today.month, calendar.monthrange(today.year, today.month)[1]
        month_text = today.strftime("%Y-%m")

    def net(keep):
        return round(sum(a for d, a in sales if keep(d)) - sum(a for d, a in spend if keep(d)), 2)

    revenue = sum(a for d, a in sales if d.year == year)
    expenses = sum(a for d, a in spend if d.year == year)
    charts = {
        "currency": app.config["CURRENCY"],
        "monthly": {"labels": [calendar.month_abbr[m] for m in range(1, 13)],
                    "values": [net(lambda d, m=m: d.year == year and d.month == m) for m in range(1, 13)]},
        "yearly": {"labels": [str(y) for y in years],
                   "values": [net(lambda d, y=y: d.year == y) for y in years]},
        "daily": {"labels": [str(n) for n in range(1, days + 1)],
                  "values": [net(lambda d, n=n: (d.year, d.month, d.day) == (my, mm, n)) for n in range(1, days + 1)]},
    }
    return render_template("analytics.html", charts=charts, years=years, year=year, month=month_text,
                           revenue=revenue, expenses=expenses)


# ---------- settings ----------

@app.get("/settings")
@needs("settings")
def settings():
    role = request.args.get("role", "manager")
    if role not in DEFAULTS:
        role = "manager"
    enabled = {r.perm: r.enabled for r in RolePermission.query.filter_by(role=role)}
    return render_template("settings.html", role=role, perms=PERMS, enabled=enabled)


@app.post("/settings/roles")
@needs("change_privileges")
def save_privileges():
    role = request.form.get("role")
    if role not in DEFAULTS:
        abort(400)
    chosen = set(request.form.getlist("perm"))
    for perm in PERMS:
        db.session.get(RolePermission, (role, perm)).enabled = perm in chosen
    db.session.commit()
    flash(f"Saved privileges for {role}s.", "success")
    return redirect(url_for("settings", role=role))


@app.post("/settings/change-role")
@needs("change_roles")
def change_role():
    email = request.form.get("email", "").strip().lower()
    new_role = request.form.get("role")
    target = User.query.filter_by(email=email).first()
    allowed_new = ROLES if g.user.role == "admin" else ("employee", "manager")
    if target is None:
        flash("No account with that email.", "error")
    elif target.id == g.user.id:
        flash("You can't change your own role.", "error")
    elif new_role not in allowed_new:
        flash("You can't give that role.", "error")
    elif g.user.role != "admin" and target.role != "employee":
        flash("Managers can only change the role of employees.", "error")
    elif target.role == "admin" and new_role != "admin" and User.query.filter_by(role="admin").count() < 2:
        flash("There must be at least one admin.", "error")
    else:
        target.role = new_role
        db.session.commit()
        flash(f"{target.full_name} is now a {new_role}.", "success")
    return redirect(url_for("settings"))


# ---------- account ----------

@app.get("/account")
def account():
    users = User.query.order_by(User.role, User.first_name).all() if g.user.role == "admin" else []
    return render_template("account.html", users=users)


@app.post("/account/password")
def change_password():
    f = request.form
    current, new = f.get("current", ""), f.get("new", "")
    if not check_password_hash(g.user.password_hash, current):
        flash("Your current password is wrong.", "error")
    elif len(new) < 8:
        flash("The new password must be at least 8 characters.", "error")
    elif new != f.get("confirm"):
        flash("The two new passwords don't match.", "error")
    elif new == current:
        flash("Pick a password different from the current one.", "error")
    else:
        g.user.password_hash = generate_password_hash(new)
        db.session.commit()
        flash("Password changed.", "success")
    return redirect(url_for("account"))


@app.post("/account/users")
@admin_only
def add_role_user():
    f = request.form
    try:
        user = make_user(f.get("email", ""), f.get("first_name", ""), f.get("last_name", ""),
                         f.get("password", ""), f.get("role", ""))
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(f"Created {user.role} account for {user.email}.", "success")
    return redirect(url_for("account"))


@app.post("/account/users/<int:user_id>/remove")
@admin_only
def remove_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == "admin":
        flash("Admin accounts can't be removed here.", "error")
    else:
        email = user.email
        db.session.delete(user)
        db.session.commit()
        flash(f"Removed {email}.", "success")
    return redirect(url_for("account"))


if __name__ == "__main__":
    app.run(debug=True)
