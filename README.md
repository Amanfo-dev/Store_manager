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

## Roles

| | Admin | Manager | Employee |
|---|---|---|---|
| Edit and delete items | yes | yes | no |
| Open Settings | yes | yes | no |
| Change role privileges | yes | yes | no |
| Add new items | yes | yes | no |
| View Analytics | yes | no | no |
| Change other people's roles | managers and employees | employees only | no |
| Create and remove accounts | yes | no | no |

Everything else (selling, expenses, records, price history) is open to everyone. For managers and employees, each privilege above can be toggled in **Settings > Roles**. Admins always have everything.

The very first person to open the app signs up and becomes the admin. After that sign-up closes, and the admin creates everyone else from **Account > Add role users**.

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

Open http://127.0.0.1:5000 and create the admin account. The SQLite file is created for you in `instance/`.

Two things worth knowing while developing:

- Sign-up checks that the email's domain can actually receive mail (a DNS lookup), so you need an internet connection. Set `CHECK_EMAIL_DNS=0` to turn that off when you're offline.
- If you change the models later, delete `instance/store.db` and start again. There are no migrations yet.


## Project layout

```
app.py            routes, auth, roles, invoices, analytics
models.py         database models
templates/        Jinja pages
static/           style.css, app.js (theme, dialogs, cart), charts.js
Procfile          how Railway starts the app
requirements.txt
```

## Known limits

- Email checking is format plus a mail-domain lookup. It does not send a confirmation link, so it can't prove someone owns the mailbox.
- Prices and totals are stored as floats, which is fine for a small shop but not for real accounting.
- No password reset yet. An admin can remove and recreate an account.
- Price-change notifications (push to phones and the alert on open) are not built yet.
- Charts load Chart.js from a CDN, so Analytics needs an internet connection.

## Tech

Flask, Flask-SQLAlchemy, gunicorn, email-validator, fpdf2, Chart.js.
