from decimal import Decimal as D

from orders.models import LedgerEntry
from orders.services import seller_flow as flow
from orders.services.payouts import settle

from .orders_helpers import HX, OrdersCase


class EarningsTests(OrdersCase):
    def deliver_a(self):
        for _ in range(2):
            self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        self.client.post(f'/orders/{self.so_a.pk}/advance/', {'courier': 'C', 'awb': 'A'}, **HX)
        self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)

    def test_empty_earnings(self):
        r = self.client.get('/earnings/')
        self.assertContains(r, 'No earnings yet'); self.assertContains(r, 'No payouts yet'); self.assertContains(r, '₹0.00')

    def test_delivered_order_shows_as_pending_payout(self):
        self.deliver_a()
        r = self.client.get('/earnings/')
        self.assertEqual(r.context['bal']['pending'], D('2352.50'))                      # 2,500 - 125 margin - 22.50 GST
        self.assertContains(r, '₹2,352.50'); self.assertContains(r, 'Pending'); self.assertContains(r, self.so_a.invoice_number)

    def test_settled_payouts_move_from_pending_to_settled(self):
        self.deliver_a()
        settle(self.a.pk, self.superuser, 'UTR-77')
        r = self.client.get('/earnings/')
        self.assertEqual((r.context['bal']['pending'], r.context['bal']['settled']), (D('0.00'), D('2352.50')))
        self.assertContains(r, 'UTR-77'); self.assertContains(r, 'Settled')

    def test_returns_appear_as_debits(self):
        self.deliver_a(); settle(self.a.pk, self.superuser)
        flow.mark_returned(self.a, self.so_a.pk, self.a.user, 'Customer return')
        r = self.client.get('/earnings/')
        self.assertEqual(r.context['bal']['pending'], D('-2352.50'))
        self.assertContains(r, 'Refund for')

    def test_sellers_only_see_their_own_money(self):
        self.deliver_a()
        self.login_as(self.b.user)
        r = self.client.get('/earnings/')
        self.assertEqual(r.context['bal']['pending'], D('0.00'))
        self.assertNotContains(r, self.so_a.invoice_number)
        self.assertEqual(LedgerEntry.objects.filter(seller=self.b).count(), 0)

    def test_earnings_is_read_only_and_gated(self):
        self.assertEqual(self.client.post('/earnings/', {'amount': 1}).status_code, 405)
        for user in (self.pending.user, self.customer):
            self.login_as(user)
            self.assertIn(self.client.get('/earnings/').status_code, (302,))
