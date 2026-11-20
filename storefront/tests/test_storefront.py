from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase

from dash.tests import factories as f
from orders.models import Order
from storefront import delivery, gateway
from storefront.cart import SESSION_CART_KEY, add_to_cart, get_cart, merge_session_cart
from storefront.emi import emi_options
from storefront.models import Address, Cart
from storefront.selectors import visible_products

User = get_user_model()
HOST = {'HTTP_HOST': 'www.localhost'}
HX = {**HOST, 'HTTP_HX_REQUEST': 'true'}


class Base(TestCase):
    def setUp(self):
        sub = f.make_category('Whey', f.make_category('Protein'))
        self.s1, self.s2 = f.make_seller('Optimum Nutrition'), f.make_seller('Kapiva')
        self.p1 = f.make_product(self.s1, sub, '1000', stock=10, name='Gold Whey')
        self.p2 = f.make_product(self.s2, sub, '500', stock=10, name='Shilajit')
        self.user = User.objects.create_user('cust@x.test', 'cust@x.test', 'pw-Str0ng-123')
        self.other = User.objects.create_user('other@x.test', 'other@x.test', 'pw-Str0ng-123')
        self.addr = Address.objects.create(user=self.user, name='Cust', line1='1 Road', city='Bengaluru', state='KA', pincode='560038', is_default=True)

    def login(self):
        self.client.login(username='cust@x.test', password='pw-Str0ng-123')


class VisibilityTests(Base):
    def test_only_live_products_of_approved_sellers_with_stock(self):
        sub = self.p1.subcategory
        draft = f.make_product(self.s1, sub, '100', status='draft', name='Draft')
        pending = f.make_product(f.make_seller('Pending Co', status='pending'), sub, '100', name='Pending seller')
        oos = f.make_product(self.s1, sub, '100', stock=0, name='Sold out')
        names = set(visible_products().values_list('name', flat=True))
        self.assertEqual(names, {'Gold Whey', 'Shilajit'})
        r = self.client.get('/products/', **HOST)
        for hidden in (draft, pending, oos):
            self.assertNotContains(r, hidden.name)
        self.assertEqual(self.client.get(f'/product/{draft.slug}/', **HOST).status_code, 404)


