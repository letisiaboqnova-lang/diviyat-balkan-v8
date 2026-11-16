import os
import secrets
import sqlite3
from functools import wraps
from hmac import compare_digest
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort
)
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-only-change-me"
)

DB_PATH = Path("tourism.db")

MAX_PARTICIPANTS = 12


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def add_phone_level_columns(connection, table_name):
    existing_columns = {
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }

    if "phone" not in existing_columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN phone TEXT"
        )

    if "level" not in existing_columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN level TEXT"
        )


def init_db():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1))
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS booking_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                participants INTEGER NOT NULL
                    CHECK(participants BETWEEN 1 AND 12),
                preferred_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS tour_departures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                departure_date TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1)),
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departure_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                participants INTEGER NOT NULL CHECK(participants > 0),
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (departure_id)
                    REFERENCES tour_departures(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK(role IN ('public', 'operator', 'admin')),
                status TEXT NOT NULL
                    CHECK(status IN (
                        'ACTIVE',
                        'PENDING_APPROVAL',
                        'DISABLED'
                    )),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        add_phone_level_columns(connection, "booking_requests")
        add_phone_level_columns(connection, "bookings")

        count = connection.execute(
            "SELECT COUNT(*) FROM tours"
        ).fetchone()[0]

        if count == 0:
            connection.executemany(
                """
                INSERT INTO tours (code, name, price)
                VALUES (?, ?, ?)
                """,
                [
                    ("weekend", "Уикенд във Врачанския Балкан", 199),
                    ("ledenika", "Пещерно приключение в Леденика", 99),
                    ("skaklya", "Пролетен поход до водопад Скакля", 89),
                    ("vratsata", "Фотообиколка на Вратцата", 129),
                ],
            )

        departure_count = connection.execute(
            "SELECT COUNT(*) FROM tour_departures"
        ).fetchone()[0]

        if departure_count == 0:
            weekend_id = connection.execute(
                "SELECT id FROM tours WHERE code = 'weekend'"
            ).fetchone()["id"]

            connection.executemany(
                """
                INSERT INTO tour_departures
                    (tour_id, departure_date, capacity)
                VALUES (?, ?, ?)
                """,
                [
                    (weekend_id, "2026-11-15", 12),
                    (weekend_id, "2026-11-22", 12),
                    (weekend_id, "2026-11-29", 12),
                ]
            )

        user_count = connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if user_count == 0:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, 'admin', 'ACTIVE')
                """,
                (
                    "admin",
                    "admin@example.com",
                    generate_password_hash("Admin123!")
                )
            )


init_db()


def migrate_tours_table():
    with get_connection() as connection:
        existing_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tours)"
            ).fetchall()
        }

        columns_to_add = {
            "location": "TEXT",
            "description": "TEXT",
            "capacity": "INTEGER",
            "latitude": "REAL",
            "longitude": "REAL",
            "map_query": "TEXT",
            "image_url": "TEXT",
        }

        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE tours "
                    f"ADD COLUMN {column_name} {column_type}"
                )

        # Попълва данните само ако още са празни,
        # за да не се презапишат вече въведените.
        start_data = [
            (
                "Враца",
                "Двудневно приключение сред скалите и пещерите на Врачанския Балкан.",
                12,
                43.2000,
                23.5500,
                "Природен парк Врачански Балкан, България",
                "/static/images/vrachanskibalkan.jpg",
                "weekend",
            ),
            (
                "Пещера Леденика",
                "Разходка из залите на една от най-красивите пещери в България.",
                12,
                43.2050,
                23.4930,
                "Пещера Леденика, България",
                "/static/images/ledenika.jpg",
                "ledenika",
            ),
            (
                "Водопад Скакля",
                "Пролетен поход до един от най-високите водопади в България.",
                12,
                43.2190,
                23.5120,
                "Водопад Скакля, България",
                "/static/images/skaklya.jpg",
                "skaklya",
            ),
            (
                "Вратцата",
                "Фотообиколка в тесния пролом между отвесните скали.",
                12,
                43.1890,
                23.5060,
                "Вратцата, Враца, България",
                "/static/images/vratsata.jpg",
                "vratsata",
            ),
        ]

        for row in start_data:
            connection.execute(
                """
                UPDATE tours
                SET location = ?,
                    description = ?,
                    capacity = ?,
                    latitude = ?,
                    longitude = ?,
                    map_query = ?,
                    image_url = ?
                WHERE code = ?
                  AND location IS NULL
                """,
                row
            )


migrate_tours_table()


def migrate_ownership():
    with get_connection() as connection:
        tour_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tours)"
            ).fetchall()
        }

        if "operator_id" not in tour_columns:
            connection.execute(
                "ALTER TABLE tours "
                "ADD COLUMN operator_id INTEGER"
            )

        booking_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(bookings)"
            ).fetchall()
        }

        if "public_user_id" not in booking_columns:
            connection.execute(
                "ALTER TABLE bookings "
                "ADD COLUMN public_user_id INTEGER"
            )


migrate_ownership()


# ---------- Login, роли и CSRF ----------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            if session.get("role") not in allowed_roles:
                abort(403)

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def get_csrf_token():
    token = session.get("csrf_token")

    if token is None:
        token = secrets.token_hex(32)
        session["csrf_token"] = token

    return token


@app.context_processor
def inject_csrf_token():
    return {
        "csrf_token": get_csrf_token
    }


def validate_csrf():
    expected = session.get("csrf_token")
    received = request.form.get("csrf_token", "")

    if (
        not expected
        or not received
        or not compare_digest(expected, received)
    ):
        abort(400)


def can_manage(operator_id):
    if session.get("role") == "admin":
        return True

    return (
        session.get("role") == "operator"
        and operator_id == session.get("user_id")
    )


def get_available_capacity(connection, departure_id):
    row = connection.execute(
        """
        SELECT
            d.capacity,
            COALESCE(
                SUM(
                    CASE
                        WHEN b.status = 'CONFIRMED'
                        THEN b.participants
                        ELSE 0
                    END
                ),
                0
            ) AS reserved
        FROM tour_departures AS d
        LEFT JOIN bookings AS b
          ON b.departure_id = d.id
        WHERE d.id = ?
        GROUP BY d.id
        """,
        (departure_id,)
    ).fetchone()

    if row is None:
        return None

    return row["capacity"] - row["reserved"]


# ---------- Публична част ----------

@app.route("/")
def home():
    with get_connection() as connection:
        tours = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()

    return render_template("index.html", tours=tours)


@app.route("/tours/<int:tour_id>")
def tour_detail(tour_id):
    with get_connection() as connection:
        tour = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE id = ? AND is_active = 1
            """,
            (tour_id,)
        ).fetchone()

        departures = connection.execute(
            """
            SELECT
                d.id,
                d.departure_date,
                d.capacity,
                d.capacity -
                COALESCE(SUM(
                    CASE
                        WHEN b.status = 'CONFIRMED'
                        THEN b.participants
                        ELSE 0
                    END
                ), 0) AS available
            FROM tour_departures AS d
            LEFT JOIN bookings AS b
              ON b.departure_id = d.id
            WHERE d.tour_id = ?
              AND d.is_active = 1
            GROUP BY d.id
            ORDER BY d.departure_date
            """,
            (tour_id,)
        ).fetchall()

    if tour is None:
        return "Офертата не е намерена.", 404

    return render_template(
        "tour_detail.html",
        tour=tour,
        departures=departures
    )


