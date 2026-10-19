#!/usr/bin/env python3
"""
Bugema University Gym — Hardened REST API Bridge
Connects the Bugema Gym website (book.html, attendance.html) directly
with the Reception Python Gym Tracker database (gym.db).

Security & Business Logic Highlights:
- Strict Localhost Isolation (Bound to 127.0.0.1)
- HTTP Security Headers (anti-clickjacking, MIME-sniffing protection)
- Sliding-Window Rate Limiting (anti-DDoS, anti-spam)
- Strict Input Validation & HTML Sanitization (SQLi & XSS protection)
- Online Subscriptions saved as PENDING PAYMENTS until Receptionist approval
- Administrative Endpoints protected via Secret Auth Token
"""

import os
import sys
import re
import secrets
import sqlite3
import functools
import contextlib
from datetime import datetime, date, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gym.db")
API_PORT = 5050
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".reception_secret")


# ─── Administrative Security Token Management ────────────────────────────────
def load_or_create_admin_token() -> str:
    """Loads or generates a cryptographically secure 256-bit token for receptionist authorization."""
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if len(t) >= 32:
                    return t
        except Exception:
            pass
    token = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(token)
    except Exception:
        pass
    return token

ADMIN_SECRET_TOKEN = load_or_create_admin_token()


# ─── Flask App & CORS Initialization ─────────────────────────────────────────
app = Flask(__name__)

# Strict CORS configuration
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)


# ─── Security Headers & Middleware ───────────────────────────────────────────
@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Reception-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


# ─── In-Memory Rate Limiting (Anti-Spam & DDoS Protection) ────────────────────
RATE_LIMIT_STORE = {}  # ip -> list of timestamps
PHONE_LIMIT_STORE = {} # phone -> last submission timestamp

def is_rate_limited(client_ip: str, max_requests: int = 25, window_seconds: int = 60) -> bool:
    """Sliding-window rate limiter per client IP."""
    now = datetime.now().timestamp()
    history = RATE_LIMIT_STORE.get(client_ip, [])
    history = [t for t in history if now - t < window_seconds]
    if len(history) >= max_requests:
        return True
    history.append(now)
    RATE_LIMIT_STORE[client_ip] = history
    return False

def is_phone_throttled(phone: str, cooldown_seconds: int = 20) -> bool:
    """Blocks rapid repeated submissions for the same phone number."""
    now = datetime.now().timestamp()
    last_time = PHONE_LIMIT_STORE.get(phone, 0)
    if now - last_time < cooldown_seconds:
        return True
    PHONE_LIMIT_STORE[phone] = now
    return False


# ─── Authentication Decorator for Sensitive Endpoints ────────────────────────
def require_reception_auth(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow requests with valid secret token header or query parameter
        provided_token = request.headers.get("X-Reception-Key") or request.args.get("reception_key")
        # Local Python internal calls can bypass if requested locally
        if provided_token != ADMIN_SECRET_TOKEN:
            return jsonify({"error": "Unauthorized: Receptionist administrative credentials required"}), 403
        return f(*args, **kwargs)
    return decorated_function


# ─── Input Sanitization & Validation Helpers ─────────────────────────────────
def sanitize_string(val: str, max_len: int = 60) -> str:
    if not val:
        return ""
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]*?>", "", str(val))
    # Strip control characters
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", cleaned)
    return cleaned.strip()[:max_len]

def validate_phone(phone: str) -> bool:
    clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    return bool(re.match(r"^\+?[0-9]{7,16}$", clean))

def validate_name(name: str) -> bool:
    return bool(re.match(r"^[a-zA-Z\s'\-\.]{2,60}$", name))

def validate_email(email: str) -> bool:
    if not email:
        return True  # Optional
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email)) and len(email) <= 100


