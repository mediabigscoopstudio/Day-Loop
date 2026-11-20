import json
from datetime import timedelta
from decimal import Decimal as D

from django.utils import timezone

from orders.models import LedgerEntry, SellerOrder

from .orders_helpers import HX, OrdersCase


class StatusPopupTests(OrdersCase):
    def test_each_step_has_a_confirmation_popup_then_applies(self):
        r = self.client.get(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.assertContains(r, 'Accept this order?'); self.assertContains(r, 'commit to packing')
        out = self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.assertEqual(out.status_code, 204)
        self.assertTrue(json.loads(out['HX-Trigger'])['orders-changed'])
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'accepted')
        self.assertContains(self.client.get(f'/orders/{self.so_a.pk}/advance/', **HX), 'Mark as packed?')
        self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'packed')

    def test_shipping_needs_courier_and_awb(self):
        for _ in range(2):
            self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        form = self.client.get(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.assertContains(form, 'AWB / tracking number'); self.assertContains(form, 'sheet')
        for data in ({}, {'courier': 'Delhivery'}, {'awb': 'A1'}):
            r = self.client.post(f'/orders/{self.so_a.pk}/advance/', data, **HX)
            self.assertContains(r, 'Courier name and AWB', status_code=422)
        bad = self.client.post(f'/orders/{self.so_a.pk}/advance/', {'courier': 'X', 'awb': 'Y', 'tracking_url': 'javascript:alert(1)'}, **HX)
        self.assertContains(bad, 'must start with http', status_code=422)
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'packed')

    def test_shipped_order_records_courier_and_timeline(self):
        self.assertEqual(self.ship_a().status_code, 204)
        self.so_a.refresh_from_db()
        self.assertEqual((self.so_a.status, self.so_a.courier, self.so_a.awb), ('shipped', 'Delhivery', 'DL123456'))
        self.assertIsNotNone(self.so_a.shipped_at)
        self.assertEqual([e.status for e in self.so_a.events.all()], ['new', 'accepted', 'packed', 'shipped'])
        detail = self.client.get(f'/orders/{self.so_a.pk}/', **HX)
        self.assertContains(detail, 'Track shipment'); self.assertContains(detail, 'DL123456')

    def test_delivery_credits_the_payout_and_no_actions_remain_but_return(self):
        self.ship_a()
        self.assertContains(self.client.get(f'/orders/{self.so_a.pk}/advance/', **HX), 'Your payout for this order is credited')
        self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        credit = LedgerEntry.objects.get()
        self.assertEqual((credit.kind, credit.amount, credit.seller_id), ('credit', D('2352.50'), self.a.pk))
        self.assertEqual(credit.amount, self.so_a.payout)
        detail = self.client.get(f'/orders/{self.so_a.pk}/', **HX)
        self.assertContains(detail, 'Mark returned'); self.assertNotContains(detail, 'Cancel</button>')

    def test_cancel_needs_a_reason_and_returns_stock(self):
        self.assertContains(self.client.get(f'/orders/{self.so_a.pk}/cancel/', **HX), 'back on your shelf')
        r = self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': '  '}, **HX)
        self.assertContains(r, 'A reason is required', status_code=422)
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'new')
        self.assertEqual(self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': 'Item damaged'}, **HX).status_code, 204)
        self.so_a.refresh_from_db()
        self.assertEqual((self.so_a.status, self.so_a.events.last().note), ('cancelled', 'Item damaged'))
        self.assertEqual((self.stock(self.pa1), self.stock(self.pa2)), (20, 20))

    def test_cancel_is_refused_after_shipping(self):
        self.ship_a()
        r = self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': 'Changed mind'}, **HX)
        self.assertContains(r, 'can no longer be cancelled', status_code=422)
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'shipped')

    def test_return_after_delivery_reverses_the_payout(self):
        self.ship_a(); self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.assertContains(self.client.get(f'/orders/{self.so_a.pk}/return/', **HX), 'payout for this order is reversed')
        self.assertContains(self.client.post(f'/orders/{self.so_a.pk}/return/', {'reason': ''}, **HX), 'A reason is required', status_code=422)
        self.assertEqual(self.client.post(f'/orders/{self.so_a.pk}/return/', {'reason': 'Customer returned'}, **HX).status_code, 204)
        kinds = list(LedgerEntry.objects.order_by('id').values_list('kind', flat=True))
        self.assertEqual(kinds, ['credit', 'debit'])
        self.assertEqual(sum(e.signed_amount for e in LedgerEntry.objects.all()), 0)
        self.assertEqual(self.stock(self.pa1), 20)

    def test_finished_orders_show_a_friendly_message(self):
        self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': 'x'}, **HX)
        self.assertContains(self.client.get(f'/orders/{self.so_a.pk}/advance/', **HX), 'cancelled')


class ListFilterTests(OrdersCase):
    def setUp(self):
        super().setUp()
        from dash.tests import factories as f
        from orders.services.checkout import create_order
        from .orders_helpers import ADDRESS
        self.o2 = create_order(f.make_user('b2'), [(self.pa2.variant.pk, 1)], ADDRESS)
        self.so2 = self.o2.seller_orders.get(seller=self.a)
        self.client.post(f'/orders/{self.so2.pk}/advance/', **HX)                       # accepted
        SellerOrder.objects.filter(pk=self.so_a.pk).update(created_at=timezone.now() - timedelta(days=10))

    def invoices(self, qs=''):
        r = self.client.get('/orders/' + qs)
        self.assertEqual(r.status_code, 200, qs)
        return {so.invoice_number for so in r.context['page'].object_list}

    def test_filters_and_search(self):
        a, b = self.so_a.invoice_number, self.so2.invoice_number
        self.assertEqual(self.invoices(), {a, b})
        self.assertEqual(self.invoices('?status=accepted'), {b}); self.assertEqual(self.invoices('?status=new'), {a})
        self.assertEqual(self.invoices(f'?q={a}'), {a})
        self.assertEqual(self.invoices(f'?product={self.pa1.pk}'), {a}); self.assertEqual(self.invoices(f'?product={self.pa2.pk}'), {a, b})
        recent = (timezone.now() - timedelta(days=3)).date().isoformat()
        self.assertEqual(self.invoices(f'?date_from={recent}'), {b})
        self.assertEqual(self.invoices(f'?date_to={recent}'), {a})
        self.assertEqual(self.invoices('?status=bogus&product=x&date_from=zz&page=-4'), {a, b})

    def test_status_tabs_count_only_mine(self):
        counts = self.client.get('/orders/').context['counts']
        self.assertEqual((counts['all'], counts['new'], counts['accepted']), (2, 1, 1))

    def test_overdue_new_orders_are_flagged(self):
        SellerOrder.objects.filter(pk=self.so_a.pk).update(accept_by=timezone.now() - timedelta(hours=1))
        self.assertContains(self.client.get('/orders/'), 'Overdue')

    def test_empty_states(self):
        SellerOrder.objects.filter(seller=self.a).delete()
        self.assertContains(self.client.get('/orders/'), 'No orders yet')
        self.assertContains(self.client.get('/orders/?q=zzz'), 'No orders match')
