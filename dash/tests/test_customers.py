from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class CustomerTests(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.p = f.make_product(f.make_seller(), sub, '1000')
        self.rep, self.one, self.nobody = f.make_user('rep'), f.make_user('one'), f.make_user('nobody')
        now = timezone.now()
        f.make_order(self.rep, now - timedelta(days=3), [(self.p, 1)])
        f.make_order(self.rep, now, [(self.p, 2)])
        f.make_order(self.rep, now, [(self.p, 9)], status='cancelled')     # ignored in stats
        f.make_order(self.one, now - timedelta(days=1), [(self.p, 1)])
        self.login_as(self.superuser)

    def rows(self, qs=''):
        r = self.client.get('/customers/' + qs)
        self.assertEqual(r.status_code, 200)
        return {c.username: c for c in r.context['page'].object_list}

    def test_only_customers_with_orders_and_stats_exclude_cancelled(self):
        rows = self.rows()
        self.assertEqual(set(rows), {self.rep.username, self.one.username})
        r = rows[self.rep.username]
        self.assertEqual((r.order_count, r.lifetime_value), (2, Decimal('3000')))

    def test_repeat_filter_search_sort(self):
        self.assertEqual(set(self.rows('?repeat=yes')), {self.rep.username})
        self.assertEqual(set(self.rows('?repeat=no')), {self.one.username})
        self.assertEqual(set(self.rows(f'?q={self.one.email}')), {self.one.username})
        r = self.client.get('/customers/?sort=ltv&dir=desc')
        self.assertEqual(r.context['page'].object_list[0].username, self.rep.username)

    def test_detail_modal_and_no_n_plus_one(self):
        self.assertContains(self.client.get(f'/customers/{self.rep.pk}/', **HX), 'Repeat customer')
        self.assertEqual(self.client.get(f'/customers/{self.nobody.pk}/', **HX).status_code, 404)
        self.client.get('/customers/')
        with CaptureQueriesContext(connection) as small:
            self.client.get('/customers/')
        for _ in range(8):
            f.make_order(f.make_user('x'), timezone.now(), [(self.p, 1)])
        with CaptureQueriesContext(connection) as large:
            self.client.get('/customers/')
        self.assertEqual(len(small), len(large))

    def test_non_superusers_forbidden(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for url in ('/customers/', f'/customers/{self.rep.pk}/'):
                self.assertEqual(self.client.get(url, **HX).status_code, 403, f'{url} {user.username}')
