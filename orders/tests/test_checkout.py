from decimal import Decimal as D

from django.test import TestCase

from catalog.models import ProductVariant, StockMovement
from dash.tests import factories as f
from orders.models import Order, OrderItem, SellerOrder
from orders.services.checkout import CheckoutError, create_order, shipment_labels

ADDRESS = dict(name='Priya Sharma', line1='12 MG Road', city='Pune', state='Maharashtra', pincode='411001')


class CheckoutBase(TestCase):
    def setUp(self):
        sub = f.make_category('S', f.make_category('C'))
        self.s1, self.s2, self.s3 = f.make_seller('Prana'), f.make_seller('Ayura'), f.make_seller('Nourish')
        self.p1 = f.make_product(self.s1, sub, '1000', stock=10)      # Prana
        self.p2 = f.make_product(self.s1, sub, '500', stock=10)       # Prana
        self.p3 = f.make_product(self.s2, sub, '2000', stock=10)      # Ayura
        self.p4 = f.make_product(self.s3, sub, '300', stock=10)       # Nourish
        self.customer = f.make_user('cust')

    def order(self, lines=None):
        lines = lines or [(self.p1.variant.pk, 2), (self.p2.variant.pk, 1), (self.p3.variant.pk, 1)]
        return create_order(self.customer, lines, ADDRESS, payment_method='UPI')


class MultiSellerCheckoutTests(CheckoutBase):
    def test_one_order_and_one_seller_order_per_seller(self):
        order = self.order()
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(order.seller_orders.count(), 2)
        self.assertEqual({so.seller_id for so in order.seller_orders.all()}, {self.s1.pk, self.s2.pk})
        self.assertEqual(order.ship_city, 'Pune')            # one address snapshot for the whole checkout

    def test_items_never_mix_between_sellers(self):
        order = self.order()
        for so in order.seller_orders.all():
            self.assertTrue(so.items.exists())
            self.assertEqual({it.seller_id for it in so.items.all()}, {so.seller_id})
            self.assertEqual({it.variant.seller_id for it in so.items.all()}, {so.seller_id})
        prana = order.seller_orders.get(seller=self.s1)
        self.assertEqual(sorted(it.quantity for it in prana.items.all()), [1, 2])
        self.assertEqual(order.seller_orders.get(seller=self.s2).items.count(), 1)

    def test_seller_order_totals_and_money_snapshot(self):
        order = self.order()
        prana = order.seller_orders.get(seller=self.s1)       # 2 x 1000 + 1 x 500 = 2500
        self.assertEqual(prana.purchase_value, D('2500.00'))
        self.assertEqual((prana.margin, prana.margin_gst, prana.payout), (D('125.00'), D('22.50'), D('2352.50')))
        self.assertEqual((prana.commission_rate, prana.gst_rate_on_margin), (D('0.0500'), D('0.1800')))
        ayura = order.seller_orders.get(seller=self.s2)       # 2000
        self.assertEqual((ayura.margin, ayura.margin_gst, ayura.payout), (D('100.00'), D('18.00'), D('1882.00')))

    def test_order_total_is_all_taxable_values_plus_customer_gst(self):
        order = self.order()
        taxable = D('2500') + D('2000')
        gst = sum((it.gst_amount for it in OrderItem.objects.filter(order=order)), D('0'))
        self.assertEqual(gst, taxable * D('0.18'))                 # variants default to 18% GST
        self.assertEqual(order.total, taxable + gst)

    def test_invoice_numbers_are_per_seller_and_sequential(self):
        a, b = self.order(), self.order()
        inv_a = a.seller_orders.get(seller=self.s1).invoice_number
        inv_b = b.seller_orders.get(seller=self.s1).invoice_number
        self.assertEqual(inv_a, f'DL-{self.s1.code}-000001')
        self.assertEqual(inv_b, f'DL-{self.s1.code}-000002')
        self.assertEqual(a.seller_orders.get(seller=self.s2).invoice_number, f'DL-{self.s2.code}-000001')

    def test_shipment_labels_make_the_split_clear(self):
        labels = shipment_labels(self.order())
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(l.startswith('Shipment ') and ' of 2 from ' in l for l in labels))

    def test_stock_is_taken_and_timeline_started(self):
        order = self.order()
        self.assertEqual(ProductVariant.objects.get(pk=self.p1.variant.pk).stock, 8)
        self.assertEqual(ProductVariant.objects.get(pk=self.p3.variant.pk).stock, 9)
        self.assertEqual(StockMovement.objects.filter(kind='sale').count(), 3)
        for so in order.seller_orders.all():
            self.assertEqual([e.status for e in so.events.all()], ['new'])
            self.assertIsNotNone(so.accept_by)


class CheckoutFailureTests(CheckoutBase):
    def test_not_enough_stock_rolls_everything_back(self):
        with self.assertRaises(CheckoutError):
            self.order([(self.p1.variant.pk, 2), (self.p3.variant.pk, 99)])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(ProductVariant.objects.get(pk=self.p1.variant.pk).stock, 10)
        self.assertFalse(StockMovement.objects.exists())

    def test_unavailable_items_are_refused_without_side_effects(self):
        self.p4.status = 'inactive'; self.p4.save()
        with self.assertRaises(CheckoutError):
            self.order([(self.p4.variant.pk, 1)])
        self.s2.status = 'pending'; self.s2.save()
        with self.assertRaises(CheckoutError):
            self.order([(self.p3.variant.pk, 1)])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(ProductVariant.objects.get(pk=self.p3.variant.pk).stock, 10)

    def test_empty_cart_and_moq(self):
        with self.assertRaises(CheckoutError):
            create_order(self.customer, [], ADDRESS)
        ProductVariant.objects.filter(pk=self.p1.variant.pk).update(moq=5)
        with self.assertRaises(CheckoutError):
            self.order([(self.p1.variant.pk, 2)])
        self.assertEqual(Order.objects.count(), 0)
