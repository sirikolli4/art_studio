"""Run with:  python -m unittest -v"""
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, timedelta

# Use a throwaway database; must be set BEFORE importing the app.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "test.db")

import app as studio  # noqa: E402

DB = os.environ["DATABASE_PATH"]


def in_days(n):
    return (date.today() + timedelta(days=n)).isoformat()


def client(email=None, password="secret123", as_studio=False):
    c = studio.app.test_client()
    if as_studio:
        # the studio account comes from seed_data/seed.json
        r = c.post("/api/login", json={"email": "studio@artstudio.in", "password": "Studio@123"})
        assert r.status_code == 200
    elif email:
        c.post("/api/signup", json={"email": email, "password": password})
    return c


class StudioTests(unittest.TestCase):
    def setUp(self):
        # fresh data for every test (keep the seeded catalog + studio account)
        conn = sqlite3.connect(DB)
        conn.executescript("DELETE FROM orders; DELETE FROM bookings; DELETE FROM pottery_requests; DELETE FROM paintings WHERE id > 12; "
                           "DELETE FROM users WHERE role='customer'; "
                           "UPDATE paintings SET status = CASE WHEN id IN (4, 9) THEN 'sold' ELSE 'available' END;")
        conn.commit()
        conn.close()
        self.staff = client(as_studio=True)
        self.alice = client("alice@test.com")
        self.bob = client("bob@test.com")

    # ---- auth / RBAC --------------------------------------------------
    def test_not_logged_in_is_401(self):
        c = studio.app.test_client()
        for path in ["/api/paintings", "/api/orders", "/api/bookings", "/api/pottery"]:
            self.assertEqual(c.get(path).status_code, 401, path)
        self.assertEqual(c.post("/api/orders", json={"painting_id": 1}).status_code, 401)

    def test_wrong_role_is_403(self):
        self.assertEqual(self.alice.post("/api/paintings", json={"title": "x", "price": 5}).status_code, 403)
        self.assertEqual(self.alice.post("/api/bookings/1/confirm").status_code, 403)
        self.assertEqual(self.alice.post("/api/pottery/1/accept").status_code, 403)
        self.assertEqual(self.staff.post("/api/orders", json={"painting_id": 1}).status_code, 403)
        self.assertEqual(self.staff.post("/api/bookings", json={}).status_code, 403)
        self.assertEqual(self.staff.post("/api/pottery", json={}).status_code, 403)

    def test_signup_cannot_make_studio(self):
        c = studio.app.test_client()
        r = c.post("/api/signup", json={"email": "evil@test.com", "password": "secret123", "role": "studio"})
        self.assertEqual(r.get_json()["user"]["role"], "customer")

    def test_other_customers_record_is_404(self):
        oid = self.alice.post("/api/orders", json={"painting_id": 1}).get_json()["id"]
        self.assertEqual(self.bob.post(f"/api/orders/{oid}/cancel").status_code, 404)
        bid = self.alice.post("/api/bookings", json={"date": in_days(20), "wall_sqft": 50, "address": "x"}).get_json()["id"]
        self.assertEqual(self.bob.post(f"/api/bookings/{bid}/cancel").status_code, 404)
        self.assertEqual(self.bob.get("/api/orders").get_json(), [])

    def test_customers_only_see_their_own_lists_studio_sees_all(self):
        self.alice.post("/api/orders", json={"painting_id": 1})
        self.bob.post("/api/orders", json={"painting_id": 2})
        self.assertEqual(len(self.alice.get("/api/orders").get_json()), 1)
        self.assertEqual(len(self.staff.get("/api/orders").get_json()), 2)

    # ---- paintings ----------------------------------------------------
    def test_buy_twice_and_cancel_frees_painting(self):
        self.assertEqual(self.alice.post("/api/orders", json={"painting_id": 1}).status_code, 201)
        self.assertEqual(self.bob.post("/api/orders", json={"painting_id": 1}).status_code, 409)
        oid = self.alice.get("/api/orders").get_json()[0]["id"]
        self.assertEqual(self.alice.post(f"/api/orders/{oid}/cancel").status_code, 200)
        self.assertEqual(self.alice.post(f"/api/orders/{oid}/cancel").status_code, 409)  # already cancelled
        self.assertEqual(self.bob.post("/api/orders", json={"painting_id": 1}).status_code, 201)

    def test_buy_unknown_painting_is_404(self):
        self.assertEqual(self.alice.post("/api/orders", json={"painting_id": 9999}).status_code, 404)

    def test_studio_edit_only_while_available(self):
        edit = {"title": "New", "price": 99, "description": ""}
        self.assertEqual(self.staff.put("/api/paintings/1", json=edit).status_code, 200)
        self.alice.post("/api/orders", json={"painting_id": 1})
        self.assertEqual(self.staff.put("/api/paintings/1", json=edit).status_code, 409)
        self.assertEqual(self.staff.put("/api/paintings/9999", json=edit).status_code, 404)

    def test_concurrent_buys_only_one_wins(self):
        clients = [client(f"racer{i}@test.com") for i in range(10)]
        results, barrier = [], threading.Barrier(len(clients))

        def go(c):
            barrier.wait()
            results.append(c.post("/api/orders", json={"painting_id": 3}).status_code)

        threads = [threading.Thread(target=go, args=(c,)) for c in clients]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [201] + [409] * 9)

    # ---- wall bookings -----------------------------------------------
    def test_booking_validation(self):
        def book(**kw):
            data = {"date": in_days(20), "wall_sqft": 50, "address": "12 Main St"}
            data.update(kw)
            return self.alice.post("/api/bookings", json=data).status_code
        self.assertEqual(book(date=in_days(6)), 400)
        self.assertEqual(book(date=in_days(91)), 400)
        self.assertEqual(book(wall_sqft=9), 400)
        self.assertEqual(book(wall_sqft=501), 400)
        self.assertEqual(book(address=" "), 400)
        self.assertEqual(book(date="not-a-date"), 400)
        self.assertEqual(book(date=in_days(7)), 201)
        self.assertEqual(book(date=in_days(90)), 201)

    def test_booking_price_and_date_uniqueness(self):
        r = self.alice.post("/api/bookings", json={"date": in_days(30), "wall_sqft": 100, "address": "a"})
        self.assertEqual(r.get_json()["price"], 100 * studio.seed.WALL_RATE_PER_SQFT)
        self.assertEqual(self.bob.post("/api/bookings", json={"date": in_days(30), "wall_sqft": 20, "address": "b"}).status_code, 409)

    def test_declined_or_cancelled_booking_frees_the_date(self):
        bid = self.alice.post("/api/bookings", json={"date": in_days(30), "wall_sqft": 20, "address": "a"}).get_json()["id"]
        self.assertEqual(self.staff.post(f"/api/bookings/{bid}/decline").status_code, 200)
        self.assertEqual(self.staff.post(f"/api/bookings/{bid}/confirm").status_code, 409)  # already decided
        self.assertEqual(self.bob.post("/api/bookings", json={"date": in_days(30), "wall_sqft": 20, "address": "b"}).status_code, 201)

    def test_concurrent_bookings_same_date_only_one_wins(self):
        clients = [client(f"booker{i}@test.com") for i in range(10)]
        results, barrier = [], threading.Barrier(len(clients))

        def go(c):
            barrier.wait()
            results.append(c.post("/api/bookings", json={"date": in_days(45), "wall_sqft": 20, "address": "a"}).status_code)

        threads = [threading.Thread(target=go, args=(c,)) for c in clients]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [201] + [409] * 9)

    def test_booking_cancel_window(self):
        bid = self.alice.post("/api/bookings", json={"date": in_days(20), "wall_sqft": 20, "address": "a"}).get_json()["id"]
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE bookings SET date=? WHERE id=?", (in_days(2), bid))  # 2 days away: too late
        conn.commit()
        self.assertEqual(self.alice.post(f"/api/bookings/{bid}/cancel").status_code, 409)
        conn.execute("UPDATE bookings SET date=? WHERE id=?", (in_days(3), bid))  # exactly 3 days: allowed
        conn.commit()
        conn.close()
        self.assertEqual(self.alice.post(f"/api/bookings/{bid}/cancel").status_code, 200)

    # ---- pottery -----------------------------------------------------
    def pottery(self, **kw):
        data = {"item_id": 1, "glaze_id": 1, "quantity": 2, "needed_by": in_days(20)}
        data.update(kw)
        return data

    def test_pottery_validation(self):
        post = lambda **kw: self.alice.post("/api/pottery", json=self.pottery(**kw)).status_code
        self.assertEqual(post(quantity=0), 400)
        self.assertEqual(post(quantity=13), 400)
        self.assertEqual(post(needed_by=in_days(13)), 400)
        self.assertEqual(post(item_id=9999), 400)
        self.assertEqual(post(glaze_id=9999), 400)
        self.assertEqual(post(needed_by=in_days(14), quantity=12), 201)

    def test_pottery_edit_cancel_only_while_requested(self):
        rid = self.alice.post("/api/pottery", json=self.pottery()).get_json()["id"]
        self.assertEqual(self.alice.put(f"/api/pottery/{rid}", json=self.pottery(quantity=5)).status_code, 200)
        self.assertEqual(self.bob.put(f"/api/pottery/{rid}", json=self.pottery()).status_code, 404)
        self.assertEqual(self.staff.post(f"/api/pottery/{rid}/accept").status_code, 200)
        self.assertEqual(self.alice.put(f"/api/pottery/{rid}", json=self.pottery()).status_code, 409)
        self.assertEqual(self.alice.post(f"/api/pottery/{rid}/cancel").status_code, 409)

    def test_studio_cannot_cancel_or_edit_customer_records(self):
        oid = self.alice.post("/api/orders", json={"painting_id": 1}).get_json()["id"]
        bid = self.alice.post("/api/bookings", json={"date": in_days(20), "wall_sqft": 20, "address": "a"}).get_json()["id"]
        rid = self.alice.post("/api/pottery", json=self.pottery()).get_json()["id"]
        self.assertEqual(self.staff.post(f"/api/orders/{oid}/cancel").status_code, 403)
        self.assertEqual(self.staff.post(f"/api/bookings/{bid}/cancel").status_code, 403)
        self.assertEqual(self.staff.post(f"/api/pottery/{rid}/cancel").status_code, 403)
        self.assertEqual(self.staff.put(f"/api/pottery/{rid}", json=self.pottery()).status_code, 403)

    # ---- real seed data ------------------------------------------------
    def test_seed_data_is_loaded(self):
        paintings = self.alice.get("/api/paintings").get_json()
        self.assertEqual(len(paintings), 12)
        self.assertEqual(sorted(p["id"] for p in paintings if p["status"] == "sold"), [4, 9])
        self.assertEqual(paintings[0]["image_url"], "images/p-001.jpg")
        cat = self.alice.get("/api/catalog").get_json()
        self.assertEqual((len(cat["items"]), len(cat["glazes"]), cat["wall_rate_per_sqft"]), (5, 6, 150))

    def test_studio_account_from_seed_file_can_log_in(self):
        c = studio.app.test_client()
        r = c.post("/api/login", json={"email": "studio@artstudio.in", "password": "Studio@123"})
        self.assertEqual(r.get_json()["user"]["role"], "studio")

    def test_sold_seed_painting_cannot_be_bought(self):
        self.assertEqual(self.alice.post("/api/orders", json={"painting_id": 4}).status_code, 409)

    def test_booked_dates_only_lists_live_bookings(self):
        self.alice.post("/api/bookings", json={"date": in_days(20), "wall_sqft": 20, "address": "a"})
        b = self.alice.post("/api/bookings", json={"date": in_days(21), "wall_sqft": 20, "address": "a"}).get_json()["id"]
        self.staff.post(f"/api/bookings/{b}/decline")
        self.assertEqual(self.bob.get("/api/booked-dates").get_json(), [in_days(20)])
        self.assertEqual(studio.app.test_client().get("/api/booked-dates").status_code, 401)

    def test_painting_image_url_validation(self):
        add = lambda url: self.staff.post("/api/paintings", json={"title": "t", "price": 10, "image_url": url}).status_code
        self.assertEqual(add("images/p-013.jpg"), 201)
        self.assertEqual(add("https://example.com/a.jpg"), 201)
        self.assertEqual(add("javascript:alert(1)"), 400)
        self.assertEqual(add("images/../secret.txt"), 400)

    def test_editing_a_painting_keeps_its_image_and_artist(self):
        self.staff.put("/api/paintings/1", json={"title": "Renamed", "price": 100})
        p = [x for x in self.alice.get("/api/paintings").get_json() if x["id"] == 1][0]
        self.assertEqual((p["title"], p["image_url"], p["artist"]), ("Renamed", "images/p-001.jpg", "Meera Kumari"))


if __name__ == "__main__":
    unittest.main()
