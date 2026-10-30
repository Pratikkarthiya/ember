# EMBER café — Python edition

A working Python + SQLite café ordering demo with the original EMBER design.
Requires Python 3.10 or newer. No third-party Python packages are required.

## Hosting the website

### Deploy on Render

[Deploy EMBER to Render](https://render.com/deploy?repo=https://github.com/Pratikkarthiya/ember)

Sign in, review the Blueprint, enter private kitchen and admin PINs, and confirm
the deployment. The Blueprint uses Render's native Python runtime, a paid Starter
web service, and a 1 GB persistent disk for orders. Review Render's displayed
price before deploying. The free tier does not support this persistent disk.
Render assigns the public website URL after deployment; use the URL shown in
the service dashboard. Automatic deployments are disabled; deploy future updates
from Render after testing them.

### Other Docker hosts

The included `Dockerfile` runs the complete Python application. Connect this
repository to a Docker-capable web host, expose its `PORT` environment variable,
and attach a persistent disk at `/data`. The SQLite database is stored at
`/data/ember.sqlite3`; keep a single running instance sharing that disk.

Set private `EMBER_KITCHEN_PIN` and `EMBER_ADMIN_PIN` environment variables in the
host's dashboard before exposing the site. Use the host's HTTPS public URL for
customers, `/kitchen` for kitchen staff, and `/admin` for administration.
Do not commit the database or private PINs. This remains a demo with simulated
payments; the host must provide HTTPS. GitHub Pages cannot run this Python server.

## Start

Extract the project ZIP, open a terminal in this folder, and run:

```sh
python app.py
```

On Windows, `py app.py` also works when the Python launcher is installed.
Open http://127.0.0.1:8000/?table=5 in your browser. Keep the terminal open.

## Try the complete flow

1. Browse the menu and customise an item.
2. Review the cart and choose a demo payment result.
3. Only successful demo payments create kitchen orders. Failed payments keep the cart.
4. Open `/kitchen` and enter the local demo PIN `2468`.
5. Advance Paid → Preparing → Ready → Served. Customer order screens refresh every five seconds.
6. Select Call your waiter. Staff can mark that table request attended in the kitchen.
7. Open `/admin` and enter the local demo admin PIN `1357` to see all-time demo
   sales, active and served order counts, recent orders, and outstanding waiter requests.

Kitchen and Admin are separate dashboards, linked in the customer menu footer.
The kitchen handles preparation, serving, and waiter requests. The single admin
login manages menu items, prices, and tables alongside the café overview. In
Admin, choose a menu item, change its fields, and select Save changes; choose
Add a new item to create a dish. Add tables by number and copy their ordering links.
Menu edits and tables persist in SQLite and apply without restarting the server.
Customers refresh the menu to see changes; checkout refreshes prices and asks them
to review changed totals. Existing paid orders keep their original names and prices.
Each dashboard has its own sign-out;
signing into one role does not grant access to the other role's APIs.

Orders, payment attempts, sessions, and waiter requests persist in `data/ember.sqlite3`.
Each customer browser has its own order history. Kitchen staff can see orders from all devices.
The server calculates prices from `menu.json`; submitted client prices are ignored.
Checkout retries reuse a unique key to avoid duplicate orders.

## Table links and other devices

Change the URL's table number: `/?table=1`, `/?table=2`, etc., up to table 999.
Use these links as the destinations of printed table QR codes.

To use phones and a kitchen device on the same trusted Wi-Fi:

```sh
python app.py --host 0.0.0.0 --port 8000
```

On each device open `http://YOUR-COMPUTER-LAN-IP:8000/?table=5`.
Use the computer's actual Wi-Fi IP address, not `0.0.0.0` or `127.0.0.1`.
The host firewall may need to allow Python on your private network.
All devices must connect to the same running Python server.

Set a different staff PIN before starting, for example in Windows PowerShell:

```powershell
$env:EMBER_KITCHEN_PIN = 'your-own-long-pin'
$env:EMBER_ADMIN_PIN = 'your-own-admin-pin'
python app.py --host 0.0.0.0
```

Kitchen and admin logins last eight hours. Restart with a different PIN does not revoke existing
staff sessions until they expire. This PIN and the built-in HTTP server are for a local demo.

## Files

- `app.py`: Python HTTP server, checkout validation, session handling, SQLite storage, staff APIs.
- `menu.json`: dish details, prices, categories, options and images.
- `static/index.html`, `static/style.css`, `static/app.js`: responsive browser interface.
- `static/staff.html`, `static/staff.css`, `static/staff.js`: separate kitchen and admin dashboard views.
- `test_app.py`: integration tests using a separate temporary database.
- `requirements.txt`: explains the zero-dependency runtime.

Run backend checks with `python -m unittest -v test_app` and interface state checks
with `node --test test_ui.js` (Node.js is needed only for these interface checks).

The interface uses a warm glass design: a floating translucent header, a wide
photographic welcome, frosted menu cards, and a sticky order panel on desktop.
Phones use a two-column menu and a floating cart; ordering dialogs open as bottom
sheets. Admin and Kitchen share the glass surfaces, burgundy accents, and serif
headings. Reduced-motion preferences are respected, with opaque surface fallbacks
for browsers that do not support backdrop blur.

The zero-build Python app loads daisyUI 5 and Tailwind CSS 4 from jsDelivr. Custom
EMBER layout and theme styles are served locally. Existing badge, progress, and
order status classes use distinct names to avoid daisyUI component collisions.
The local daisyUI authoring guides live in `skills/daisyui/`.

The admin sidebar separates Overview, Menu & prices, Tables & links, Order ledger,
and Service calls without resetting editor drafts. The kitchen uses four columns
for Paid, Preparing, Ready, and Served tickets; on phones, swipe across the board.

## Demo scope

Payments are simulations. No money is collected and no card or UPI credentials are requested.
The 5% tax line is illustrative, not configured for a specific business.
Menu photos and fonts require internet access.
QR links identify a table but do not verify physical presence at that table.
This project has no QR image generator. Use the ordering links in Admin as the
destinations of printed QR codes. `menu.json` seeds the initial menu; manage saved
items through Admin after first startup. Tables 1–5 are registered initially;
existing table links from 1–999 continue to work.

For commercial use, connect a real payment provider with verified server callbacks,
replace demo payment controls, configure actual taxes, add production authentication,
and host behind HTTPS with an appropriate production server.
The previously published Sites URL remains the original browser-only demo; it cannot run this Python server.
