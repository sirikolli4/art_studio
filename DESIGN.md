# DESIGN.md

## 1. How do login and the two roles work?

Customers sign up with an email and password. Passwords are stored hashed (never as plain text), and a successful login puts the user's id in a signed session cookie. There is no studio sign-up: the one studio account is created from the seed file (`seed_data/seed.json`) the first time the database is made, and the sign-up route always creates a `customer` whatever the request says.

Every API route goes through one decorator, `require(role)`. On each request it looks the user up in the database and answers 401 if nobody is logged in, 403 if the role is wrong, and otherwise runs the route. Customers only ever read rows filtered by their own `user_id`, and when they act on someone else's record the lookup includes `AND user_id = ?`, so it simply isn't found (404). The page hides buttons by role too, but that is only for convenience; the server is what enforces the rules.

## 2. Which database did you choose, and why?

SQLite. The whole app is one small Flask process, so a file database needs no setup and lets anyone run the project on a clean machine with one command. It still gives me real transactions, `CHECK` constraints and partial unique indexes, which is what keeps paintings and dates safe. The trade-off is that it is single-machine and has one writer at a time, so for several servers I would move to PostgreSQL and keep the same schema and queries.

## 3. How do you stop two people from taking the same painting or date?

I don't check availability and then write, because two requests can both pass the check. Instead the database makes the decision in a single step.

- **Painting:** buying runs `UPDATE paintings SET status='sold' WHERE id=? AND status='available'` inside a transaction and checks how many rows changed. Only one request can change 1 row; everyone else changes 0 and sees "Sorry, this painting was just sold" (409). A unique index also refuses two `placed` orders for one painting as a safety net.
- **Wall date:** a partial unique index allows only one booking in `requested` or `confirmed` status per date. A second insert fails and the user sees "that date was just taken". Declined or cancelled bookings leave the index, so their date becomes free again. The "Already booked" list on the form is only an early hint; the index is the real guard.
- **Status changes** (confirm, cancel, accept and so on) use `UPDATE ... WHERE status IN (...)` the same way, so two clicks at once can't both succeed.

The tests send 10 simultaneous requests for the same painting and for the same date and check that exactly one succeeds.

## 4. What did you finish, what did you leave out, and what would you do next?

**Finished:** everything in the brief. Sign-up, login and logout; the two roles with 401 / 403 / 404 enforced on the server; paintings (browse, studio add and edit while available, buy, cancel); wall bookings (7 to 90 days away, 10 to 500 sq ft, price = size × the seed rate of ₹150, one booking per date, studio confirm or decline, customer cancel until 3 days before); pottery requests (item and glaze from the seed data, quantity 1 to 12, needed-by at least 14 days away, studio accept or decline, customer edit or cancel only while `requested`). The database is filled from the official seed file, including the two paintings that start as sold. Every list has loading, empty and error states, refusals show a clear message, and long titles are handled. 23 automated tests pass, and I clicked through both roles in a real browser.

**Left out (on purpose, per the brief):** payments, password reset, email verification, image uploads, emails or SMS, deployment. A new painting's image is chosen by typing a path to a file already in `static/images`, instead of uploading one.

**Known limits:** the date rules use the calendar day on the server, and the date pickers use the browser's clock, so they agree when both are on the same machine but could differ by a day across time zones. The lists have no pagination.

**Next:** pagination, a calendar picker that greys out booked dates, real image uploads, and moving to PostgreSQL if the app ever needed more than one server.
