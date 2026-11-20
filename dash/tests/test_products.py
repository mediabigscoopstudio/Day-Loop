import json
from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catalog.models import Product

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class ProductListTests(DashTestCase):
    def setUp(self):
        super().setUp()
        self.well, self.care = f.make_category('Wellness'), f.make_category('Care')
        self.prot, self.vit = f.make_category('Protein', self.well), f.make_category('Vitamins', self.well)
        self.skin = f.make_category('Skin', self.care)
        self.s1, self.s2 = f.make_seller('Prana'), f.make_seller('Ayura')
        self.a = f.make_product(self.s1, self.prot, '1500', stock=50, name='Whey', brand='Prana', sku='W1')
        self.b = f.make_product(self.s1, self.vit, '300', stock=5, name='VitC', brand='Prana')
        self.c = f.make_product(self.s2, self.skin, '800', stock=0, name='Cream', brand='Ayura', is_active=False)
        self.login_as(self.superuser)

    def names(self, qs=''):
        r = self.client.get('/products/' + qs)
        self.assertEqual(r.status_code, 200, qs)
        return {p.name for p in r.context['page'].object_list}

    def test_each_filter(self):
        self.assertEqual(self.names(), {'Whey', 'VitC', 'Cream'})
        self.assertEqual(self.names(f'?seller={self.s2.pk}'), {'Cream'})
        self.assertEqual(self.names(f'?category={self.well.pk}'), {'Whey', 'VitC'})
        self.assertEqual(self.names(f'?category={self.well.pk}&subcategory={self.vit.pk}'), {'VitC'})
        self.assertEqual(self.names('?brand=ayura'), {'Cream'})
        self.assertEqual(self.names('?status=inactive'), {'Cream'})
        self.assertEqual(self.names('?status=active'), {'Whey', 'VitC'})
        self.assertEqual(self.names('?price_min=500&price_max=1000'), {'Cream'})
        self.assertEqual(self.names('?stock=out'), {'Cream'})
        self.assertEqual(self.names('?stock=low'), {'VitC'})
        self.assertEqual(self.names('?stock=in'), {'Whey'})
        self.assertEqual(self.names('?q=w1'), {'Whey'})
        self.assertEqual(self.names('?q=ayura'), {'Cream'})

    def test_date_filter(self):
        old = timezone.now() - timedelta(days=40)
        Product.objects.filter(pk=self.a.pk).update(created_at=old)
        today = timezone.localdate().isoformat()
        self.assertEqual(self.names(f'?date_from={today}'), {'VitC', 'Cream'})
        self.assertEqual(self.names(f'?date_to={(old + timedelta(days=1)).date().isoformat()}'), {'Whey'})

    def test_bad_filter_values_are_ignored(self):
        self.assertEqual(self.names('?seller=x&price_min=abc&date_from=nope&stock=zzz&status=bogus&page=-3'),
                         {'Whey', 'VitC', 'Cream'})

    def test_sorting(self):
        r = self.client.get('/products/?sort=price&dir=desc')
        self.assertEqual([p.name for p in r.context['page'].object_list], ['Whey', 'Cream', 'VitC'])
        r = self.client.get('/products/?sort=name&dir=asc')
        self.assertEqual([p.name for p in r.context['page'].object_list], ['Cream', 'VitC', 'Whey'])

    def test_no_n_plus_one(self):
        self.client.get('/products/')
        with CaptureQueriesContext(connection) as small:
            self.client.get('/products/')
        for i in range(12):
            f.make_product(self.s1, self.prot, '100', name=f'Extra {i}')
        with CaptureQueriesContext(connection) as large:
            self.client.get('/products/')
        self.assertEqual(len(small), len(large))

    def test_empty_states(self):
        Product.objects.all().delete()
        self.assertContains(self.client.get('/products/'), 'No products yet')
        f.make_product(self.s1, self.prot)
        self.assertContains(self.client.get('/products/?q=zzzz'), 'No products match')


class ProductActionTests(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        s = f.make_seller()
        self.p1, self.p2 = f.make_product(s, sub), f.make_product(s, sub)
        self.login_as(self.superuser)

    def test_toggle_has_a_warning_popup_then_applies(self):
        page = self.client.get(f'/products/{self.p1.pk}/toggle/', **HX)
        self.assertContains(page, 'no longer be able to see or buy')
        r = self.client.post(f'/products/{self.p1.pk}/toggle/', **HX)
        self.assertEqual(r.status_code, 204)
        self.p1.refresh_from_db(); self.assertEqual(self.p1.status, 'inactive')

    def test_bulk_confirm_then_apply(self):
        page = self.client.get(f'/products/bulk/?action=deactivate&ids={self.p1.pk}&ids={self.p2.pk}', **HX)
        self.assertContains(page, 'Deactivate 2 products')
        r = self.client.post('/products/bulk/', {'action': 'deactivate', 'ids': f'{self.p1.pk},{self.p2.pk}'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.assertIn('2 products deactivated', json.loads(r['HX-Trigger'])['toast']['message'])
        self.assertEqual(Product.objects.filter(status='live').count(), 0)
        self.client.post('/products/bulk/', {'action': 'activate', 'ids': str(self.p1.pk)}, **HX)
        self.assertEqual(Product.objects.filter(status='live').count(), 1)

    def test_bulk_with_nothing_selected_is_handled(self):
        self.assertContains(self.client.get('/products/bulk/?action=activate', **HX), 'Select at least one')
        self.assertEqual(self.client.post('/products/bulk/', {'action': 'activate', 'ids': ''}, **HX).status_code, 422)
        self.assertEqual(self.client.post('/products/bulk/', {'action': 'delete', 'ids': '1'}, **HX).status_code, 422)

    def test_detail_modal(self):
        self.assertContains(self.client.get(f'/products/{self.p1.pk}/', **HX), self.p1.name)
        self.assertEqual(self.client.get('/products/999999/', **HX).status_code, 404)

    def test_non_superusers_forbidden(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for method, url in (('get', '/products/'), ('get', f'/products/{self.p1.pk}/'), ('post', f'/products/{self.p1.pk}/toggle/'),
                                ('get', '/products/bulk/?action=activate&ids=1'), ('post', '/products/bulk/')):
                r = getattr(self.client, method)(url, {'action': 'deactivate', 'ids': str(self.p1.pk)}, **HX)
                self.assertEqual(r.status_code, 403, f'{method} {url} {user.username}')
        self.p1.refresh_from_db(); self.assertEqual(self.p1.status, 'live')


class ProductReviewStateTests(DashTestCase):
    def test_bulk_and_toggle_only_touch_live_and_inactive_products(self):
        sub = f.make_category('S', f.make_category('C')); s = f.make_seller()
        draft = f.make_product(s, sub, status='draft'); pending = f.make_product(s, sub, status='pending')
        live = f.make_product(s, sub)
        self.login_as(self.superuser)
        self.client.post('/products/bulk/', {'action': 'deactivate', 'ids': f'{draft.pk},{pending.pk},{live.pk}'}, **HX)
        draft.refresh_from_db(); pending.refresh_from_db(); live.refresh_from_db()
        self.assertEqual((draft.status, pending.status, live.status), ('draft', 'pending', 'inactive'))
        self.assertEqual(self.client.post(f'/products/{pending.pk}/toggle/', **HX).status_code, 422)
        self.assertContains(self.client.get(f'/products/{draft.pk}/toggle/', **HX), 'is draft')
