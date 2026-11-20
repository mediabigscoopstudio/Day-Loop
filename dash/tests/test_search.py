from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class SearchTests(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.s = f.make_seller('Prana Wellness', 'pending')
        self.p = f.make_product(self.s, sub, '900', name='Prana Whey')
        self.u = f.make_user('priya')
        self.o = f.make_order(self.u, timezone.now(), [(self.p, 1)])
        self.login_as(self.superuser)

    def test_grouped_results(self):
        r = self.client.get('/search/?q=prana', **HX)
        for text in ('Sellers', 'Products', 'Prana Wellness', 'Prana Whey'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'Orders')
        r = self.client.get('/search/?q=priya', **HX)
        self.assertContains(r, 'Customers'); self.assertContains(r, 'Orders')
        self.assertContains(self.client.get(f'/search/?q={self.o.number}', **HX), f'#{self.o.number}')

    def test_short_and_empty_queries(self):
        self.assertEqual(self.client.get('/search/?q=p', **HX).content.strip(), b'')
        self.assertContains(self.client.get('/search/?q=zzzzzz', **HX), 'No results')

    def test_results_are_limited_and_bounded_queries(self):
        for i in range(10):
            f.make_seller(f'Many {i}')
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get('/search/?q=many', **HX)
        self.assertLessEqual(r.content.decode().count('menu-link'), 4)
        self.assertLessEqual(len(ctx), 8)

    def test_bell_counts_pending_and_dropdown(self):
        r = self.client.get('/')
        self.assertContains(r, 'class="dot"')
        self.assertContains(self.client.get('/notifications/', **HX), 'awaiting review')
        self.s.status = 'approved'; self.s.save()
        self.assertContains(self.client.get('/notifications/', **HX), 'all caught up')

    def test_forbidden_for_non_superusers(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for url in ('/search/?q=prana', '/notifications/'):
                self.assertEqual(self.client.get(url, **HX).status_code, 403)