# Старият модел от Семинар 4 (запазен за история)
@app.route("/booking", methods=["POST"])
def booking():
    customer_name = request.form.get("customer_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    level = request.form.get("level", "").strip()
    preferred_date = request.form.get("preferred_date", "").strip()

    try:
        tour_id = int(request.form.get("tour_id", ""))
        participants = int(request.form.get("participants", ""))
    except ValueError:
        return "Невалидни данни.", 400

    if not customer_name or "@" not in email:
        return "Проверете име и e-mail.", 400

    if not phone or not level:
        return "Попълнете телефон и ниво на подготовка.", 400

    if not 1 <= participants <= MAX_PARTICIPANTS:
        return "Участниците трябва да са между 1 и 12.", 400

    with get_connection() as connection:
        tour = connection.execute(
            "SELECT id FROM tours WHERE id = ? AND is_active = 1",
            (tour_id,)
        ).fetchone()

        if tour is None:
            return "Офертата не съществува.", 400

        connection.execute(
            """
            INSERT INTO booking_requests
                (tour_id, customer_name, email, phone, level,
                 participants, preferred_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tour_id, customer_name, email, phone, level,
             participants, preferred_date)
        )

    return redirect(url_for("bookings"))


@app.route("/bookings")
def bookings():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                br.id,
                br.customer_name,
                br.email,
                br.phone,
                br.level,
                br.participants,
                br.preferred_date,
                t.name AS tour_name,
                t.price
            FROM booking_requests AS br
            JOIN tours AS t
              ON t.id = br.tour_id
            ORDER BY br.id DESC
            """
        ).fetchall()

    return render_template("bookings.html", bookings=rows)


# ---------- Акаунти ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
              AND status = 'ACTIVE'
            """,
            (username,)
        ).fetchone()

    if user is None:
        return "Невалидно потребителско име или парола.", 401

    if not check_password_hash(
        user["password_hash"],
        password
    ):
        return "Невалидно потребителско име или парола.", 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]

    if user["role"] == "public":
        return redirect(url_for("home"))

    return redirect(url_for("admin_tours"))


@app.route("/logout", methods=["POST"])
def logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("home"))


@app.route("/register", methods=["GET", "POST"])
def register_public():
    if request.method == "GET":
        return render_template("register_public.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or "@" not in email or len(password) < 8:
        return "Проверете регистрационните данни.", 400

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, 'public', 'ACTIVE')
                """,
                (
                    username,
                    email,
                    generate_password_hash(password)
                )
            )
    except sqlite3.IntegrityError:
        return "Този username или e-mail вече съществува.", 400

    return redirect(url_for("login"))


