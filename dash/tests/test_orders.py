from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from dash.services import metrics
from dash.services.dates import build_range
from orders.models import Order

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class OrderTests(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.s1, self.s2 = f.make_seller('Prana'), f.make_seller('Ayura')
        self.p1, self.p2 = f.make_product(self.s1, sub, '1000'), f.make_product(self.s2, sub, '500')
        self.cust = f.make_user('cu')
        now = timezone.now()
        self.o1 = f.make_order(self.cust, now, [(self.p1, 2), (self.p2, 1)], status='pending', payment='pending')
        self.o2 = f.make_order(self.cust, now - timedelta(days=5), [(self.p2, 1)], status='shipped')
        self.o3 = f.make_order(self.cust, now - timedelta(days=9), [(self.p1, 1)], status='delivered', payment='refunded')
        self.login_as(self.superuser)

    def numbers(self, qs=''):
        r = self.client.get('/orders/' + qs)
        self.assertEqual(r.status_code, 200, qs)
        return {o.number for o in r.context['page'].object_list}

    def test_filters(self):
        every = {self.o1.number, self.o2.number, self.o3.number}
        self.assertEqual(self.numbers(), every)
        self.assertEqual(self.numbers('?status=shipped'), {self.o2.number})
        self.assertEqual(self.numbers('?payment=refunded'), {self.o3.number})
        self.assertEqual(self.numbers(f'?seller={self.s1.pk}'), {self.o1.number, self.o3.number})
        self.assertEqual(self.numbers(f'?q={self.o2.number}'), {self.o2.number})
        self.assertEqual(self.numbers(f'?q={self.cust.username}'), every)
        d = (timezone.now() - timedelta(days=6)).date().isoformat()
        self.assertEqual(self.numbers(f'?date_from={d}'), {self.o1.number, self.o2.number})
        self.assertEqual(self.numbers('?status=bogus&payment=x&seller=y&date_from=zz'), every)

    def test_seller_filter_does_not_duplicate_rows(self):
        r = self.client.get(f'/orders/?seller={self.s1.pk}')
        nums = [o.number for o in r.context['page'].object_list]
        self.assertEqual(len(nums), len(set(nums)))

    def test_detail_modal_groups_items_by_seller(self):
        r = self.client.get(f'/orders/{self.o1.pk}/', **HX)
        self.assertContains(r, 'Prana'); self.assertContains(r, 'Ayura')
        self.assertEqual(len(r.context['subs']), 2)
        self.assertContains(r, '₹2,500.00')

    def test_status_flow(self):
        r = self.client.post(f'/orders/{self.o1.pk}/status/', {'status': 'processing'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.o1.refresh_from_db(); self.assertEqual(self.o1.status, 'processing')

    def test_invalid_transitions_are_rejected(self):
        for new in ('shipped', 'delivered', 'cancelled', 'pending', 'junk'):
            r = self.client.post(f'/orders/{self.o1.pk}/status/', {'status': new}, **HX)
            self.assertEqual(r.status_code, 422, new)
        self.o1.refresh_from_db(); self.assertEqual(self.o1.status, 'pending')
        self.assertEqual(self.client.post(f'/orders/{self.o3.pk}/status/', {'status': 'pending'}, **HX).status_code, 422)

    def test_cancel_popup_warns_and_cancels_pending_only(self):
        self.assertContains(self.client.get(f'/orders/{self.o1.pk}/cancel/', **HX), 'excluded from revenue')
        self.assertEqual(self.client.post(f'/orders/{self.o1.pk}/cancel/', **HX).status_code, 204)
        self.o1.refresh_from_db(); self.assertEqual(self.o1.status, 'cancelled')
        self.assertEqual(self.client.post(f'/orders/{self.o2.pk}/cancel/', **HX).status_code, 422)   # shipped
        self.o2.refresh_from_db(); self.assertEqual(self.o2.status, 'shipped')

    def test_cancelling_lowers_gmv(self):
        dr = build_range((timezone.localdate() - timedelta(days=30)), timezone.localdate())
        before = metrics.overview_kpis(dr)[0]['value']
        self.client.post(f'/orders/{self.o1.pk}/cancel/', **HX)
        after = metrics.overview_kpis(dr)[0]['value']
        self.assertEqual(before - after, self.o1.total)

    def test_list_has_no_n_plus_one(self):
        self.client.get('/orders/')
        with CaptureQueriesContext(connection) as small:
            self.client.get('/orders/')
        for i in range(10):
            f.make_order(self.cust, timezone.now(), [(self.p1, 1)])
        with CaptureQueriesContext(connection) as large:
            self.client.get('/orders/')
        self.assertEqual(len(small), len(large))

    def test_non_superusers_forbidden(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for method, url in (('get', '/orders/'), ('get', f'/orders/{self.o1.pk}/'), ('get', f'/orders/{self.o1.pk}/status/'),
                                ('post', f'/orders/{self.o1.pk}/status/'), ('post', f'/orders/{self.o1.pk}/cancel/')):
                r = getattr(self.client, method)(url, {'status': 'processing'}, **HX)
                self.assertEqual(r.status_code, 403, f'{method} {url} {user.username}')
        self.o1.refresh_from_db(); self.assertEqual(self.o1.status, 'pending')
