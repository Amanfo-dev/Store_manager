# Store Manager

A small web app for running a shop: keep track of items and stock, ring up sales from a cart, log expenses, and see how the day, month and year are going. Built because paper ledgers and loose WhatsApp notes stop working the moment a second person helps in the shop.

Flask + SQLite on your laptop, Postgres when it's deployed. The frontend is plain HTML, CSS and a bit of JavaScript, no build step.

## What it does

- **Home**: item table with price and stock, search and sort, and a strip showing today's revenue, expenses and what's left in the till. Hit **Add** on an item to put some in the cart, then open the cart (floating button) and check out. Every checkout becomes an invoice.
- **Add item**: new items with price and starting stock.
- **Price history**: every price change is logged with old price, new price, date and time.
- **Records**: all invoices and expenses in one table. Filter by date range, amount range and type. Open an invoice to see what was bought, then print it or save it as a PDF.
- **Analytics**: income per month, per year and per day (sales minus expenses), plus the year's total revenue and expenditure.
- **Accounts and roles**: admin, manager and employee, with privileges the admin can switch on and off.
- Light, dark or follow-the-system theme. Works on phones, tablets and desktops.

## Accounts, sign-up and roles

**Sign-up is for the shop owner and makes an admin account.** You enter your details, the app emails a 6-digit code to your address, and the account is only created once you type that code in. Everyone else (managers and employees) gets an account from the admin under **Account > Add role users**.

- On a brand-new install, anyone can sign up first, so set `ADMIN_EMAIL` (below) before you share the link. With it set, only the owner's email address can create an admin account, and the owner can always sign up again later if needed.
- Logged-out visitors always see a **Sign up** link on the login page. If they aren't the owner, the page tells them to ask their admin for an account.
- Everyone can change their own password under **Account**.

| | Admin | Manager | Employee |
|---|---|---|---|
| Edit and delete items | yes | yes | no |
| Open Settings | yes | yes | no |
| Change role privileges | yes | yes | no |
| Add new items | yes | yes | no |
| View Analytics | yes | no | no |
| Change other people's roles | managers and employees | employees only | no |
| Create and remove accounts | yes | no | no |

Everything else (selling, expenses, records, price history) is open to everyone. For managers and employees, each privilege above can be toggled in **Settings > Roles**. Admins always have everything. There is no limit on how many accounts you can create.

## Running it locally

You need Python 3.10 or newer.

```bash
git clone <your-repo-url>
cd store-manager
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and sign up. With no email service configured, the 6-digit code is **printed in the terminal** where the app is running, so you can still try the whole flow offline. The SQLite file is created for you in `instance/`.

Good to know while developing:

- Sign-up checks that the email's domain can receive mail (a DNS lookup), so it needs an internet connection. Set `CHECK_EMAIL_DNS=0` to skip that when you're offline.
- If you change the models, delete `instance/store.db` and start again. There are no migrations yet.
- The app uses SQLite whenever `DATABASE_URL` isn't set, and Postgres when it is. Your laptop and the live site never share data.

## Hosting it for free (Render + Neon)

The app runs on **Render** (free web service) and keeps its data in **Neon** (free Postgres that doesn't expire). Neither asks for a card. Render's own free Postgres is deleted after 30 days, which is why the database is on Neon.

### 1. Database on Neon

1. Sign up at [neon.com](https://neon.com) and create a project. Pick a region close to you, and remember it.
2. On the project page, click **Connect**, turn **Connection pooling** off, and copy the connection string. It starts with `postgresql://`.

### 2. Email on Resend

Free hosts block normal SMTP, so the app sends the sign-up code through [Resend](https://resend.com)'s web API.

1. Sign up at Resend and create an API key (it starts with `re_`).
2. Resend's test sender (`onboarding@resend.dev`) can **only email the address you signed up to Resend with**. For a one-owner shop that's enough: sign up to Resend with your own email and use that same email as `ADMIN_EMAIL` below. To email anyone else, verify a domain in Resend and set `MAIL_FROM`.

### 3. The app on Render

1. Push this repo to GitHub.
2. On [render.com](https://render.com), choose **New > Blueprint**, pick the repo, and Render reads `render.yaml`.
3. Fill in the three values it asks for:
   - `DATABASE_URL`: the Neon string from step 1.
   - `ADMIN_EMAIL`: your email (several can be separated with commas).
   - `RESEND_API_KEY`: the key from step 2.
4. Deploy. When it's live, open the `onrender.com` link, click **Sign up**, and check your inbox for the code.

(Prefer clicking through? Create a **Web Service** instead, set the build command to `pip install -r requirements.txt` and the start command to `gunicorn app:app --preload --workers 2 --bind 0.0.0.0:$PORT`, and add the same variables plus a long random `SECRET_KEY`.)

The app refuses to start in production without `SECRET_KEY` and `DATABASE_URL`. That's on purpose: a free host wipes its disk on restart, so running on SQLite there would quietly lose your data.

### What free means here

- **Waking up:** Render's free service goes to sleep after 15 minutes without visitors, and the first page after that takes about a minute. Everyone in the shop can use it at the same time once it's awake. To keep it awake during opening hours, point a free uptime pinger (for example UptimeRobot) at `https://<your-app>.onrender.com/health` every 5 minutes. That page doesn't touch the database, so Neon can still sleep.
- **Hours:** Render gives 750 free instance hours a month, which covers one service running all month.
- **Data:** Neon's free plan has 0.5 GB of storage, plenty for years of shop records. If the database has been idle, the first request after a pause takes an extra moment.
- Plans and limits change, so check [Render's](https://render.com/docs/free) and [Neon's](https://neon.com/pricing) pages.

### Environment variables

| Variable | Required | What it does |
|---|---|---|
| `SECRET_KEY` | yes in production | Signs login sessions. Render generates one for you. |
| `DATABASE_URL` | yes in production | Postgres connection string. Without it the app uses local SQLite. |
| `ADMIN_EMAIL` | strongly advised | Email(s) allowed to sign up as admin, comma-separated. |
| `RESEND_API_KEY` | yes in production | Sends the sign-up code. Without it (locally) the code is printed in the terminal. |
| `MAIL_FROM` | no | Sender address. Defaults to Resend's test sender. |
| `CHECK_EMAIL_DNS` | no | `0` skips the mail-domain check on sign-up. Default `1`. |

Currency and the app name are set at the top of `app.py` (`CURRENCY`, `CURRENCY_CODE`, `APP_NAME`).

## Project layout

```
app.py            routes, auth, roles, invoices, analytics
models.py         database models
templates/        Jinja pages
static/           style.css, app.js (theme, dialogs, cart), charts.js
render.yaml       Render blueprint (web service settings)
Procfile          start command for hosts that read one
.python-version   Python 3.12 on Render
requirements.txt
```

## Known limits

- The emailed code proves the owner controls the address they signed up with. Accounts the admin creates for staff are not email-verified.
- Email checking also does a mail-domain lookup, which can't tell whether a specific inbox exists.
- Prices and totals are stored as floats, which is fine for a small shop but not for real accounting.
- No "forgot password" yet. An admin can remove and recreate a staff account, and the owner can sign up again with an `ADMIN_EMAIL` address.
- Price-change notifications (push to phones and the alert on open) are not built yet.
- Charts load Chart.js from a CDN, so Analytics needs an internet connection.

## Tech

Flask, Flask-SQLAlchemy, psycopg2, gunicorn, email-validator, fpdf2, Chart.js.
