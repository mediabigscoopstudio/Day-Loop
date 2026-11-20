from decimal import Decimal as D

from orders.models import LedgerEntry, SellerOrder

from .orders_helpers import HX, OrdersCase


class VisibilityTests(OrdersCase):
    def test_checkout_made_one_order_and_two_seller_orders(self):
        self.assertEqual(self.order.seller_orders.count(), 2)
        self.assertEqual({it.seller_id for it in self.so_a.items.all()}, {self.a.pk})
        self.assertEqual({it.seller_id for it in self.so_b.items.all()}, {self.b.pk})

    def test_list_shows_only_my_shipment(self):
        r = self.client.get('/orders/')
        rows = list(r.context['page'].object_list)
        self.assertEqual([so.pk for so in rows], [self.so_a.pk])
        self.assertContains(r, self.so_a.invoice_number)
        self.assertNotContains(r, self.so_b.invoice_number)
        self.assertContains(r, f'Shipment {self.so_a.shipment_index} of 2')

    def test_detail_popup_never_shows_another_sellers_items_or_money(self):
        r = self.client.get(f'/orders/{self.so_a.pk}/', **HX)
        for text in ('Alpha Whey', 'Alpha Bar', 'Pune', '12 MG Road', 'Your payout'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'Beta Secret Tonic')
        self.assertNotContains(r, self.so_b.invoice_number)
        self.assertNotContains(r, '6,000')                                   # B's purchase value
        self.assertContains(r, '− ₹125.00'); self.assertContains(r, '− ₹22.50'); self.assertContains(r, '₹2,352.50')   # A: 2,500 -> 125 / 22.50 / 2,352.50

    def test_packing_slip_and_label_contain_only_my_items(self):
        for path in ('packing-slip', 'label'):
            r = self.client.get(f'/orders/{self.so_a.pk}/{path}/')
            self.assertEqual(r.status_code, 200, path)
            self.assertContains(r, self.so_a.invoice_number); self.assertContains(r, 'Priya Sharma'); self.assertContains(r, '411001')
            self.assertNotContains(r, 'Beta Secret Tonic'); self.assertNotContains(r, self.so_b.invoice_number)
        slip = self.client.get(f'/orders/{self.so_a.pk}/packing-slip/')
        self.assertContains(slip, 'Alpha Whey'); self.assertContains(slip, self.a.business_name)
        label = self.client.get(f'/orders/{self.so_a.pk}/label/')
        self.assertContains(label, 'Alpha Bar'); self.assertContains(label, 'Units: <strong>3</strong>')

    def test_seller_b_sees_only_their_own_shipment(self):
        self.login_as(self.b.user)
        r = self.client.get('/orders/')
        self.assertEqual([so.pk for so in r.context['page'].object_list], [self.so_b.pk])
        self.assertNotContains(r, self.so_a.invoice_number)
        self.assertContains(self.client.get(f'/orders/{self.so_b.pk}/', **HX), 'Beta Secret Tonic')


class CrossSellerAccessTests(OrdersCase):
    def test_every_endpoint_404s_for_another_sellers_order(self):
        base = f'/orders/{self.so_b.pk}/'
        urls = [('get', base), ('get', base + 'advance/'), ('post', base + 'advance/'), ('get', base + 'cancel/'), ('post', base + 'cancel/'),
                ('get', base + 'return/'), ('post', base + 'return/'), ('get', base + 'packing-slip/'), ('get', base + 'label/')]
        for method, url in urls:
            r = getattr(self.client, method)(url, {'reason': 'x', 'courier': 'X', 'awb': 'Y'}, **HX)
            self.assertEqual(r.status_code, 404, f'{method} {url}')
        self.so_b.refresh_from_db()
        self.assertEqual(self.so_b.status, 'new'); self.assertEqual(self.so_b.events.count(), 1)
        self.assertEqual(self.stock(self.pb), 17)                            # B's stock untouched
        self.assertFalse(LedgerEntry.objects.exists())

    def test_list_filters_cannot_reach_other_sellers_data(self):
        r = self.client.get(f'/orders/?product={self.pb.pk}')
        self.assertEqual(list(r.context['page'].object_list), [])
        self.assertEqual(len(self.client.get(f'/orders/?q={self.so_b.invoice_number}').context['page'].object_list), 0)

    def test_unapproved_non_sellers_and_anonymous_are_denied(self):
        for user in (self.pending.user, self.draft.user, self.customer):
            self.login_as(user)
            for url in (f'/orders/{self.so_a.pk}/', f'/orders/{self.so_a.pk}/advance/'):
                self.assertEqual(self.client.get(url, **HX).status_code, 403, url)
            self.assertEqual(self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': 'x'}, **HX).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(f'/orders/{self.so_a.pk}/', **HX).status_code, 403)
        self.so_a.refresh_from_db(); self.assertEqual(self.so_a.status, 'new')

    def test_cancelling_my_shipment_does_not_change_the_other_sellers(self):
        before = {k: getattr(self.so_b, k) for k in ('status', 'purchase_value', 'margin', 'payout', 'invoice_number')}
        self.client.post(f'/orders/{self.so_a.pk}/cancel/', {'reason': 'Out of stock'}, **HX)
        self.so_a.refresh_from_db(); self.so_b.refresh_from_db()
        self.assertEqual(self.so_a.status, 'cancelled')
        self.assertEqual({k: getattr(self.so_b, k) for k in before}, before)
        self.assertEqual((self.stock(self.pa1), self.stock(self.pb)), (20, 17))
