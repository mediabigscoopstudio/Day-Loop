from datetime import date, datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import factories as f
from .base import DashTestCase


class OverviewTests(DashTestCase):
    def test_overview_renders_with_empty_database(self):
        self.login_as(self.superuser)
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Aarav')                       # greeting uses first name
        self.assertContains(r, 'No orders yet')               # friendly empty state
        self.assertContains(r, 'All caught up')
        self.assertContains(r, '₹0')

    def _seed(self):
        cat = f.make_category('Wellness'); sub = f.make_category('Protein', parent=cat)
        sellers = [f.make_seller(f'Seller {i}') for i in range(6)]
        f.make_seller('Pending One', status='pending')
        products = [f.make_product(s, sub, '1500') for s in sellers]
        customers = [f.make_user('c') for _ in range(8)]
        now = timezone.now()
        for i, c in enumerate(customers):
            for j in range(3):
                f.make_order(c, now - timezone.timedelta(days=(i + j) % 20), [(products[(i + j) % 6], 2)])

    def test_overview_query_count_is_bounded_and_independent_of_data_size(self):
        self.login_as(self.superuser)
        self._seed()
        self.client.get('/')  # warm-up: one-time session/cache work
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.client.get('/').status_code, 200)
        self._seed()  # double the data
        with CaptureQueriesContext(connection) as large:
            self.assertEqual(self.client.get('/').status_code, 200)
        self.assertLessEqual(len(large), 24, 'overview should stay within its query budget')
        self.assertEqual(len(small), len(large), 'no N+1: query count must not grow with data')

    def test_json_endpoints(self):
        self._seed()
        self.login_as(self.superuser)
        s = self.client.get('/api/sales/?range=30d')
        self.assertEqual(s.status_code, 200)
        data = s.json()
        self.assertEqual(len(data['labels']), 30)
        self.assertGreater(sum(data['gmv']), 0)
        c = self.client.get('/api/category-revenue/?range=30d').json()
        self.assertEqual(c['rows'][0]['name'], 'Wellness')
        self.assertEqual(c['rows'][0]['share'], 100.0)

    def test_json_endpoints_forbidden_for_everyone_but_superusers(self):
        for url in ('/api/sales/', '/api/category-revenue/', '/partials/kpis/',
                    '/partials/pending-approvals/', '/partials/recent-orders/'):
            self.client.logout()
            self.assertEqual(self.client.get(url, HTTP_ACCEPT='application/json').status_code in (302, 403), True, url)
            for u in (self.staff, self.customer, self.seller_user):
                self.login_as(u)
                r = self.client.get(url, HTTP_HX_REQUEST='true')
                self.assertEqual(r.status_code, 403, f'{url} for {u.username}')
            self.client.logout()
            self.assertEqual(self.client.get(url, HTTP_HX_REQUEST='true').status_code, 403, url)
