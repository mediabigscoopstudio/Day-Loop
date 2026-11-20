from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from catalog.models import ProductVariant
from dash.tests import factories as f
from orders.models import LedgerEntry, SellerOrder
from orders.services import seller_flow as flow
from orders.services.checkout import create_order

from .test_checkout import ADDRESS


class FlowBase(TestCase):
    def setUp(self):
        sub = f.make_category('S', f.make_category('C'))
        self.s1, self.s2 = f.make_seller('Prana'), f.make_seller('Ayura')
        self.p1 = f.make_product(self.s1, sub, '1000', stock=10)
        self.p2 = f.make_product(self.s2, sub, '2000', stock=10)
        self.customer, self.actor = f.make_user('cust'), f.make_user('act')
        self.order = create_order(self.customer, [(self.p1.variant.pk, 2), (self.p2.variant.pk, 3)], ADDRESS)
        self.so1 = self.order.seller_orders.get(seller=self.s1)
        self.so2 = self.order.seller_orders.get(seller=self.s2)

    def stock(self, p):
        return ProductVariant.objects.get(pk=p.variant.pk).stock


class CancelIndependenceTests(FlowBase):
    def test_cancelling_one_seller_order_leaves_the_others_untouched(self):
        before = {k: getattr(self.so2, k) for k in ('status', 'purchase_value', 'margin', 'payout', 'invoice_number')}
        flow.cancel(self.s1, self.so1.pk, self.actor, 'Out of stock at warehouse')
        self.so1.refresh_from_db(); self.so2.refresh_from_db()
        self.assertEqual(self.so1.status, 'cancelled')
        self.assertEqual({k: getattr(self.so2, k) for k in before}, before)
        self.assertEqual(self.so2.items.count(), 1)
        self.assertEqual(self.stock(self.p1), 10)          # cancelled items went back on the shelf
        self.assertEqual(self.stock(self.p2), 7)           # the other seller's stock is unchanged
        self.assertEqual(self.so1.events.last().status, 'cancelled')
        self.assertEqual(self.so1.events.last().note, 'Out of stock at warehouse')

    def test_cancel_writes_no_ledger_entries(self):
        flow.cancel(self.s1, self.so1.pk, self.actor)
        self.assertFalse(LedgerEntry.objects.exists())

    def test_cannot_cancel_after_shipping(self):
        for _ in range(2):
            flow.advance(self.s1, self.so1.pk, self.actor)
        flow.advance(self.s1, self.so1.pk, self.actor, courier='Delhivery', awb='AWB1')
        with self.assertRaises(flow.FlowError):
            flow.cancel(self.s1, self.so1.pk, self.actor)


class PipelineTests(FlowBase):
    def test_full_pipeline_with_timeline_and_payout_credit(self):
        flow.advance(self.s1, self.so1.pk, self.actor)                       # accepted
        flow.advance(self.s1, self.so1.pk, self.actor)                       # packed
        flow.advance(self.s1, self.so1.pk, self.actor, courier='Delhivery', awb='DL123', tracking_url='https://t.example/DL123')
        so = SellerOrder.objects.get(pk=self.so1.pk)
        self.assertEqual((so.status, so.courier, so.awb), ('shipped', 'Delhivery', 'DL123'))
        self.assertFalse(LedgerEntry.objects.exists())                       # nothing credited before delivery
        flow.advance(self.s1, self.so1.pk, self.actor)                       # delivered
        so.refresh_from_db()
        self.assertEqual(so.status, 'delivered')
        credit = LedgerEntry.objects.get()
        self.assertEqual((credit.kind, credit.amount, credit.seller_id), ('credit', D('1882.00'), self.s1.pk))   # 2000 - 100 margin - 18 GST
        self.assertEqual([e.status for e in so.events.all()], ['new', 'accepted', 'packed', 'shipped', 'delivered'])

    def test_shipping_requires_courier_and_awb(self):
        flow.advance(self.s1, self.so1.pk, self.actor); flow.advance(self.s1, self.so1.pk, self.actor)
        for kwargs in ({}, {'courier': 'X'}, {'awb': 'Y'}):
            with self.assertRaises(flow.FlowError):
                flow.advance(self.s1, self.so1.pk, self.actor, **kwargs)
        self.assertEqual(SellerOrder.objects.get(pk=self.so1.pk).status, 'packed')

    def test_cannot_skip_steps_or_move_past_delivered(self):
        with self.assertRaises(flow.FlowError):
            flow.mark_returned(self.s1, self.so1.pk, self.actor)             # not delivered yet
        for _ in range(2):
            flow.advance(self.s1, self.so1.pk, self.actor)
        flow.advance(self.s1, self.so1.pk, self.actor, courier='C', awb='A')
        flow.advance(self.s1, self.so1.pk, self.actor)
        with self.assertRaises(flow.FlowError):
            flow.advance(self.s1, self.so1.pk, self.actor)

    def test_return_debits_the_payout_and_restores_stock_for_that_order_only(self):
        for _ in range(2):
            flow.advance(self.s1, self.so1.pk, self.actor)
        flow.advance(self.s1, self.so1.pk, self.actor, courier='C', awb='A')
        flow.advance(self.s1, self.so1.pk, self.actor)
        flow.mark_returned(self.s1, self.so1.pk, self.actor, 'Damaged in transit')
        entries = list(LedgerEntry.objects.filter(seller=self.s1).order_by('id'))
        self.assertEqual([e.kind for e in entries], ['credit', 'debit'])
        self.assertEqual(sum(e.signed_amount for e in entries), D('0.00'))
        self.assertEqual(self.stock(self.p1), 10)
        self.assertEqual(self.stock(self.p2), 7)
        self.assertEqual(SellerOrder.objects.get(pk=self.so2.pk).status, 'new')
        self.assertFalse(LedgerEntry.objects.filter(seller=self.s2).exists())

    def test_expire_unaccepted_cancels_only_overdue_new_orders(self):
        flow.advance(self.s2, self.so2.pk, self.actor)                       # s2 accepted in time
        n = flow.expire_unaccepted(now=timezone.now() + timezone.timedelta(hours=25))
        self.assertEqual(n, 1)
        self.assertEqual(SellerOrder.objects.get(pk=self.so1.pk).status, 'cancelled')
        self.assertEqual(SellerOrder.objects.get(pk=self.so2.pk).status, 'accepted')
        self.assertEqual(self.stock(self.p1), 10)


class OwnershipTests(FlowBase):
    def test_another_sellers_order_is_not_found(self):
        for call in (lambda: flow.advance(self.s2, self.so1.pk, self.actor),
                     lambda: flow.cancel(self.s2, self.so1.pk, self.actor),
                     lambda: flow.mark_returned(self.s2, self.so1.pk, self.actor)):
            with self.assertRaises(SellerOrder.DoesNotExist):
                call()
        self.assertEqual(SellerOrder.objects.get(pk=self.so1.pk).status, 'new')


class ExpireCommandTests(FlowBase):
    def test_command_cancels_only_overdue_new_orders_and_returns_stock(self):
        from django.core.management import call_command
        from io import StringIO
        SellerOrder.objects.filter(pk=self.so1.pk).update(accept_by=timezone.now() - timezone.timedelta(minutes=1))
        out = StringIO()
        call_command('expire_seller_orders', stdout=out)
        self.assertIn('Cancelled 1', out.getvalue())
        self.assertEqual(SellerOrder.objects.get(pk=self.so1.pk).status, 'cancelled')
        self.assertEqual(SellerOrder.objects.get(pk=self.so2.pk).status, 'new')          # still inside its window
        self.assertEqual(self.stock(self.p1), 10)
