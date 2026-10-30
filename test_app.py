import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import app


class CafeFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=app.ROOT)
        app.DB = Path(cls.tmp.name) / 'test.sqlite3'
        app.PIN = 'test-pin'
        app.ADMIN_PIN = 'admin-test-pin'
        app.init_db()
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def client(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, client, path, data=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={'Content-Type': 'application/json'} if data is not None else {})
        try:
            with client.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def payload(self, key, outcome='success'):
        return dict(table=12, method='UPI', outcome=outcome, key=key,
                    items=[dict(id='cappuccino', qty=2, option='Oat milk +₹40', notes='No sugar', price=1)])

    def test_complete_flow_and_customer_isolation(self):
        customer, other, staff = self.client(), self.client(), self.client()
        self.assertEqual(self.request(staff, '/api/kitchen/orders')[0], 401)
        self.assertEqual(self.request(staff, '/api/kitchen/login', {'pin': 'wrong'})[0], 401)
        self.assertEqual(self.request(staff, '/api/kitchen/login', {'pin': 'test-pin'})[0], 200)
        payload = self.payload('checkout-flow-00001')
        code, paid = self.request(customer, '/api/checkout', payload)
        self.assertEqual(code, 200)
        order = paid['order']
        self.assertEqual((order['sub'], order['tax'], order['total']), (440, 22, 462))
        self.assertEqual(self.request(customer, '/api/checkout', payload)[1]['order']['id'], order['id'])
        self.assertEqual(self.request(other, '/api/orders')[1], [])
        self.assertEqual(self.request(other, '/api/payments/' + paid['id'])[0], 404)
        self.assertEqual(self.request(other, '/api/kitchen/status', {'id': order['id'], 'status': 1})[0], 401)
        self.assertEqual(self.request(staff, '/api/kitchen/status', {'id': order['id'], 'status': 2})[0], 409)
        for status in (1, 2, 3):
            self.assertEqual(self.request(staff, '/api/kitchen/status', {'id': order['id'], 'status': status})[0], 200)
        self.assertEqual(self.request(customer, '/api/orders')[1][0]['status'], 3)
        app.init_db()  # Reinitializing the application must preserve saved records.
        self.assertEqual(self.request(customer, '/api/orders')[1][0]['id'], order['id'])

    def test_failed_and_pending_payment_gating(self):
        customer = self.client()
        failed = self.request(customer, '/api/checkout', self.payload('checkout-failed-001', 'failed'))[1]
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(self.request(customer, '/api/orders')[1], [])
        pending = self.request(customer, '/api/checkout', self.payload('checkout-pending-01', 'pending'))[1]
        self.assertEqual(pending['state'], 'pending')
        self.assertEqual(self.request(customer, '/api/orders')[1], [])
        with app.connect() as con:
            con.execute('UPDATE payments SET ready=0 WHERE id=?', (pending['id'],))
        result = self.request(customer, '/api/payments/' + pending['id'])[1]
        self.assertEqual(result['state'], 'success')
        self.assertEqual(self.request(customer, '/api/payments/' + pending['id'])[1]['order']['id'], result['order']['id'])
        self.assertEqual(len(self.request(customer, '/api/orders')[1]), 1)

    def test_validation_key_conflict_and_waiter_request(self):
        customer, staff = self.client(), self.client()
        data = self.payload('checkout-validate-01')
        data['items'][0]['qty'] = -1
        self.assertEqual(self.request(customer, '/api/checkout', data)[0], 400)
        data = self.payload('checkout-validate-01')
        self.assertEqual(self.request(customer, '/api/checkout', data)[0], 200)
        data['table'] = 13
        self.assertEqual(self.request(customer, '/api/checkout', data)[0], 409)
        for _ in range(2):
            self.assertEqual(self.request(customer, '/api/waiter', {'table': 12})[0], 200)
        self.request(staff, '/api/kitchen/login', {'pin': 'test-pin'})
        requests = self.request(staff, '/api/kitchen/orders')[1]['requests']
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.request(staff, '/api/kitchen/resolve', {'id': requests[0]['id']})[0], 200)
        self.assertEqual(self.request(staff, '/api/kitchen/orders')[1]['requests'], [])

    def test_static_files_and_private_database(self):
        client = self.client()
        for path in ('/', '/app.js', '/style.css', '/kitchen', '/admin', '/staff.js', '/staff.css'):
            with client.open(self.base + path) as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(self.request(client, '/data/ember.sqlite3')[0], 404)
        req = urllib.request.Request(self.base + '/api/waiter', data=b'{"table":5}',
                                     headers={'Content-Type': 'application/json', 'Origin': 'https://other.example'})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            client.open(req)
        self.assertEqual(raised.exception.code, 403)
        raised.exception.close()

    def test_admin_overview_role_isolation_and_logout(self):
        customer, kitchen, admin = self.client(), self.client(), self.client()
        self.assertEqual(self.request(customer, '/api/admin/overview')[0], 401)
        self.assertEqual(self.request(admin, '/api/admin/login', {'pin': 'test-pin'})[0], 401)
        self.assertEqual(self.request(kitchen, '/api/kitchen/login', {'pin': 'admin-test-pin'})[0], 401)
        self.assertEqual(self.request(kitchen, '/api/kitchen/login', {'pin': 'test-pin'})[0], 200)
        self.assertEqual(self.request(kitchen, '/api/admin/overview')[0], 401)
        self.assertEqual(self.request(admin, '/api/admin/login', {'pin': 'admin-test-pin'})[0], 200)
        self.assertEqual(self.request(admin, '/api/kitchen/orders')[0], 401)
        before = self.request(admin, '/api/admin/overview')[1]['summary']
        paid = self.request(customer, '/api/checkout', self.payload('admin-overview-0001'))[1]['order']
        self.request(customer, '/api/waiter', {'table': 99})
        code, overview = self.request(admin, '/api/admin/overview')
        self.assertEqual(code, 200)
        self.assertEqual(overview['summary']['orders'], before['orders'] + 1)
        self.assertEqual(overview['summary']['total'], before['total'] + paid['total'])
        self.assertEqual(overview['summary']['active'], before['active'] + 1)
        self.assertEqual(overview['orders'][0]['id'], paid['id'])
        self.assertTrue(any(r['table_no'] == 99 for r in overview['requests']))
        for request in overview['requests']:
            if request['table_no'] == 99:
                self.request(kitchen, '/api/kitchen/resolve', {'id': request['id']})
        self.assertEqual(self.request(admin, '/api/kitchen/status', {'id': paid['id'], 'status': 1})[0], 401)
        for status in (1, 2, 3):
            self.assertEqual(self.request(kitchen, '/api/kitchen/status', {'id': paid['id'], 'status': status})[0], 200)
        after = self.request(admin, '/api/admin/overview')[1]['summary']
        self.assertEqual(after['served'], before['served'] + 1)
        self.assertEqual(after['active'], before['active'])
        # A browser can hold both roles; signing out revokes only the selected role.
        self.request(admin, '/api/kitchen/login', {'pin': 'test-pin'})
        self.assertEqual(self.request(admin, '/api/admin/logout', {})[0], 200)
        self.assertEqual(self.request(admin, '/api/admin/overview')[0], 401)
        self.assertEqual(self.request(admin, '/api/kitchen/orders')[0], 200)
        self.assertEqual(self.request(admin, '/api/kitchen/logout', {})[0], 200)
        self.assertEqual(self.request(admin, '/api/kitchen/orders')[0], 401)

    def test_admin_session_expiry_and_existing_database_migration(self):
        admin = self.client()
        self.request(admin, '/api/admin/login', {'pin': 'admin-test-pin'})
        with app.connect() as con:
            con.execute('UPDATE sessions SET admin_until=0')
        self.assertEqual(self.request(admin, '/api/admin/overview')[0], 401)
        original = app.DB
        try:
            app.DB = Path(self.tmp.name) / 'legacy.sqlite3'
            with app.connect() as con:
                con.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY, staff_until REAL DEFAULT 0)')
                con.execute("INSERT INTO sessions VALUES('saved-session', 123)")
            app.init_db()
            app.init_db()
            with app.connect() as con:
                row = con.execute("SELECT * FROM sessions WHERE id='saved-session'").fetchone()
                self.assertEqual(row['staff_until'], 123)
                self.assertEqual(row['admin_until'], 0)
        finally:
            app.DB = original

    def test_admin_menu_editing_prices_and_persistence(self):
        admin, customer, kitchen = self.client(), self.client(), self.client()
        item = dict(id='admin-test-tea', name='Garden tea', price=90, cat='Tea',
                    veg=True, tag='NEW', desc='Fresh mint tea.',
                    image='photo-1572442388796-11668a67e53d', time='5 MIN',
                    options=['Regular', 'Large +\u20b920'])
        self.assertEqual(self.request(customer, '/api/admin/settings')[0], 401)
        self.assertEqual(self.request(customer, '/api/admin/items/add', item)[0], 401)
        self.request(kitchen, '/api/kitchen/login', {'pin': 'test-pin'})
        self.assertEqual(self.request(kitchen, '/api/admin/items/add', item)[0], 401)
        self.request(admin, '/api/admin/login', {'pin': 'admin-test-pin'})
        self.assertEqual(self.request(admin, '/api/admin/items/add', item)[0], 200)
        self.assertEqual(self.request(admin, '/api/admin/items/add', item)[0], 409)
        self.assertIn(item, self.request(customer, '/api/menu')[1])
        payload = dict(table=76, method='UPI', outcome='success', key='new-menu-item-00001',
                       items=[dict(id=item['id'], qty=2, option=item['options'][1], price=1)])
        paid = self.request(customer, '/api/checkout', payload)[1]['order']
        self.assertEqual(paid['sub'], 220)
        item.update(price=120, name='Fresh garden tea', desc='Mint and lemon tea.')
        self.assertEqual(self.request(admin, '/api/admin/items/update', item)[0], 200)
        payload['key'] = 'new-menu-item-00002'
        new_order = self.request(customer, '/api/checkout', payload)[1]['order']
        self.assertEqual(new_order['sub'], 280)
        self.assertEqual(new_order['items'][0]['name'], item['name'])
        orders = self.request(customer, '/api/orders')[1]
        old = next(order for order in orders if order['id'] == paid['id'])
        self.assertEqual(old['sub'], 220)
        self.assertEqual(old['items'][0]['name'], 'Garden tea')
        app.init_db()
        self.assertIn(item, self.request(admin, '/api/admin/settings')[1]['menu'])
        for changes in [dict(price=-1), dict(price=1.5), dict(name=''), dict(veg='yes'),
                        dict(options=[]), dict(image='javascript:alert(1)'), dict(id='../bad')]:
            self.assertEqual(self.request(admin, '/api/admin/items/update', item | changes)[0], 400)
        self.assertEqual(self.request(admin, '/api/admin/items/update', item | {'id':'missing-item'})[0], 404)

    def test_admin_table_creation_and_ordering_link(self):
        admin, customer, kitchen = self.client(), self.client(), self.client()
        table = dict(number=76, label='Garden table')
        self.assertEqual(self.request(customer, '/api/admin/tables/add', table)[0], 401)
        self.request(kitchen, '/api/kitchen/login', {'pin': 'test-pin'})
        self.assertEqual(self.request(kitchen, '/api/admin/tables/add', table)[0], 401)
        self.request(admin, '/api/admin/login', {'pin': 'admin-test-pin'})
        self.assertEqual(self.request(admin, '/api/admin/tables/add', table)[0], 200)
        self.assertEqual(self.request(admin, '/api/admin/tables/add', table)[0], 409)
        for invalid in [dict(number=0), dict(number=1000), dict(number=3.2), dict(number=77, label='')]:
            self.assertEqual(self.request(admin, '/api/admin/tables/add', invalid)[0], 400)
        app.init_db()
        self.assertIn(table, self.request(admin, '/api/admin/settings')[1]['tables'])
        with customer.open(self.base + '/?table=76') as response:
            self.assertEqual(response.status, 200)
        payload = self.payload('added-table-order-01')
        payload['table'] = table['number']
        self.assertEqual(self.request(customer, '/api/checkout', payload)[1]['order']['table'], 76)


if __name__ == '__main__':
    unittest.main(verbosity=2)