class CartTests(Base):
    def test_guest_cart_lives_in_session_and_merges_on_signin(self):
        self.client.post('/cart/add/', {'variant_id': self.p1.variant.pk, 'quantity': 2}, **HOST)
        self.assertEqual(self.client.session[SESSION_CART_KEY], {str(self.p1.variant.pk): 2})
        Cart.objects.create(user=self.user).items.create(variant=self.p1.variant, quantity=1)
        r = self.client.post('/modal/login/', {'identifier': 'cust@x.test', 'password': 'pw-Str0ng-123'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Cart.objects.get(user=self.user).items.get().quantity, 3)
        self.assertNotIn(SESSION_CART_KEY, self.client.session)

    def test_cart_groups_by_seller_and_flags_low_stock(self):
        self.login()
        for p in (self.p1, self.p2):
            self.client.post('/cart/add/', {'variant_id': p.variant.pk}, **HX)
        cart = get_cart(type('R', (), {'user': self.user, 'session': self.client.session})())
        self.assertEqual(len(cart['groups']), 2)
        self.client.post('/cart/update/', {'variant_id': self.p1.variant.pk, 'quantity': 3}, **HX)
        self.p1.variant.stock = 1
        self.p1.variant.save()
        r = self.client.get('/cart/', **HOST)
        self.assertContains(r, 'Only 1 left in stock')
        self.assertContains(r, 'Shipment 1 of 2 from')

    def test_add_rejects_more_than_stock(self):
        r = self.client.post('/cart/add/', {'variant_id': self.p1.variant.pk, 'quantity': 99}, **HX)
        self.assertEqual(r.status_code, 422)


class DeliveryTests(TestCase):
    def test_tiers(self):
        self.assertEqual(delivery.tier_for('Indiranagar', 'Bengaluru'), delivery.FASTEST)
        self.assertEqual(delivery.tier_for('Unknown', 'Bengaluru'), delivery.SAME_DAY)
        self.assertEqual(delivery.tier_for('Bandra', 'Mumbai'), delivery.SCHEDULED)
        self.assertEqual(delivery.tier_for('Nowhere', 'Nowhere'), delivery.SCHEDULED)

    def test_options_grey_out_with_reason(self):
        opts = {o['key']: o for o in delivery.options_for(delivery.SAME_DAY)}
        self.assertFalse(opts['fastest']['available'])
        self.assertTrue(opts['fastest']['reason'])
        self.assertTrue(opts['scheduled']['available'])

    def test_eta_uses_dispatch_days(self):
        from datetime import date
        self.assertEqual(delivery.eta_for(delivery.FASTEST, 0), 'Within 15 min')
        self.assertEqual(delivery.eta_for(delivery.SCHEDULED, 2, today=date(2026, 1, 1)), 'Tue, 06 Jan')


class EmiTests(TestCase):
    def test_emi_options(self):
        o = emi_options('9000')
        self.assertEqual([(x['months'], x['monthly']) for x in o], [(3, D('3000')), (6, D('1500')), (9, D('1000'))])


class CheckoutTests(Base):
    def _fill(self):
        self.login()
        for p in (self.p1, self.p2):
            self.client.post('/cart/add/', {'variant_id': p.variant.pk}, **HX)

    def test_pay_creates_one_order_with_separate_seller_orders(self):
        self._fill()
        r = self.client.post('/checkout/pay/', {'payment_method': 'upi'}, **HX)
        self.assertContains(r, 'Simulate success')
        r = self.client.post('/checkout/pay/confirm/', {'payment_method': 'upi', 'simulate': 'success'}, **HX)
        self.assertEqual(r.status_code, 204)
        order = Order.objects.get()
        self.assertEqual(order.seller_orders.count(), 2)
        self.assertEqual(len({so.invoice_number for so in order.seller_orders.all()}), 2)
        self.p1.variant.refresh_from_db()
        self.assertEqual(self.p1.variant.stock, 9)
        self.assertEqual(self.client.get('/cart/', **HOST).context['cart']['total_items'], 0)

    def test_failed_payment_creates_no_order(self):
        self._fill()
        r = self.client.post('/checkout/pay/confirm/', {'payment_method': 'card', 'simulate': 'failure'}, **HX)
        self.assertContains(r, 'Retry payment')
        self.assertEqual(Order.objects.count(), 0)

    def test_gateway(self):
        self.assertFalse(gateway.charge(10, 'upi', 'failure').ok)
        self.assertTrue(gateway.charge(10, 'cod', 'failure').ok)


class PrivacyTests(Base):
    def test_customer_cannot_see_anothers_order(self):
        order = f.make_order(self.other, __import__('django').utils.timezone.now(), [(self.p1, 1)])
        self.login()
        self.assertEqual(self.client.get(f'/account/orders/{order.number}/', **HOST).status_code, 404)
        self.assertEqual(self.client.get(f'/order/confirmation/{order.number}/', **HOST).status_code, 404)
        self.assertNotContains(self.client.get('/account/orders/', **HOST), order.number)


class PopupTests(Base):
    def test_popups_return_fragments(self):
        self.login()
        for url in ('/modal/login/', '/modal/area/', '/modal/schedule/', f'/emi/{self.p1.variant.pk}/',
                    f'/cart/remove/{self.p1.variant.pk}/', '/account/addresses/new/', '/modal/logout/',
                    '/products/filters/', '/checkout/address/'):
            r = self.client.get(url, **HX)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, '<dialog', msg_prefix=url)
            self.assertNotContains(r, '<html', msg_prefix=url)

    def test_pages_render(self):
        self.login()
        for url in ('/', '/products/', f'/product/{self.p1.slug}/', '/cart/', '/account/', '/account/orders/',
                    '/account/addresses/', '/account/subscriptions/', '/search/?q=whey'):
            self.assertEqual(self.client.get(url, **HOST).status_code, 200, url)

    def test_logout_needs_post_and_confirmation(self):
        self.login()
        self.assertEqual(self.client.post('/modal/logout/', **HX).status_code, 204)
        self.assertEqual(self.client.get('/account/', **HOST).status_code, 302)
