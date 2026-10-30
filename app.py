"""EMBER local café demo. Python 3.10+, standard library only."""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MENU = json.loads((ROOT / 'menu.json').read_text(encoding='utf-8-sig'))
ITEMS = {item['id']: item for item in MENU}
DB = Path(os.environ.get('EMBER_DATABASE', ROOT / 'data' / 'ember.sqlite3'))
PIN = os.environ.get('EMBER_KITCHEN_PIN', '1234')
ADMIN_PIN = os.environ.get('EMBER_ADMIN_PIN', '1234')


@contextmanager
def connect():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, staff_until REAL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS payments(
            id TEXT PRIMARY KEY, session TEXT, request_key TEXT, fingerprint TEXT,
            state TEXT, ready REAL, body TEXT, order_id TEXT, UNIQUE(session, request_key));
          CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY, session TEXT, status INTEGER DEFAULT 0, body TEXT);
          CREATE TABLE IF NOT EXISTS waiter(
            id TEXT PRIMARY KEY, session TEXT, table_no INTEGER, created REAL, resolved INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS login_attempts(session TEXT PRIMARY KEY, count INTEGER, reset REAL);
          CREATE TABLE IF NOT EXISTS menu_items(id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cafe_tables(number INTEGER PRIMARY KEY, label TEXT NOT NULL);
        ''')
        con.executemany('INSERT OR IGNORE INTO menu_items VALUES(?,?)',
                        [(item['id'], json.dumps(item)) for item in MENU])
        con.executemany('INSERT OR IGNORE INTO cafe_tables VALUES(?,?)',
                        [(number, f'Table {number}') for number in range(1, 6)])
        columns = {row['name'] for row in con.execute('PRAGMA table_info(sessions)')}
        if 'admin_until' not in columns:
            con.execute('ALTER TABLE sessions ADD COLUMN admin_until REAL DEFAULT 0')


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Problem(f'Expected a whole number from {minimum} to {maximum}.')
    return value


def read_menu():
    with connect() as con:
        return [json.loads(row['body']) for row in con.execute('SELECT body FROM menu_items ORDER BY rowid')]


def menu_item(data):
    result = {}
    for key, limit in [('id', 60), ('name', 100), ('cat', 80), ('desc', 500),
                       ('tag', 60), ('time', 40), ('image', 100)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise Problem(f'{key}: enter between 1 and {limit} characters.')
        result[key] = value.strip()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', result['id']):
        raise Problem('Item ID must use lowercase letters, numbers, and single hyphens.')
    if not re.fullmatch(r'photo-[a-zA-Z0-9-]+', result['image']):
        raise Problem('Enter an Unsplash photo ID, such as photo-1572442388796-11668a67e53d.')
    result['price'] = integer(data.get('price'), 0, 100000)
    if type(data.get('veg')) is not bool:
        raise Problem('Choose whether the item is vegetarian.')
    result['veg'] = data['veg']
    options = data.get('options')
    if not isinstance(options, list) or not 1 <= len(options) <= 12:
        raise Problem('Enter between 1 and 12 options.')
    if any(not isinstance(option, str) or not option.strip() or len(option) > 100 for option in options):
        raise Problem('Each option must contain between 1 and 100 characters.')
    result['options'] = [option.strip() for option in options]
    if len(set(result['options'])) != len(options):
        raise Problem('Options must be unique.')
    return result


def price_order(data):
    items_by_id = {item['id']: item for item in read_menu()}
    table = integer(data.get('table'), 1, 999)
    method = data.get('method')
    if method not in ('UPI', 'Card', 'Wallet'):
        raise Problem('Choose a supported demo payment method.')
    rows = data.get('items')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise Problem('Choose between 1 and 50 order lines.')
    items = []
    for row in rows:
        if not isinstance(row, dict):
            raise Problem('Invalid order item.')
        item_id = row.get('id')
        item = items_by_id.get(item_id) if isinstance(item_id, str) else None
        if not item:
            raise Problem('An item is no longer available.')
        option = row.get('option')
        if option not in item['options']:
            raise Problem('Choose a valid item option.')
        notes = row.get('notes', '')
        if not isinstance(notes, str) or len(notes) > 160:
            raise Problem('Instructions must be 160 characters or fewer.')
        match = re.search(r'₹(\d+)', option)
        price = item['price'] + (int(match[1]) if match else 0)
        items.append(dict(id=item['id'], name=item['name'], option=option, notes=notes,
                          price=price, qty=integer(row.get('qty'), 1, 99)))
    subtotal = sum(i['price'] * i['qty'] for i in items)
    tax = (subtotal * 5 + 50) // 100
    return dict(table=table, method=method, items=items, sub=subtotal, tax=tax,
                total=subtotal + tax, demo=True)


def payment_result(con, payment):
    """Called inside a write transaction; one payment can create only one order."""
    if payment['state'] == 'pending' and time.time() >= payment['ready']:
        order_id = 'EM-' + secrets.token_hex(5).upper()
        order = json.loads(payment['body'])
        order.update(id=order_id, status=0, time=int(time.time() * 1000))
        con.execute('INSERT INTO orders(id, session, body) VALUES(?,?,?)',
                    (order_id, payment['session'], json.dumps(order)))
        con.execute("UPDATE payments SET state='success',order_id=? WHERE id=?", (order_id, payment['id']))
        return dict(id=payment['id'], state='success', order=order)
    result = dict(id=payment['id'], state=payment['state'])
    if payment['order_id']:
        row = con.execute('SELECT * FROM orders WHERE id=?', (payment['order_id'],)).fetchone()
        result['order'] = json.loads(row['body']) | {'status': row['status']}
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'EmberPython/1.0'

    def log_message(self, fmt, *args):
        # Do not log cookies, credentials, or request bodies.
        pass

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            sid = cookie['ember_session'].value if 'ember_session' in cookie else ''
        except Exception:
            sid = ''
        with connect() as con:
            if re.fullmatch(r'[a-f0-9]{64}', sid) and con.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                return sid
            sid = secrets.token_hex(32)
            con.execute('INSERT INTO sessions(id) VALUES(?)', (sid,))
        self.new_cookie = sid
        return sid

    def send(self, value, status=200, kind='application/json; charset=utf-8'):
        payload = json.dumps(value, ensure_ascii=False).encode() if kind.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if getattr(self, 'new_cookie', None):
            self.send_header('Set-Cookie', f'ember_session={self.new_cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000')
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise Problem('JSON requests only.', 415)
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            raise Problem('Cross-origin requests are not allowed.', 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeDecodeError):
            raise Problem('Invalid JSON request.')

    def staff(self, sid, role='kitchen'):
        column = 'admin_until' if role == 'admin' else 'staff_until'
        with connect() as con:
            row = con.execute(f'SELECT {column} FROM sessions WHERE id=?', (sid,)).fetchone()
            if not row or row[column] < time.time():
                raise Problem(f'Enter the {role} PIN to continue.', 401)

    def do_GET(self):
        self.handle_route('GET')

    def do_POST(self):
        self.handle_route('POST')

    def handle_route(self, method):
        self.new_cookie = None
        try:
            path = urlsplit(self.path).path
            if path in ('/admin/', '/kitchen/'):
                path = path.rstrip('/')
            if method == 'GET' and not path.startswith('/api/'):
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/kitchen': ('staff.html', 'text/html; charset=utf-8'),
                         '/admin': ('staff.html', 'text/html; charset=utf-8'),
                         '/staff.js': ('staff.js', 'text/javascript; charset=utf-8'),
                         '/staff.css': ('staff.css', 'text/css; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if path not in files:
                    raise Problem('Page not found.', 404)
                name, kind = files[path]
                return self.send((ROOT / 'static' / name).read_bytes(), kind=kind)
            sid = self.session()
            if method == 'GET' and path == '/api/menu':
                return self.send(read_menu())
            if method == 'GET' and path == '/api/admin/settings':
                self.staff(sid, 'admin')
                with connect() as con:
                    tables = [dict(row) for row in con.execute('SELECT * FROM cafe_tables ORDER BY number')]
                return self.send(dict(menu=read_menu(), tables=tables))
            if method == 'GET' and path == '/api/orders':
                with connect() as con:
                    rows = con.execute('SELECT * FROM orders WHERE session=? ORDER BY rowid DESC', (sid,)).fetchall()
                return self.send([json.loads(r['body']) | {'status': r['status']} for r in rows])
            if method == 'GET' and re.fullmatch('/api/payments/[a-f0-9]{32}', path):
                with connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    row = con.execute('SELECT * FROM payments WHERE id=? AND session=?', (path.split('/')[-1], sid)).fetchone()
                    if not row:
                        raise Problem('Payment not found.', 404)
                    result = payment_result(con, row)
                return self.send(result)
            if method == 'GET' and path == '/api/kitchen/orders':
                self.staff(sid)
                with connect() as con:
                    rows = con.execute('SELECT * FROM orders ORDER BY rowid DESC LIMIT 200').fetchall()
                    requests = con.execute('SELECT id,table_no,created FROM waiter WHERE resolved=0 ORDER BY created').fetchall()
                return self.send(dict(orders=[json.loads(r['body']) | {'status': r['status']} for r in rows], requests=[dict(r) for r in requests]))
            if method == 'GET' and path == '/api/admin/overview':
                self.staff(sid, 'admin')
                with connect() as con:
                    rows = con.execute('SELECT * FROM orders ORDER BY rowid DESC').fetchall()
                    requests = con.execute('SELECT id,table_no,created FROM waiter WHERE resolved=0 ORDER BY created').fetchall()
                orders = [json.loads(r['body']) | {'status': r['status']} for r in rows]
                return self.send(dict(
                    orders=orders[:200], requests=[dict(r) for r in requests],
                    summary=dict(orders=len(orders), total=sum(o['total'] for o in orders),
                                 active=sum(o['status'] < 3 for o in orders),
                                 served=sum(o['status'] == 3 for o in orders))))
            if method != 'POST':
                raise Problem('Not found.', 404)
            data = self.body()
            if path in ('/api/admin/items/add', '/api/admin/items/update'):
                self.staff(sid, 'admin')
                item = menu_item(data)
                with connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    exists = con.execute('SELECT 1 FROM menu_items WHERE id=?', (item['id'],)).fetchone()
                    if path.endswith('/add'):
                        if exists:
                            raise Problem('That item ID is already in use.', 409)
                        con.execute('INSERT INTO menu_items VALUES(?,?)', (item['id'], json.dumps(item)))
                    else:
                        if not exists:
                            raise Problem('Item not found.', 404)
                        con.execute('UPDATE menu_items SET body=? WHERE id=?', (json.dumps(item), item['id']))
                return self.send(item)
            if path == '/api/admin/tables/add':
                self.staff(sid, 'admin')
                number = integer(data.get('number'), 1, 999)
                label = data.get('label', f'Table {number}')
                if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
                    raise Problem('Table name must contain between 1 and 80 characters.')
                with connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    if con.execute('SELECT 1 FROM cafe_tables WHERE number=?', (number,)).fetchone():
                        raise Problem('That table number already exists.', 409)
                    con.execute('INSERT INTO cafe_tables VALUES(?,?)', (number, label.strip()))
                return self.send(dict(number=number, label=label.strip()))
            if path in ('/api/kitchen/logout', '/api/admin/logout'):
                column = 'admin_until' if path == '/api/admin/logout' else 'staff_until'
                with connect() as con:
                    con.execute(f'UPDATE sessions SET {column}=0 WHERE id=?', (sid,))
                return self.send({'ok': True})
            if path in ('/api/kitchen/login', '/api/admin/login'):
                role = 'admin' if path == '/api/admin/login' else 'kitchen'
                column = 'admin_until' if role == 'admin' else 'staff_until'
                pin = ADMIN_PIN if role == 'admin' else PIN
                with connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    attempt = con.execute('SELECT * FROM login_attempts WHERE session=?', (sid,)).fetchone()
                    count = attempt['count'] if attempt and attempt['reset'] > time.time() else 0
                    if count >= 8:
                        raise Problem('Too many attempts. Try again in five minutes.', 429)
                    correct = hmac.compare_digest(str(data.get('pin', '')).encode(), pin.encode())
                    con.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (sid, 0 if correct else count + 1, time.time() + 300))
                    if correct:
                        con.execute(f'UPDATE sessions SET {column}=? WHERE id=?', (time.time() + 28800, sid))
                if not correct:
                    raise Problem('That PIN did not match.', 401)
                return self.send({'ok': True})
            if path == '/api/checkout':
                order = price_order(data)
                key, outcome = data.get('key'), data.get('outcome')
                if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', key):
                    raise Problem('A valid checkout key is required.')
                if outcome not in ('success', 'pending', 'failed'):
                    raise Problem('Invalid demo payment result.')
                fingerprint = hashlib.sha256(json.dumps([order, outcome], sort_keys=True).encode()).hexdigest()
                with connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    row = con.execute('SELECT * FROM payments WHERE session=? AND request_key=?', (sid, key)).fetchone()
                    if row and row['fingerprint'] != fingerprint:
                        raise Problem('This checkout key belongs to a different order.', 409)
                    if not row:
                        pid = secrets.token_hex(16)
                        con.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,NULL)',
                                    (pid, sid, key, fingerprint, 'failed' if outcome == 'failed' else 'pending',
                                     time.time() + (2 if outcome == 'pending' else 0), json.dumps(order)))
                        row = con.execute('SELECT * FROM payments WHERE id=?', (pid,)).fetchone()
                    result = payment_result(con, row)
                return self.send(result)
            if path == '/api/waiter':
                table = integer(data.get('table'), 1, 999)
                with connect() as con:
                    existing = con.execute('SELECT id FROM waiter WHERE session=? AND table_no=? AND resolved=0', (sid, table)).fetchone()
                    if not existing:
                        con.execute('INSERT INTO waiter VALUES(?,?,?,?,0)', (secrets.token_hex(12), sid, table, time.time()))
                return self.send({'ok': True})
            if path == '/api/kitchen/status':
                self.staff(sid)
                status = integer(data.get('status'), 1, 3)
                with connect() as con:
                    cur = con.execute('UPDATE orders SET status=? WHERE id=? AND status=?', (status, str(data.get('id')), status - 1))
                    if not cur.rowcount:
                        raise Problem('Order status already changed. Refresh and try again.', 409)
                return self.send({'ok': True})
            if path == '/api/kitchen/resolve':
                self.staff(sid)
                with connect() as con:
                    con.execute('UPDATE waiter SET resolved=1 WHERE id=?', (str(data.get('id')),))
                return self.send({'ok': True})
            raise Problem('Not found.', 404)
        except Problem as exc:
            self.send({'error': exc.message}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send({'error': 'The server could not complete this request. Please try again.'}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    init_db()
    print(f'EMBER: http://{args.host}:{args.port}/?table=5', flush=True)
    print('Kitchen PIN: use EMBER_KITCHEN_PIN; local demo default is 1234.', flush=True)
    print('Admin: /admin; use EMBER_ADMIN_PIN; local demo default is 1234.', flush=True)
    print('Demo payments only. Press Ctrl+C to stop.', flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
