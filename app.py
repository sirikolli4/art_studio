"""Art Studio API (Flask + SQLite).

Read top to bottom: helpers -> auth -> paintings/orders -> bookings -> pottery.
"""
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # .env support is optional
    pass

import seed

DB_PATH = os.environ.get("DATABASE_PATH", "studio.db")

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
seed.run(DB_PATH)  # creates tables + starter data if missing (safe to repeat)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
class ApiError(Exception):
    """Raise this anywhere; the handler below turns it into a JSON error."""

    def __init__(self, status, message):
        self.status, self.message = status, message


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error=e.message), e.status


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Flask's own errors (404 unknown URL, 405, bad JSON...) keep their status code.
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception(e)
    return jsonify(error="Something went wrong on our side."), 500


def db():
    """One SQLite connection per request."""
    if "db" not in g:
        # isolation_level=None -> we decide exactly when transactions begin.
        g.db = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def tx():
    """All-or-nothing block. BEGIN IMMEDIATE takes the write lock up front,
    so two requests can never interleave inside the block."""
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def body():
    return request.get_json(silent=True) or {}


def int_field(data, name, lo, hi):
    try:
        value = int(data.get(name))
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a whole number.")
    if not lo <= value <= hi:
        raise ApiError(400, f"{name} must be between {lo} and {hi}.")
    return value


def text_field(data, name, max_len=300):
    value = str(data.get(name) or "").strip()
    if not value:
        raise ApiError(400, f"{name} is required.")
    if len(value) > max_len:
        raise ApiError(400, f"{name} is too long.")
    return value


def date_field(data, name, min_days, max_days=None):
    try:
        d = date.fromisoformat(str(data.get(name)))
    except ValueError:
        raise ApiError(400, f"{name} must be a date like 2026-12-31.")
    days = (d - date.today()).days
    if days < min_days:
        raise ApiError(400, f"{name} must be at least {min_days} days from today.")
    if max_days is not None and days > max_days:
        raise ApiError(400, f"{name} must be within {max_days} days from today.")
    return d.isoformat()


def days_until(iso_date):
    return (date.fromisoformat(iso_date) - date.today()).days


def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args).fetchall()]


# --------------------------------------------------------------------------
# Auth + roles. The server checks the role on EVERY request.
#   not logged in -> 401      wrong role -> 403      not your record -> 404
# --------------------------------------------------------------------------
def require(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = session.get("uid")
            user = None
            if uid:
                user = db().execute("SELECT id, email, role FROM users WHERE id=?", (uid,)).fetchone()
            if not user:
                raise ApiError(401, "Please log in.")
            if role and user["role"] != role:
                raise ApiError(403, "You don't have permission to do that.")
            g.user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def owner_filter(alias):
    """Customers only see their own rows; the studio sees everything."""
    if g.user["role"] == "studio":
        return "", []
    return f"WHERE {alias}.user_id = ?", [g.user["id"]]


def transition(table, rid, new_status, allowed_from, owner_id=None, check=None):
    """Move a record to a new status, atomically.
    - owner_id given -> a record owned by someone else is 'not found' (404)
    - the UPDATE only matches if the status is still one of allowed_from, so
      two clicks at once can't both succeed (409 for the loser)."""
    sql, args = f"SELECT * FROM {table} WHERE id = ?", [rid]
    if owner_id is not None:
        sql += " AND user_id = ?"
        args.append(owner_id)
    row = db().execute(sql, args).fetchone()
    if not row:
        raise ApiError(404, "Not found.")
    if row["status"] in allowed_from and check:
        check(row)
    marks = ",".join("?" * len(allowed_from))
    cur = db().execute(
        f"UPDATE {table} SET status = ? WHERE id = ? AND status IN ({marks})",
        [new_status, rid, *allowed_from],
    )
    if cur.rowcount == 0:
        raise ApiError(409, f"This is already {row['status']}.")
    return row


@app.post("/api/signup")
def signup():
    data = body()
    email = text_field(data, "email", 120).lower()
    password = str(data.get("password") or "")
    if "@" not in email:
        raise ApiError(400, "Enter a valid email.")
    if len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters.")
    try:
        cur = db().execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?,?,'customer')",
            (email, generate_password_hash(password)),
        )
    except sqlite3.IntegrityError:
        raise ApiError(409, "That email is already registered.")
    session.clear()
    session["uid"] = cur.lastrowid
    return jsonify(user={"id": cur.lastrowid, "email": email, "role": "customer"}), 201