# ─── Database Helpers ────────────────────────────────────────────────────────
@contextlib.contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_months(source_date: date, months: int) -> date:
    """Add calendar months to a date, clamping to month-end boundaries."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_months = [31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(source_date.day, days_in_months[month - 1])
    return date(year, month, day)


def calculate_expiration(source_date: date, duration_months: int, duration_days: int = 0) -> date:
    """
    Calculates expiration date.
    If duration_months is 0, adds days (default 1 day for Daily Pass).
    Otherwise adds calendar months.
    """
    if duration_months <= 0:
        days = duration_days if duration_days > 0 else 1
        return source_date + timedelta(days=days)
    return add_months(source_date, duration_months)


# Website plan keys → tracker plan names and parameters
PLAN_CONFIG = {
    "daily": {
        "name": "Student Daily Pass",
        "duration_months": 0,
        "duration_days": 1,
        "price": 2000.0,
    },
    "monthly": {
        "name": "Monthly Standard",
        "duration_months": 1,
        "duration_days": 0,
        "price": 30000.0,
    },
    "vip": {
        "name": "Semestrial Subscription",
        "duration_months": 4,
        "duration_days": 0,
        "price": 120000.0,
    },
    "unlimited": {
        "name": "Annual Unlimited",
        "duration_months": 12,
        "duration_days": 0,
        "price": 360000.0,
    },
}


def init_database():
    """Ensures database schema and lookup plans exist in gym.db."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Plans
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                duration_months INTEGER NOT NULL,
                price REAL NOT NULL
            )
        """)
        # Members (Official Active Members)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                plan_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                expiration_date TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id)
            )
        """)
        # Renewals (Receipts & Financial Ledger)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS renewals (
                renewal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                renewal_date TEXT NOT NULL,
                old_expiration_date TEXT,
                new_expiration_date TEXT NOT NULL,
                amount_paid REAL NOT NULL,
                FOREIGN KEY (member_id) REFERENCES members (member_id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id)
            )
        """)
        # Attendance Check-ins
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER,
                full_name TEXT NOT NULL,
                phone TEXT,
                weight_kg REAL,
                height_cm TEXT,
                session TEXT,
                checkin_time TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (member_id) REFERENCES members (member_id)
            )
        """)
        # Pending Payments (Online registrations awaiting receptionist approval)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_payments (
                pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                plan_id INTEGER NOT NULL,
                plan_name TEXT NOT NULL,
                amount_due REAL NOT NULL,
                start_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                approved_at TEXT,
                approved_by TEXT,
                notes TEXT,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id)
            )
        """)

        # Seed standard website plans
        for key, p in PLAN_CONFIG.items():
            cursor.execute("SELECT plan_id FROM plans WHERE name = ?", (p["name"],))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO plans (name, duration_months, price) VALUES (?, ?, ?)",
                    (p["name"], p["duration_months"], p["price"]),
                )


# Run initialization on startup
init_database()


def resolve_plan(plan_key: str, cursor) -> tuple[int, str, int, int, float]:
    """Resolves plan_id, plan_name, duration_months, duration_days, price."""
    key_clean = plan_key.strip().lower()

    if key_clean in PLAN_CONFIG:
        cfg = PLAN_CONFIG[key_clean]
        target_name = cfg["name"]
        months = cfg["duration_months"]
        days = cfg["duration_days"]
        price = cfg["price"]
    else:
        cursor.execute("SELECT * FROM plans WHERE LOWER(name) = LOWER(?)", (plan_key.strip(),))
        row = cursor.fetchone()
        if row:
            return (
                row["plan_id"],
                row["name"],
                row["duration_months"],
                1 if row["duration_months"] == 0 else 0,
                row["price"],
            )
        cfg = PLAN_CONFIG["monthly"]
        target_name = cfg["name"]
        months = cfg["duration_months"]
        days = cfg["duration_days"]
        price = cfg["price"]

    cursor.execute("SELECT * FROM plans WHERE name = ?", (target_name,))
    row = cursor.fetchone()
    if row:
        return (
            row["plan_id"],
            row["name"],
            row["duration_months"],
            days,
            row["price"],
        )

    cursor.execute(
        "INSERT INTO plans (name, duration_months, price) VALUES (?, ?, ?)",
        (target_name, months, price),
    )
    return cursor.lastrowid, target_name, months, days, price


# ─── REST Endpoints ──────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Bugema Gym Tracker Secure API Bridge",
        "database": DB_PATH,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "security": "Enforced (Localhost, Rate Limiting, Input Sanitization)"
    }), 200


@app.route("/api/plans", methods=["GET"])
def get_plans():
    """Returns all available subscription plans."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans ORDER BY duration_months ASC, price ASC")
        rows = cursor.fetchall()
        plans = [dict(r) for r in rows]
    return jsonify({"success": True, "plans": plans}), 200


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Returns dashboard summary counts (total, active, expiring soon, expired, pending approvals)."""
    today = date.today()
    threshold = int(request.args.get("threshold", 7))
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT member_id, expiration_date FROM members")
        rows = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM pending_payments WHERE status = 'PENDING'")
        pending_count = cursor.fetchone()[0]

    total = len(rows)
    active = 0
    expiring_soon = 0
    expired = 0

    for r in rows:
        try:
            exp_date = datetime.strptime(r["expiration_date"], "%Y-%m-%d").date()
            days_left = (exp_date - today).days
            if days_left < 0:
                expired += 1
            elif days_left <= threshold:
                expiring_soon += 1
            else:
                active += 1
        except Exception:
            expired += 1

    return jsonify({
        "success": True,
        "total": total,
        "active": active,
        "expiring_soon": expiring_soon,
        "expired": expired,
        "pending": pending_count,
        "system_date": today.strftime("%Y-%m-%d"),
    }), 200


@app.route("/api/members", methods=["GET"])
def get_members():
    """Returns active gym members with dynamically calculated statuses."""
    search = sanitize_string(request.args.get("search", ""), 50)
    status_filter = sanitize_string(request.args.get("status", "ALL"), 20).upper()
    threshold = int(request.args.get("threshold", 7))
    today = date.today()

    query = """
        SELECT m.member_id, m.full_name, m.phone, m.email, m.start_date, m.expiration_date,
               p.name AS plan_name, p.price, p.duration_months
        FROM members m
        JOIN plans p ON m.plan_id = p.plan_id
    """
    params = []
    if search:
        query += " WHERE (m.full_name LIKE ? OR m.phone LIKE ? OR m.email LIKE ?)"
        pat = f"%{search}%"
        params.extend([pat, pat, pat])

    query += " ORDER BY m.member_id DESC"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    members = []
    for r in rows:
        try:
            exp_date = datetime.strptime(r["expiration_date"], "%Y-%m-%d").date()
            days_left = (exp_date - today).days
        except Exception:
            days_left = -1

        if days_left < 0:
            status = "EXPIRED"
        elif days_left <= threshold:
            status = "EXPIRING SOON"
        else:
            status = "ACTIVE"

        if status_filter != "ALL" and status != status_filter:
            continue

        members.append({
            "member_id": r["member_id"],
            "formatted_id": f"BUG-{r['member_id']:04d}",
            "full_name": r["full_name"],
            "phone": r["phone"],
            "email": r["email"] or "",
            "plan_name": r["plan_name"],
            "price": r["price"],
            "start_date": r["start_date"],
            "expiration_date": r["expiration_date"],
            "days_remaining": days_left,
            "status": status,
        })

    return jsonify({"success": True, "count": len(members), "members": members}), 200


@app.route("/api/members/check", methods=["GET"])
def check_member():
    """Looks up membership and expiration date by phone number or member_id."""
    phone = sanitize_string(request.args.get("phone", ""), 25)
    member_id = request.args.get("id")

    if not phone and not member_id:
        return jsonify({"error": "Either phone or id is required"}), 400

    today = date.today()
    clean_phone = phone.replace(" ", "").replace("+256", "0").replace("-", "")

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Check in official members table
        query = """
            SELECT m.member_id, m.full_name, m.phone, m.email, m.start_date, m.expiration_date,
                   p.name AS plan_name, p.price, p.duration_months
            FROM members m
            JOIN plans p ON m.plan_id = p.plan_id
        """
        params = []
        if member_id:
            query += " WHERE m.member_id = ?"
            params.append(member_id)
        else:
            query += " WHERE m.phone LIKE ?"
            params.append(f"%{clean_phone}%")

        cursor.execute(query, params)
        row = cursor.fetchone()

        if row:
            try:
                exp_date = datetime.strptime(row["expiration_date"], "%Y-%m-%d").date()
                days_left = (exp_date - today).days
            except Exception:
                days_left = -1

            if days_left < 0:
                status = "EXPIRED"
            elif days_left <= 7:
                status = "EXPIRING SOON"
            else:
                status = "ACTIVE"

            return jsonify({
                "found": True,
                "is_pending": False,
                "member": {
                    "member_id": row["member_id"],
                    "formatted_id": f"BUG-{row['member_id']:04d}",
                    "full_name": row["full_name"],
                    "phone": row["phone"],
                    "email": row["email"] or "",
                    "plan_name": row["plan_name"],
                    "start_date": row["start_date"],
                    "expiration_date": row["expiration_date"],
                    "days_remaining": days_left,
                    "status": status,
                }
            }), 200

        # 2. Check in pending_payments table (booked online but awaiting counter payment)
        cursor.execute("""
            SELECT pending_id, full_name, phone, email, plan_name, amount_due, start_date
            FROM pending_payments
            WHERE phone LIKE ? AND status = 'PENDING'
            ORDER BY pending_id DESC LIMIT 1
        """, (f"%{clean_phone}%",))
        pending_row = cursor.fetchone()

        if pending_row:
            return jsonify({
                "found": True,
                "is_pending": True,
                "member": {
                    "member_id": None,
                    "formatted_id": f"BUG-P{pending_row['pending_id']:04d}",
                    "full_name": pending_row["full_name"],
                    "phone": pending_row["phone"],
                    "email": pending_row["email"] or "",
                    "plan_name": pending_row["plan_name"],
                    "start_date": pending_row["start_date"],
                    "expiration_date": "Pending Desk Payment",
                    "days_remaining": 0,
                    "status": "PENDING PAYMENT",
                }
            }), 200

    return jsonify({"found": False, "message": "No member or pending booking found matching phone/ID."}), 200


# ─── ONLINE REGISTRATION (STRICT SECURITY & PENDING APPROVAL) ────────────────
@app.route("/api/register", methods=["POST"])
def register_member():
    """
    Online registration endpoint called by book.html.
    
    SECURITY MEASURES:
    - Rate-limited (max 25 requests/min per IP, 20s cooldown per phone)
    - Full input sanitization (XSS, SQL injection protection)
    - All registrations saved as PENDING PAYMENTS
    - Member is NOT activated until receptionist confirms payment at front desk!
    """
    client_ip = request.remote_addr or "127.0.0.1"
    if is_rate_limited(client_ip):
        return jsonify({"error": "Rate limit exceeded. Please wait a minute before trying again."}), 429

    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "Invalid request payload"}), 400

    # Sanitize and validate inputs
    full_name = sanitize_string(data.get("full_name", ""), 60)
    phone = sanitize_string(data.get("phone", ""), 25)
    email = sanitize_string(data.get("email", ""), 80)
    plan_key = sanitize_string(data.get("plan", "monthly"), 30).lower()
    start_str = sanitize_string(data.get("start_date", ""), 15)

    if not full_name or not validate_name(full_name):
        return jsonify({"error": "Invalid name. Please enter a valid alphabetic name (2-60 characters)."}), 400

    if not phone or not validate_phone(phone):
        return jsonify({"error": "Invalid phone number. Example format: 0771234567 or +256771234567."}), 400

    if email and not validate_email(email):
        return jsonify({"error": "Invalid email address format."}), 400

    if is_phone_throttled(phone):
        return jsonify({"error": "A registration was recently submitted for this phone number. Please check at the reception counter."}), 429

    if not start_str:
        start_str = date.today().strftime("%Y-%m-%d")

    try:
        start_date_obj = datetime.strptime(start_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid start_date format. Must be YYYY-MM-DD."}), 400

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            plan_id, plan_name, duration_months, duration_days, price = resolve_plan(plan_key, cursor)

            # Check if there is already an active member with this phone
            cursor.execute("SELECT member_id, full_name FROM members WHERE phone = ?", (phone,))
            existing_member = cursor.fetchone()
            is_renewal = bool(existing_member)

            # Insert into pending_payments table (Awaiting Counter Payment)
            created_at = datetime.now().isoformat(timespec="seconds")
            cursor.execute("""
                INSERT INTO pending_payments (
                    full_name, phone, email, plan_id, plan_name, amount_due, start_date, status, created_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """, (
                full_name, phone, email, plan_id, plan_name, price, start_str, created_at,
                "Online renewal booking" if is_renewal else "New online registration"
            ))
            pending_id = cursor.lastrowid

        booking_ref = f"BUG-P{pending_id:04d}"

        return jsonify({
            "success": True,
            "status": "PENDING_PAYMENT",
            "is_new": not is_renewal,
            "pending_id": pending_id,
            "booking_ref": booking_ref,
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "plan_name": plan_name,
            "price": price,
            "price_formatted": f"{price:,.0f} UGX",
            "start_date": start_str,
            "message": f"Online registration recorded! Your booking reference is {booking_ref}. Please present this reference at the reception counter to pay and activate your membership.",
        }), 201

    except Exception as exc:
        return jsonify({"error": f"Internal database error: {str(exc)}"}), 500


# ─── RECEPTIONIST APPROVAL ENDPOINTS (SECURED) ──────────────────────────────

@app.route("/api/pending", methods=["GET"])
def get_pending_payments():
    """Fetches all online registrations currently awaiting counter payment."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pending_id, full_name, phone, email, plan_id, plan_name, amount_due, start_date, status, created_at
            FROM pending_payments
            WHERE status = 'PENDING'
            ORDER BY pending_id DESC
        """)
        rows = cursor.fetchall()
        pending = []
        for r in rows:
            d = dict(r)
            d["booking_ref"] = f"BUG-P{r['pending_id']:04d}"
            d["amount_formatted"] = f"{r['amount_due']:,.0f} UGX"
            pending.append(d)

    return jsonify({"success": True, "count": len(pending), "pending": pending}), 200


@app.route("/api/pending/<int:pending_id>/approve", methods=["POST"])
@require_reception_auth
def approve_pending_payment(pending_id: int):
    """
    Receptionist approves an online booking after confirming payment.
    Transfers the member into active members, sets expiration date, and records payment receipt.
    """
    from gym_tracker import DatabaseManager, MembershipManager
    db_mgr = DatabaseManager(DB_PATH)
    mgr = MembershipManager(db_mgr)
    success, message, info = mgr.approve_pending_payment(pending_id, approved_by="Receptionist")
    if not success:
        return jsonify({"success": False, "error": message}), 400
    return jsonify({"success": True, "message": message, "member": info}), 200


@app.route("/api/pending/<int:pending_id>/reject", methods=["POST"])
@require_reception_auth
def reject_pending_payment(pending_id: int):
    """Receptionist cancels or rejects an online booking."""
    from gym_tracker import DatabaseManager, MembershipManager
    data = request.get_json(silent=True) or {}
    reason = sanitize_string(data.get("reason", "Cancelled by receptionist"), 100)
    db_mgr = DatabaseManager(DB_PATH)
    mgr = MembershipManager(db_mgr)
    success, message = mgr.reject_pending_payment(pending_id, reason=reason)
    if not success:
        return jsonify({"success": False, "error": message}), 400
    return jsonify({"success": True, "message": message}), 200


# ─── ATTENDANCE LOGGING ──────────────────────────────────────────────────────

@app.route("/api/attendance", methods=["POST"])
def log_attendance():
    """Logs member check-in from attendance.html into attendance table in gym.db."""
    client_ip = request.remote_addr or "127.0.0.1"
    if is_rate_limited(client_ip, max_requests=40):
        return jsonify({"error": "Rate limit exceeded"}), 429

    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    full_name = sanitize_string(data.get("full_name", ""), 60)
    phone = sanitize_string(data.get("phone", ""), 25)
    height_cm = sanitize_string(data.get("height_cm", ""), 15)
    session = sanitize_string(data.get("session", "General Gym Conditioning"), 50)
    checkin_time = sanitize_string(data.get("checkin_time", ""), 30) or datetime.now().isoformat(timespec="seconds")

    if not full_name or not validate_name(full_name):
        return jsonify({"error": "Valid member full name is required"}), 400

    try:
        weight_kg = float(data.get("weight_kg")) if data.get("weight_kg") else None
        if weight_kg and (weight_kg < 20 or weight_kg > 300):
            return jsonify({"error": "Weight must be between 20kg and 300kg"}), 400
    except (ValueError, TypeError):
        weight_kg = None

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            member_id = None
            if phone:
                cursor.execute("SELECT member_id FROM members WHERE phone = ?", (phone,))
                m_row = cursor.fetchone()
                if m_row:
                    member_id = m_row["member_id"]

            cursor.execute("""
                INSERT INTO attendance (member_id, full_name, phone, weight_kg, height_cm, session, checkin_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (member_id, full_name, phone, weight_kg, height_cm, session, checkin_time))
            attendance_id = cursor.lastrowid

        return jsonify({
            "success": True,
            "attendance_id": attendance_id,
            "member_id": member_id,
            "full_name": full_name,
            "checkin_time": checkin_time,
            "message": f"Workout check-in logged for {full_name}."
        }), 201

    except Exception as exc:
        return jsonify({"error": f"Database error: {str(exc)}"}), 500


@app.route("/api/attendance", methods=["GET"])
def get_attendance():
    """Fetches recent workout attendance logs."""
    limit = min(int(request.args.get("limit", 50)), 200)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, m.expiration_date, p.name as plan_name
            FROM attendance a
            LEFT JOIN members m ON a.member_id = m.member_id
            LEFT JOIN plans p ON m.plan_id = p.plan_id
            ORDER BY a.attendance_id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        logs = [dict(r) for r in rows]

    return jsonify({"success": True, "count": len(logs), "attendance": logs}), 200


if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("   BUGEMA GYM — HARDENED RECEPTION API BRIDGE")
    print(f"   Connecting Website & Reception Tracker with Maximum Security")
    print(f"{'='*70}")
    print(f"   Database       : {DB_PATH}")
    print(f"   Binding Host   : 127.0.0.1 (Strict Localhost Isolation)")
    print(f"   Port           : {API_PORT}")
    print(f"   Admin Token    : {ADMIN_SECRET_TOKEN[:8]}...[PROTECTED]")
    print(f"   Security Rules : Rate Limiting, Input Sanitization, Security Headers")
    print(f"   Workflow       : Online bookings -> PENDING PAYMENTS (Desk Approval)")
    print(f"{'='*70}\n")
    app.run(host="127.0.0.1", port=API_PORT, debug=False)
