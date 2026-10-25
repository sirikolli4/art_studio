# Art Studio

A small full-stack website for an art studio. Customers can buy paintings, book a wall-painting date, and request custom pottery. The studio manages everything from its own login.

**Stack:** Python 3.10+, Flask, SQLite, plain HTML/CSS/JavaScript (no build step, no internet needed at run time: the fonts and paintings are bundled).

## Run it (clean machine)

```bash
git clone <your-repo-url>
cd art-studio

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# optional: open .env and change SECRET_KEY

python app.py
```

Open http://localhost:5000

The database (`studio.db`) is created and filled from `seed_data/seed.json` the first time the app starts. Nothing else to install or configure.

> If you ran an older version of this project before, delete `studio.db` first. The app will tell you if it finds an old one.

## Accounts

| Role | How to get it |
| :-- | :-- |
| **Customer** | Use *Sign up* on the first page. |
| **Studio** | Already created from the seed file: `studio@artstudio.in` / `Studio@123`. There is no studio sign-up, as the brief says. |

## Run the tests

```bash
python -m unittest -v
```

23 tests. They cover the 401 / 403 / 404 rules, every range and date rule from the brief, the cancel windows, the seed data (12 paintings, 2 already sold, 5 pottery items, 6 glazes, ₹150 per sq ft, the studio login), and two concurrency tests: 10 people grabbing the same painting or the same date at once, where exactly one wins.

## Project layout

| Path | What it does |
| :-- | :-- |
| `app.py` | All API routes, role checks and validation |
| `schema.sql` | Tables, plus the unique indexes that prevent double-booking |
| `seed.py` | Reads `seed_data/seed.json` and fills the database |
| `seed_data/seed.json` | The official seed data |
| `static/index.html`, `style.css`, `app.js` | The interface |
| `static/images/` | The twelve painting images from the seed data |
| `static/fonts/` | Barlow Condensed and Montserrat (SIL Open Font License) |
| `test_app.py` | Automated tests |
| `DESIGN.md` | Design decisions and what is and isn't finished |