@app.post("/api/login")
def login():
    data = body()
    email = str(data.get("email") or "").strip().lower()
    user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], str(data.get("password") or "")):
        raise ApiError(401, "Wrong email or password.")
    session.clear()
    session["uid"] = user["id"]
    return jsonify(user={"id": user["id"], "email": user["email"], "role": user["role"]})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    uid = session.get("uid")
    user = db().execute("SELECT id, email, role FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return jsonify(user=dict(user) if user else None)  # 200 either way: the page asks this on load


@app.get("/api/catalog")
@require()
def catalog():
    rate = db().execute("SELECT value FROM settings WHERE key='wall_rate_per_sqft'").fetchone()
    return jsonify(
        wall_rate_per_sqft=int(rate["value"]),
        items=rows("SELECT id, name FROM pottery_items ORDER BY name"),
        glazes=rows("SELECT id, name FROM glazes ORDER BY name"),
    )


# --------------------------------------------------------------------------
# Paintings + orders
# --------------------------------------------------------------------------
@app.get("/api/paintings")
@require()
def list_paintings():
    return jsonify(rows("SELECT * FROM paintings ORDER BY id"))


IMAGE_RE = re.compile(r"^(images/[\w.\-]+|https?://\S+)$")


def _painting_fields(data):
    """Validate painting input. artist / image_url are None when the caller left them out."""
    title = text_field(data, "title", 200)
    price = int_field(data, "price", 1, 10_000_000)
    desc = str(data.get("description") or "").strip()[:1000]
    artist = str(data["artist"]).strip()[:120] if "artist" in data else None
    image = str(data["image_url"]).strip() if "image_url" in data else None
    if image and (len(image) > 300 or not IMAGE_RE.match(image)):
        raise ApiError(400, "image_url must look like images/p-013.jpg or be a full https link.")
    return title, artist, price, desc, image


@app.post("/api/paintings")
@require("studio")
def add_painting():
    title, artist, price, desc, image = _painting_fields(body())
    cur = db().execute(
        "INSERT INTO paintings (title, artist, description, price, image_url) VALUES (?,?,?,?,?)",
        (title, artist or "", desc, price, image or ""),
    )
    return jsonify(id=cur.lastrowid), 201


@app.put("/api/paintings/<int:pid>")
@require("studio")
def edit_painting(pid):
    title, artist, price, desc, image = _painting_fields(body())
    # Only edits while still available -- enforced inside the UPDATE itself.
    # COALESCE keeps the old artist / image when the request doesn't send one.
    cur = db().execute(
        """UPDATE paintings SET title=?, artist=COALESCE(?, artist), price=?, description=?,
                                image_url=COALESCE(?, image_url)
           WHERE id=? AND status='available'""",
        (title, artist, price, desc, image, pid),
    )
    if cur.rowcount == 0:
        exists = db().execute("SELECT 1 FROM paintings WHERE id=?", (pid,)).fetchone()
        raise ApiError(409, "A sold painting can't be edited.") if exists else ApiError(404, "Not found.")
    return jsonify(ok=True)


@app.get("/api/orders")
@require()
def list_orders():
    where, args = owner_filter("o")
    return jsonify(rows(
        f"""SELECT o.id, o.status, o.created_at, p.title AS painting_title, p.artist, p.image_url, p.price,
                   u.email AS customer_email
            FROM orders o JOIN paintings p ON p.id = o.painting_id
                          JOIN users u ON u.id = o.user_id
            {where} ORDER BY o.id DESC""", args))


@app.post("/api/orders")
@require("customer")
def buy_painting():
    pid = int_field(body(), "painting_id", 1, 2**31)
    with tx() as conn:
        # THE race-proof step: flip available -> sold in one atomic statement.
        # Only one request can ever see rowcount == 1.
        cur = conn.execute("UPDATE paintings SET status='sold' WHERE id=? AND status='available'", (pid,))
        if cur.rowcount == 0:
            exists = conn.execute("SELECT 1 FROM paintings WHERE id=?", (pid,)).fetchone()
            raise ApiError(409, "Sorry, this painting was just sold.") if exists else ApiError(404, "Not found.")
        cur = conn.execute("INSERT INTO orders (user_id, painting_id) VALUES (?,?)", (g.user["id"], pid))
    return jsonify(id=cur.lastrowid), 201


@app.post("/api/orders/<int:oid>/cancel")
@require("customer")
def cancel_order(oid):
    with tx() as conn:
        row = transition("orders", oid, "cancelled", ["placed"], owner_id=g.user["id"])
        conn.execute("UPDATE paintings SET status='available' WHERE id=?", (row["painting_id"],))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Wall painting bookings
# --------------------------------------------------------------------------
@app.get("/api/bookings")
@require()
def list_bookings():
    where, args = owner_filter("b")
    return jsonify(rows(
        f"""SELECT b.*, u.email AS customer_email FROM bookings b
            JOIN users u ON u.id = b.user_id {where} ORDER BY b.date""", args))


@app.post("/api/bookings")
@require("customer")
def create_booking():
    data = body()
    day = date_field(data, "date", 7, 90)
    sqft = int_field(data, "wall_sqft", 10, 500)
    address = text_field(data, "address", 300)
    rate = int(db().execute("SELECT value FROM settings WHERE key='wall_rate_per_sqft'").fetchone()["value"])
    try:
        # The unique index on live dates is what actually guarantees one booking per date.
        cur = db().execute(
            "INSERT INTO bookings (user_id, date, wall_sqft, address, price) VALUES (?,?,?,?,?)",
            (g.user["id"], day, sqft, address, sqft * rate),
        )
    except sqlite3.IntegrityError:
        raise ApiError(409, "Sorry, that date was just taken. Please pick another.")
    return jsonify(id=cur.lastrowid, price=sqft * rate), 201


@app.get("/api/booked-dates")
@require()
def booked_dates():
    """Dates held by a live booking (no personal details) so the form can warn early.
    The unique index is still what actually prevents a double booking."""
    found = db().execute(
        "SELECT date FROM bookings WHERE status IN ('requested','confirmed') AND date >= ? ORDER BY date",
        (date.today().isoformat(),),
    ).fetchall()
    return jsonify([r["date"] for r in found])


def _cancel_window(row):
    if days_until(row["date"]) < 3:
        raise ApiError(409, "Bookings can only be cancelled until 3 days before the date.")


@app.post("/api/bookings/<int:bid>/cancel")
@require("customer")
def cancel_booking(bid):
    transition("bookings", bid, "cancelled", ["requested", "confirmed"], owner_id=g.user["id"], check=_cancel_window)
    return jsonify(ok=True)


@app.post("/api/bookings/<int:bid>/confirm")
@require("studio")
def confirm_booking(bid):
    transition("bookings", bid, "confirmed", ["requested"])
    return jsonify(ok=True)


@app.post("/api/bookings/<int:bid>/decline")
@require("studio")
def decline_booking(bid):
    transition("bookings", bid, "declined", ["requested"])
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Custom pottery
# --------------------------------------------------------------------------
def _pottery_fields(data):
    item_id = int_field(data, "item_id", 1, 2**31)
    glaze_id = int_field(data, "glaze_id", 1, 2**31)
    if not db().execute("SELECT 1 FROM pottery_items WHERE id=?", (item_id,)).fetchone():
        raise ApiError(400, "Unknown item.")
    if not db().execute("SELECT 1 FROM glazes WHERE id=?", (glaze_id,)).fetchone():
        raise ApiError(400, "Unknown glaze.")
    return item_id, glaze_id, int_field(data, "quantity", 1, 12), date_field(data, "needed_by", 14)


@app.get("/api/pottery")
@require()
def list_pottery():
    where, args = owner_filter("r")
    return jsonify(rows(
        f"""SELECT r.id, r.item_id, r.glaze_id, r.quantity, r.needed_by, r.status,
                   i.name AS item, g.name AS glaze, u.email AS customer_email
            FROM pottery_requests r JOIN pottery_items i ON i.id = r.item_id
                                    JOIN glazes g ON g.id = r.glaze_id
                                    JOIN users u ON u.id = r.user_id
            {where} ORDER BY r.id DESC""", args))


@app.post("/api/pottery")
@require("customer")
def request_pottery():
    item_id, glaze_id, qty, needed_by = _pottery_fields(body())
    cur = db().execute(
        "INSERT INTO pottery_requests (user_id, item_id, glaze_id, quantity, needed_by) VALUES (?,?,?,?,?)",
        (g.user["id"], item_id, glaze_id, qty, needed_by),
    )
    return jsonify(id=cur.lastrowid), 201


@app.put("/api/pottery/<int:rid>")
@require("customer")
def edit_pottery(rid):
    item_id, glaze_id, qty, needed_by = _pottery_fields(body())
    # Ownership + "still requested" are both enforced inside the UPDATE.
    cur = db().execute(
        """UPDATE pottery_requests SET item_id=?, glaze_id=?, quantity=?, needed_by=?
           WHERE id=? AND user_id=? AND status='requested'""",
        (item_id, glaze_id, qty, needed_by, rid, g.user["id"]),
    )
    if cur.rowcount == 0:
        mine = db().execute("SELECT 1 FROM pottery_requests WHERE id=? AND user_id=?", (rid, g.user["id"])).fetchone()
        raise ApiError(409, "Only requests that are still 'requested' can be edited.") if mine else ApiError(404, "Not found.")
    return jsonify(ok=True)


@app.post("/api/pottery/<int:rid>/cancel")
@require("customer")
def cancel_pottery(rid):
    transition("pottery_requests", rid, "cancelled", ["requested"], owner_id=g.user["id"])
    return jsonify(ok=True)


@app.post("/api/pottery/<int:rid>/accept")
@require("studio")
def accept_pottery(rid):
    transition("pottery_requests", rid, "accepted", ["requested"])
    return jsonify(ok=True)


@app.post("/api/pottery/<int:rid>/decline")
@require("studio")
def decline_pottery(rid):
    transition("pottery_requests", rid, "declined", ["requested"])
    return jsonify(ok=True)


# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