@app.route("/operator/register", methods=["GET", "POST"])
def register_operator():
    if request.method == "GET":
        return render_template("register_operator.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or "@" not in email or len(password) < 8:
        return "Проверете регистрационните данни.", 400

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, 'operator', 'PENDING_APPROVAL')
                """,
                (
                    username,
                    email,
                    generate_password_hash(password)
                )
            )
    except sqlite3.IntegrityError:
        return "Този username или e-mail вече съществува.", 400

    return "Регистрацията е получена и очаква одобрение от администратор."


# ---------- Потребители (само admin) ----------

@app.route("/admin/users")
@role_required("admin")
def admin_users():
    with get_connection() as connection:
        users = connection.execute(
            """
            SELECT id, username, email, role, status, created_at
            FROM users
            ORDER BY id
            """
        ).fetchall()

    return render_template("admin_users.html", users=users)


@app.route(
    "/admin/users/<int:user_id>/approve",
    methods=["POST"]
)
@role_required("admin")
def approve_operator(user_id):
    validate_csrf()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET status = 'ACTIVE'
            WHERE id = ?
              AND role = 'operator'
              AND status = 'PENDING_APPROVAL'
            """,
            (user_id,)
        )

    return redirect(url_for("admin_users"))


@app.route("/admin/users/new", methods=["POST"])
@role_required("admin")
def staff_user_create():
    validate_csrf()

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "")

    if role not in ("operator", "admin"):
        return "Невалидна роля.", 400

    if not username or "@" not in email or len(password) < 8:
        return "Проверете данните на потребителя.", 400

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, ?, 'ACTIVE')
                """,
                (
                    username,
                    email,
                    generate_password_hash(password),
                    role
                )
            )
    except sqlite3.IntegrityError:
        return "Този username или e-mail вече съществува.", 400

    return redirect(url_for("admin_users"))


# ---------- Резервации ----------

@app.route("/bookings/new", methods=["POST"])
@role_required("public")
def booking_create():
    validate_csrf()

    public_user_id = session["user_id"]

    customer_name = request.form.get("customer_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    level = request.form.get("level", "").strip()

    try:
        departure_id = int(request.form.get("departure_id", ""))
        participants = int(request.form.get("participants", ""))
    except ValueError:
        return "Невалидни данни.", 400

    if not customer_name or "@" not in email:
        return "Проверете име и e-mail.", 400

    if not phone or not level:
        return "Попълнете телефон и ниво на подготовка.", 400

    if not 1 <= participants <= MAX_PARTICIPANTS:
        return "Участниците трябва да са между 1 и 12.", 400

    with get_connection() as connection:
        departure = connection.execute(
            """
            SELECT *
            FROM tour_departures
            WHERE id = ?
              AND is_active = 1
            """,
            (departure_id,)
        ).fetchone()

        if departure is None:
            return "Заминаването не съществува.", 400

        connection.execute(
            """
            INSERT INTO bookings (
                public_user_id,
                departure_id,
                customer_name,
                email,
                phone,
                level,
                participants,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                public_user_id,
                departure_id,
                customer_name,
                email,
                phone,
                level,
                participants
            )
        )

    return redirect(url_for("my_bookings"))


