import json
from decimal import Decimal as D

from orders.models import LedgerEntry, Payout
from orders.services import seller_flow as flow
from orders.services.checkout import create_order
from orders.services.payouts import SettlementError, balances, settle

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}
ADDRESS = dict(name='P', line1='1 Road', city='Pune', state='MH', pincode='411001')


def deliver(seller, so, actor):
    flow.advance(seller, so.pk, actor); flow.advance(seller, so.pk, actor)
    flow.advance(seller, so.pk, actor, courier='C', awb='A'); flow.advance(seller, so.pk, actor)


class PayoutBase(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.s1, self.s2 = f.make_seller('Alpha'), f.make_seller('Beta')
        self.p1 = f.make_product(self.s1, sub, '10000', stock=50, name='A1')
        self.p2 = f.make_product(self.s2, sub, '2000', stock=50, name='B1')
        self.buyer = f.make_user('buyer')

    def delivered(self, product, seller, qty=1):
        o = create_order(self.buyer, [(product.variant.pk, qty)], ADDRESS)
        so = o.seller_orders.get(seller=seller)
        deliver(seller, so, self.superuser)
        return so


class BalanceTests(PayoutBase):
    def test_pending_is_credits_minus_debits_and_spec_example_pays_9410(self):
        so = self.delivered(self.p1, self.s1)                             # purchase 10,000 -> payout 9,410
        self.assertEqual(so.payout, D('9410.00'))
        self.assertEqual(balances(self.s1), {'pending': D('9410.00'), 'settled': D('0.00'), 'lifetime': D('9410.00')})
        flow.mark_returned(self.s1, so.pk, self.superuser, 'Returned')
        self.assertEqual(balances(self.s1)['pending'], D('0.00'))

    def test_balances_are_per_seller(self):
        self.delivered(self.p1, self.s1); self.delivered(self.p2, self.s2)
        self.assertEqual(balances(self.s1)['pending'], D('9410.00')); self.assertEqual(balances(self.s2)['pending'], D('1882.00'))

    def test_settlement_pays_everything_pending_and_attaches_entries(self):
        self.delivered(self.p1, self.s1); self.delivered(self.p1, self.s1)
        payout = settle(self.s1.pk, self.superuser, 'UTR123')
        self.assertEqual((payout.amount, payout.reference, payout.created_by), (D('18820.00'), 'UTR123', self.superuser))
        self.assertEqual(LedgerEntry.objects.filter(payout=payout).count(), 2)
        self.assertEqual(balances(self.s1), {'pending': D('0.00'), 'settled': D('18820.00'), 'lifetime': D('18820.00')})
        with self.assertRaises(SettlementError):
            settle(self.s1.pk, self.superuser)                              # nothing left to pay

    def test_a_later_delivery_after_settlement_is_a_new_pending_balance(self):
        self.delivered(self.p1, self.s1); settle(self.s1.pk, self.superuser)
        self.delivered(self.p1, self.s1)
        self.assertEqual(balances(self.s1)['pending'], D('9410.00')); self.assertEqual(balances(self.s1)['settled'], D('9410.00'))

    def test_negative_balance_cannot_be_settled(self):
        so = self.delivered(self.p1, self.s1); settle(self.s1.pk, self.superuser)
        flow.mark_returned(self.s1, so.pk, self.superuser, 'Returned after payout')
        self.assertEqual(balances(self.s1)['pending'], D('-9410.00'))
        with self.assertRaisesMessage(SettlementError, 'not positive'):
            settle(self.s1.pk, self.superuser)
        self.assertEqual(Payout.objects.count(), 1)


class PayoutPageTests(PayoutBase):
    def setUp(self):
        super().setUp()
        self.delivered(self.p1, self.s1); self.delivered(self.p2, self.s2)
        self.login_as(self.superuser)

    def test_page_lists_pending_balances_per_seller(self):
        r = self.client.get('/payouts/')
        self.assertContains(r, 'Alpha'); self.assertContains(r, 'Beta'); self.assertContains(r, '₹9,410.00'); self.assertContains(r, '₹11,292.00')

    def test_settle_popup_then_pay(self):
        self.assertContains(self.client.get(f'/payouts/{self.s1.pk}/settle/', **HX), 'cannot be undone')
        r = self.client.post(f'/payouts/{self.s1.pk}/settle/', {'reference': 'UTR9'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.assertIn('Paid Alpha', json.loads(r['HX-Trigger'])['toast']['message'])
        self.assertEqual(balances(self.s1)['pending'], D('0.00')); self.assertEqual(balances(self.s2)['pending'], D('1882.00'))
        self.assertContains(self.client.get('/payouts/'), 'UTR9')
        again = self.client.post(f'/payouts/{self.s1.pk}/settle/', {}, **HX)
        self.assertContains(again, 'nothing pending', status_code=422)
        self.assertEqual(Payout.objects.count(), 1)

    def test_only_superusers_can_settle(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            self.assertEqual(self.client.get('/payouts/', **HX).status_code, 403)
            self.assertEqual(self.client.post(f'/payouts/{self.s1.pk}/settle/', {}, **HX).status_code, 403)
        self.assertEqual(Payout.objects.count(), 0)
