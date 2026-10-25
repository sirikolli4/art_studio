"""Creates the tables and fills them from seed_data/seed.json (only if empty).

The studio login, wall rate, paintings, pottery items and glazes all come from
the official seed file, so changing the data never means touching app code.
"""
import json
import os
import sqlite3

from werkzeug.security import generate_password_hash

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "seed_data", "seed.json"), encoding="utf-8") as f:
    DATA = json.load(f)

WALL_RATE_PER_SQFT = DATA["mural"]["ratePerSqFt"]


def _refuse_old_database(conn):
    """An older version of this app made a different paintings table."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(paintings)")]
    if cols and "image_url" not in cols:
        conn.close()
        raise SystemExit(
            "This studio.db was created by an older version of the app.\n"
            "Delete the file studio.db and start the app again."
        )


def run(db_path):
    conn = sqlite3.connect(db_path)
    _refuse_old_database(conn)
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())

    if not conn.execute("SELECT 1 FROM settings WHERE key='wall_rate_per_sqft'").fetchone():
        conn.execute("INSERT INTO settings VALUES ('wall_rate_per_sqft', ?)", (str(WALL_RATE_PER_SQFT),))

    if not conn.execute("SELECT 1 FROM paintings").fetchone():
        conn.executemany(
            "INSERT INTO paintings (title, artist, description, price, image_url, status) VALUES (?,?,?,?,?,?)",
            [(p["title"], p["artist"], p["description"], p["price"], p["imageUrl"], p["status"])
             for p in DATA["paintings"]],
        )
    if not conn.execute("SELECT 1 FROM pottery_items").fetchone():
        conn.executemany("INSERT INTO pottery_items (name) VALUES (?)", [(i["name"],) for i in DATA["potteryItems"]])
    if not conn.execute("SELECT 1 FROM glazes").fetchone():
        conn.executemany("INSERT INTO glazes (name) VALUES (?)", [(g["name"],) for g in DATA["glazes"]])

    # The studio account is seeded, never created through sign-up.
    # STUDIO_EMAIL / STUDIO_PASSWORD in .env are optional overrides.
    if not conn.execute("SELECT 1 FROM users WHERE role='studio'").fetchone():
        account = DATA["studioAccount"]
        email = (os.environ.get("STUDIO_EMAIL") or account["email"]).strip().lower()
        password = os.environ.get("STUDIO_PASSWORD") or account["password"]
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?,?,'studio')",
            (email, generate_password_hash(password)),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    run(os.environ.get("DATABASE_PATH", "studio.db"))
    print("Database ready.")
