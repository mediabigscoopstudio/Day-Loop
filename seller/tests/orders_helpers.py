from dash.tests import factories as f
from orders.services.checkout import create_order

from .base import SellerTestCase

HX = {'HTTP_HX_REQUEST': 'true'}
ADDRESS = dict(name='Priya Sharma', line1='12 MG Road', city='Pune', state='Maharashtra', pincode='411001')


class OrdersCase(SellerTestCase):
    """One customer checkout containing items from sellers A and B. Seller A is logged in."""

    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.pa1 = f.make_product(self.a, sub, '1000', stock=20, name='Alpha Whey')
        self.pa2 = f.make_product(self.a, sub, '500', stock=20, name='Alpha Bar')
        self.pb = f.make_product(self.b, sub, '2000', stock=20, name='Beta Secret Tonic')
        self.buyer = f.make_user('buyer')
        self.order = create_order(self.buyer, [(self.pa1.variant.pk, 2), (self.pa2.variant.pk, 1), (self.pb.variant.pk, 3)], ADDRESS, payment_method='UPI')
        self.so_a = self.order.seller_orders.get(seller=self.a)
        self.so_b = self.order.seller_orders.get(seller=self.b)
        self.login_as(self.a.user)

    def stock(self, p):
        from catalog.models import ProductVariant
        return ProductVariant.objects.get(pk=p.variant.pk).stock

    def ship_a(self):
        for _ in range(2):
            self.client.post(f'/orders/{self.so_a.pk}/advance/', **HX)
        return self.client.post(f'/orders/{self.so_a.pk}/advance/', {'courier': 'Delhivery', 'awb': 'DL123456', 'tracking_url': 'https://t.example/DL123456'}, **HX)