@app.route("/my/bookings")
@role_required("public")
def my_bookings():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                b.id,
                b.participants,
                b.phone,
                b.level,
                b.status,
                d.departure_date,
                t.name AS tour_name,
                t.location
            FROM bookings AS b
            JOIN tour_departures AS d
              ON d.id = b.departure_id
            JOIN tours AS t
              ON t.id = d.tour_id
            WHERE b.public_user_id = ?
            ORDER BY b.id DESC
            """,
            (session["user_id"],)
        ).fetchall()

    return render_template("my_bookings.html", bookings=rows)


@app.route("/admin/bookings")
@role_required("admin", "operator")
def booking_list():
    query = """
        SELECT
            b.id,
            b.customer_name,
            b.email,
            b.phone,
            b.level,
            b.participants,
            b.status,
            d.departure_date,
            d.capacity,
            t.name AS tour_name,
            t.location,
            t.latitude,
            t.longitude,
            t.map_query,
            t.operator_id
        FROM bookings AS b
        JOIN tour_departures AS d
          ON d.id = b.departure_id
        JOIN tours AS t
          ON t.id = d.tour_id
    """
    params = ()

    if session["role"] == "operator":
        query += " WHERE t.operator_id = ?"
        params = (session["user_id"],)

    query += " ORDER BY b.id DESC"

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    return render_template(
        "admin_bookings.html",
        bookings=rows
    )


def get_booking_with_owner(connection, booking_id):
    return connection.execute(
        """
        SELECT b.*, t.operator_id
        FROM bookings AS b
        JOIN tour_departures AS d
          ON d.id = b.departure_id
        JOIN tours AS t
          ON t.id = d.tour_id
        WHERE b.id = ?
        """,
        (booking_id,)
    ).fetchone()


@app.route(
    "/admin/bookings/<int:booking_id>/confirm",
    methods=["POST"]
)
@role_required("admin", "operator")
def booking_confirm(booking_id):
    validate_csrf()

    with get_connection() as connection:
        booking = get_booking_with_owner(connection, booking_id)

        if booking is None:
            return "Booking не е намерен.", 404

        if not can_manage(booking["operator_id"]):
            abort(403)

        if booking["status"] != "PENDING":
            return "Само PENDING booking може да се потвърди.", 400

        available = get_available_capacity(
            connection,
            booking["departure_id"]
        )

        if available is None:
            return "Departure не е намерен.", 400

        if booking["participants"] > available:
            return "Няма достатъчно свободни места.", 400

        connection.execute(
            """
            UPDATE bookings
            SET status = 'CONFIRMED'
            WHERE id = ?
            """,
            (booking_id,)
        )

    return redirect(url_for("booking_list"))


@app.route(
    "/admin/bookings/<int:booking_id>/cancel",
    methods=["POST"]
)
@role_required("admin", "operator")
def booking_cancel(booking_id):
    validate_csrf()

    with get_connection() as connection:
        booking = get_booking_with_owner(connection, booking_id)

        if booking is None:
            return "Booking не е намерен.", 404

        if not can_manage(booking["operator_id"]):
            abort(403)

        if booking["status"] == "CANCELLED":
            return "Booking вече е отменен.", 400

        connection.execute(
            """
            UPDATE bookings
            SET status = 'CANCELLED'
            WHERE id = ?
            """,
            (booking_id,)
        )

    return redirect(url_for("booking_list"))


# ---------- Оферти (admin и operator) ----------

@app.route("/admin/tours")
@role_required("admin", "operator")
def admin_tours():
    with get_connection() as connection:
        tours = connection.execute(
            "SELECT * FROM tours ORDER BY id"
        ).fetchall()

    return render_template(
        "admin_tours.html",
        tours=tours
    )


@app.route("/admin/tours/new", methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_create():
    if request.method == "GET":
        return render_template("tour_form.html", tour=None)

    validate_csrf()

    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    map_query = request.form.get("map_query", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))

        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = float(latitude_raw) if latitude_raw else None
        longitude = float(longitude_raw) if longitude_raw else None
    except ValueError:
        return "Проверете цена, капацитет и координати.", 400

    if not code or not name or not location or not description:
        return "Всички основни текстови полета са задължителни.", 400

    if price < 0 or capacity < 1:
        return "Невалидна цена или капацитет.", 400

    if session["role"] == "operator":
        operator_id = session["user_id"]
    else:
        operator_raw = request.form.get("operator_id", "").strip()
        operator_id = int(operator_raw) if operator_raw.isdigit() else None

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO tours (
                    operator_id,
                    code, name, location, description,
                    price, capacity,
                    latitude, longitude, map_query,
                    image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operator_id,
                    code, name, location, description,
                    price, capacity,
                    latitude, longitude, map_query,
                    request.form.get("image_url", "").strip()
                )
            )
    except sqlite3.IntegrityError:
        return "Вече има оферта с този code.", 400

    return redirect(url_for("admin_tours"))


@app.route("/admin/tours/<int:tour_id>/edit",
           methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_edit(tour_id):
    with get_connection() as connection:
        tour = connection.execute(
            "SELECT * FROM tours WHERE id = ?",
            (tour_id,)
        ).fetchone()

    if tour is None:
        abort(404)

    if not can_manage(tour["operator_id"]):
        abort(403)

    if request.method == "GET":
        return render_template(
            "tour_form.html",
            tour=tour
        )

    validate_csrf()

    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))

        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = float(latitude_raw) if latitude_raw else None
        longitude = float(longitude_raw) if longitude_raw else None
    except ValueError:
        return "Проверете цена, капацитет и координати.", 400

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tours
            SET name = ?,
                location = ?,
                description = ?,
                price = ?,
                capacity = ?,
                latitude = ?,
                longitude = ?,
                map_query = ?,
                image_url = ?
            WHERE id = ?
            """,
            (
                name, location, description,
                price, capacity,
                latitude, longitude,
                request.form.get("map_query", "").strip(),
                request.form.get("image_url", "").strip(),
                tour_id
            )
        )

    return redirect(url_for("admin_tours"))


@app.route("/admin/tours/<int:tour_id>/deactivate",
           methods=["POST"])
@role_required("admin", "operator")
def tour_deactivate(tour_id):
    validate_csrf()

    with get_connection() as connection:
        tour = connection.execute(
            "SELECT * FROM tours WHERE id = ?",
            (tour_id,)
        ).fetchone()

        if tour is None:
            abort(404)

        if not can_manage(tour["operator_id"]):
            abort(403)

        connection.execute(
            """
            UPDATE tours
            SET is_active = 0
            WHERE id = ?
            """,
            (tour_id,)
        )

    return redirect(url_for("admin_tours"))