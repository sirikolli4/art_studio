-- Art Studio schema (SQLite)

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('customer', 'studio')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------- Paintings & orders ----------
CREATE TABLE IF NOT EXISTS paintings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    image_url   TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL CHECK (price > 0),
    status      TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'sold'))
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    painting_id INTEGER NOT NULL REFERENCES paintings(id),
    status      TEXT NOT NULL DEFAULT 'placed' CHECK (status IN ('placed', 'cancelled')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Safety net: the database itself refuses two active orders for one painting.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_order_per_painting
    ON orders(painting_id) WHERE status = 'placed';

-- ---------- Wall painting bookings ----------
CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    date       TEXT NOT NULL,            -- ISO date, YYYY-MM-DD
    wall_sqft  INTEGER NOT NULL CHECK (wall_sqft BETWEEN 10 AND 500),
    address    TEXT NOT NULL,
    price      INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'requested'
               CHECK (status IN ('requested', 'confirmed', 'declined', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Safety net: a date can only be held by ONE live booking.
-- Declined / cancelled bookings free the date again.
CREATE UNIQUE INDEX IF NOT EXISTS one_live_booking_per_date
    ON bookings(date) WHERE status IN ('requested', 'confirmed');

-- ---------- Custom pottery ----------
CREATE TABLE IF NOT EXISTS pottery_items (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS glazes (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS pottery_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    item_id    INTEGER NOT NULL REFERENCES pottery_items(id),
    glaze_id   INTEGER NOT NULL REFERENCES glazes(id),
    quantity   INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 12),
    needed_by  TEXT NOT NULL,            -- ISO date
    status     TEXT NOT NULL DEFAULT 'requested'
               CHECK (status IN ('requested', 'accepted', 'declined', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
