from datetime import timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catalog.models import ProductVariant
from dash.services.dates import parse_range
from dash.tests import factories as f
from orders.models import SellerOrder
from orders.services import seller_flow as flow
from orders.services.checkout import create_order
from seller.services import metrics

from .orders_helpers import ADDRESS, HX
from .base import SellerTestCase


class DashboardBase(SellerTestCase):
    def setUp(self):
        super().setUp()
        self.sub = f.make_category('S', f.make_category('C'))
        self.pa = f.make_product(self.a, self.sub, '10000', stock=50, name='Alpha Whey')
        self.pb = f.make_product(self.b, self.sub, '2000', stock=50, name='Beta Tonic')
        self.buyer = f.make_user('buyer')
        self.dr = parse_range({'range': '30d'})
        self.login_as(self.a.user)

    def order(self, product, qty=1, days_ago=0):
        o = create_order(self.buyer, [(product.variant.pk, qty)], ADDRESS)
        so = o.seller_orders.get()
        if days_ago:
            SellerOrder.objects.filter(pk=so.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return SellerOrder.objects.get(pk=so.pk)


class MetricsTests(DashboardBase):
    def test_revenue_orders_and_basis(self):
        self.order(self.pa, 1); self.order(self.pa, 2)                          # 10,000 + 20,000 purchase value
        cards = {c['key']: c for c in metrics.kpis(self.a, self.dr, 'gmv')['cards']}
        self.assertEqual((cards['revenue']['value'], cards['orders']['value']), (D('30000.00'), 2))
        self.assertIn('2 new', cards['orders']['note'])
        pay = {c['key']: c for c in metrics.kpis(self.a, self.dr, 'payout')['cards']}
        self.assertEqual(pay['revenue']['value'], D('28230.00'))                  # 9,410 + 18,820
        self.assertEqual(metrics.kpis(self.a, self.dr, 'bogus')['basis'], 'gmv')

    def test_cancelled_and_returned_orders_are_excluded(self):
        keep, drop = self.order(self.pa), self.order(self.pa)
        flow.cancel(self.a, drop.pk, self.a.user, 'x')
        self.assertEqual(metrics.kpis(self.a, self.dr)['cards'][0]['value'], D('10000.00'))

    def test_delta_against_the_prior_period(self):
        self.order(self.pa, 1); self.order(self.pa, 1, days_ago=40)               # prior 30-day window holds one order
        card = metrics.kpis(self.a, self.dr)['cards'][0]
        self.assertEqual((card['value'], card['delta']), (D('10000.00'), 0.0))
        self.order(self.pa, 1)
        self.assertEqual(metrics.kpis(self.a, self.dr)['cards'][0]['delta'], 100.0)

    def test_other_sellers_sales_never_count(self):
        self.order(self.pb, 5)
        self.assertEqual(metrics.kpis(self.a, self.dr)['cards'][0]['value'], D('0.00'))
        self.assertEqual(metrics.kpis(self.b, self.dr)['cards'][0]['value'], D('10000.00'))
        self.assertEqual(metrics.top_products(self.a, self.dr), [])
        self.assertEqual(metrics.needs_action(self.a), [])

    def test_low_stock_and_payout_due(self):
        ProductVariant.objects.filter(pk=self.pa.variant.pk).update(stock=3, low_stock_threshold=10)
        so = self.order(self.pa, 1)
        flow.advance(self.a, so.pk, self.a.user); flow.advance(self.a, so.pk, self.a.user)
        flow.advance(self.a, so.pk, self.a.user, courier='C', awb='A'); flow.advance(self.a, so.pk, self.a.user)
        cards = {c['key']: c for c in metrics.kpis(self.a, self.dr)['cards']}
        self.assertEqual(cards['low_stock']['value'], 1)
        self.assertEqual(cards['payout_due']['value'], D('9410.00'))

    def test_sales_series_fills_empty_days_and_uses_the_basis(self):
        self.order(self.pa, 1, days_ago=2)
        s = metrics.sales_series(self.a, self.dr, 'payout')
        self.assertEqual(len(s['labels']), 30); self.assertEqual(sum(s['gmv']), 9410.0)
        self.assertEqual(sum(metrics.sales_series(self.a, self.dr, 'gmv')['gmv']), 10000.0)

    def test_top_products_and_actions_are_mine_only(self):
        self.order(self.pa, 2); self.order(self.pb, 9)
        top = metrics.top_products(self.a, self.dr)
        self.assertEqual([(p['name'], p['units']) for p in top], [('Alpha Whey', 2)])
        self.assertEqual(len(metrics.needs_action(self.a)), 1)


class DashboardPageTests(DashboardBase):
    def test_empty_dashboard_has_friendly_states(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        for text in ('All caught up', 'No sales in this period', 'No payouts yet', 'Stock looks healthy'):
            self.assertContains(r, text)
        self.assertContains(r, 'Revenue (GMV)'); self.assertContains(r, 'Payout due')

    def test_dashboard_with_data_basis_toggle_and_actions(self):
        so = self.order(self.pa, 1)
        r = self.client.get('/?range=30d&basis=payout')
        self.assertContains(r, 'Revenue (payout)'); self.assertContains(r, so.invoice_number)
        self.assertContains(r, f'/orders/{so.pk}/advance/')                      # quick Accept button
        self.assertContains(self.client.get('/?range=7d'), 'Revenue (GMV)')
        for rng in ('7d', '30d', '90d', '12m', 'junk'):
            self.assertEqual(self.client.get(f'/?range={rng}').status_code, 200, rng)

    def test_query_count_does_not_grow_with_data(self):
        self.client.get('/')
        with CaptureQueriesContext(connection) as small:
            self.client.get('/')
        for _ in range(8):
            self.order(self.pa, 1)
        with CaptureQueriesContext(connection) as large:
            self.client.get('/')
        self.assertEqual(len(small), len(large))

    def test_json_endpoint(self):
        self.order(self.pa, 1)
        d = self.client.get('/api/sales/?range=30d&basis=gmv').json()
        self.assertEqual((len(d['labels']), sum(d['gmv'])), (30, 10000.0))

    def test_gating(self):
        for user in (self.pending.user, self.draft.user):
            self.login_as(user)
            r = self.client.get('/'); self.assertEqual((r.status_code, r['Location']), (302, '/status/'))
            self.assertEqual(self.client.get('/api/sales/', **HX).status_code, 403)
        self.login_as(self.customer)
        self.assertEqual(self.client.get('/api/sales/').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/sales/').status_code, 403)
