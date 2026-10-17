# Store Manager

A small web app for running a shop: keep track of items and stock, ring up sales from a cart, log expenses, and see how the day, month and year are going.

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


## Tech

Flask, Flask-SQLAlchemy, psycopg2, gunicorn, email-validator, fpdf2, Chart.js.
