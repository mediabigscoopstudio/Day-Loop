import json

from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import get_resolver

from catalog.models import Category

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class CategoryCrudTests(DashTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.superuser)

    def create(self, **data):
        return self.client.post('/products/categories/new/', data, **HX)

    def test_create_category_and_subcategory_with_unique_slugs(self):
        r = self.create(name='Wellness', is_active='on')
        self.assertEqual(r.status_code, 204)
        self.assertTrue(json.loads(r['HX-Trigger'])['categories-changed'])
        top = Category.objects.get(name='Wellness')
        self.assertEqual(top.slug, 'wellness')
        self.assertEqual(self.create(name='Protein', parent=top.pk, is_active='on').status_code, 204)
        self.assertEqual(self.create(name='Wellness', parent=top.pk, is_active='on').status_code, 204)  # same name, other level
        slugs = list(Category.objects.values_list('slug', flat=True))
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(Category.objects.get(name='Protein').parent, top)

    def test_duplicate_name_in_same_parent_is_rejected_inline(self):
        self.create(name='Care', is_active='on')
        r = self.create(name='care', is_active='on')
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, 'already exists', status_code=422)

    def test_name_required(self):
        self.assertEqual(self.create(name='   ').status_code, 422)

    def test_depth_is_limited_to_two_levels(self):
        top = f.make_category('Top'); sub = f.make_category('Sub', parent=top)
        r = self.create(name='Too deep', parent=sub.pk)
        self.assertEqual(r.status_code, 422)                      # parent not offered by the form
        self.assertFalse(Category.objects.filter(name='Too deep').exists())
        with self.assertRaises(ValidationError):                   # and the model enforces it on save
            Category.objects.create(name='Too deep', parent=sub)

    def test_top_level_with_children_cannot_become_a_subcategory(self):
        a = f.make_category('A'); f.make_category('A1', parent=a); b = f.make_category('B')
        r = self.client.post(f'/products/categories/{a.pk}/edit/', {'name': 'A', 'parent': b.pk, 'is_active': 'on'}, **HX)
        a.refresh_from_db()
        self.assertIsNone(a.parent_id)

    def test_edit_and_toggle(self):
        c = f.make_category('Old')
        self.assertEqual(self.client.post(f'/products/categories/{c.pk}/edit/', {'name': 'New', 'is_active': 'on'}, **HX).status_code, 204)
        c.refresh_from_db(); self.assertEqual((c.name, c.is_active), ('New', True))
        self.assertContains(self.client.get(f'/products/categories/{c.pk}/toggle/', **HX), 'Deactivate')
        self.client.post(f'/products/categories/{c.pk}/toggle/', **HX)
        c.refresh_from_db(); self.assertFalse(c.is_active)

    def test_delete_blocked_when_products_attached(self):
        top = f.make_category('Top'); sub = f.make_category('Sub', parent=top)
        f.make_product(f.make_seller(), sub)
        for target in (sub, top):
            page = self.client.get(f'/products/categories/{target.pk}/delete/', **HX)
            self.assertContains(page, 'is in use')
            r = self.client.post(f'/products/categories/{target.pk}/delete/', **HX)
            self.assertEqual(r.status_code, 422)
            self.assertTrue(Category.objects.filter(pk=target.pk).exists())

    def test_delete_blocked_for_top_level_with_subcategories_even_without_products(self):
        top = f.make_category('Top'); f.make_category('Sub', parent=top)
        self.assertEqual(self.client.post(f'/products/categories/{top.pk}/delete/', **HX).status_code, 422)

    def test_delete_confirm_then_delete_when_unused(self):
        c = f.make_category('Empty')
        page = self.client.get(f'/products/categories/{c.pk}/delete/', **HX)
        self.assertContains(page, 'This cannot be undone')
        self.assertEqual(self.client.post(f'/products/categories/{c.pk}/delete/', **HX).status_code, 204)
        self.assertFalse(Category.objects.filter(pk=c.pk).exists())

    def test_reorder_swaps_and_renumbers(self):
        a, b, c = (f.make_category(n) for n in 'ABC')
        for i, x in enumerate((a, b, c)):
            Category.objects.filter(pk=x.pk).update(sort_order=i)
        self.client.post(f'/products/categories/{c.pk}/move/up/', **HX)
        order = list(Category.objects.order_by('sort_order').values_list('name', flat=True))
        self.assertEqual(order, ['A', 'C', 'B'])
        self.client.post(f'/products/categories/{a.pk}/move/up/', **HX)   # already first: unchanged
        self.assertEqual(list(Category.objects.order_by('sort_order').values_list('name', flat=True)), ['A', 'C', 'B'])

    def test_page_lists_counts(self):
        top = f.make_category('Top'); sub = f.make_category('Sub', parent=top)
        f.make_product(f.make_seller(), sub); f.make_product(f.make_seller(), sub)
        r = self.client.get('/products/categories/')
        self.assertContains(r, '1 subcategory · 2 products')

    def test_subcategory_options_endpoint_returns_only_active_children(self):
        top = f.make_category('Top'); a = f.make_category('Alive', parent=top); d = f.make_category('Dead', parent=top)
        Category.objects.filter(pk=d.pk).update(is_active=False)
        r = self.client.get(f'/products/subcategory-options/?category={top.pk}', **HX)
        self.assertContains(r, 'Alive'); self.assertNotContains(r, 'Dead')


class CategoryAccessTests(DashTestCase):
    URLS = [('get', '/products/categories/'), ('get', '/products/categories/new/'), ('post', '/products/categories/new/'),
            ('get', '/products/categories/{pk}/edit/'), ('post', '/products/categories/{pk}/edit/'),
            ('get', '/products/categories/{pk}/toggle/'), ('post', '/products/categories/{pk}/toggle/'),
            ('get', '/products/categories/{pk}/delete/'), ('post', '/products/categories/{pk}/delete/'),
            ('post', '/products/categories/{pk}/move/up/'), ('get', '/products/subcategory-options/')]

    def test_only_superusers_can_manage_categories(self):
        cat = f.make_category('Protected')
        for user in (self.staff, self.customer, self.seller_user, None):
            self.client.logout()
            if user:
                self.login_as(user)
            for method, url in self.URLS:
                r = getattr(self.client, method)(url.format(pk=cat.pk), {'name': 'Hacked', 'is_active': 'on'}, **HX)
                self.assertEqual(r.status_code, 403, f'{method} {url} as {getattr(user, "username", "anonymous")}')
        cat.refresh_from_db()
        self.assertEqual(cat.name, 'Protected')
        self.assertTrue(Category.objects.filter(pk=cat.pk).exists())
        self.assertEqual(Category.objects.count(), 1)

    def test_seller_and_www_hosts_expose_no_category_endpoints(self):
        for module in ('dayloop.urls_seller', 'dayloop.urls_www', 'dayloop.urls_api'):
            for pattern in get_resolver(module).url_patterns:
                self.assertNotIn('categor', str(pattern.pattern).lower(), module)
        cat = f.make_category('Protected')
        approved_seller = f.make_seller('Real Seller')           # an approved seller with a profile
        for host, cookie, user in (('seller.localhost:8000', 'dl_seller_sid', approved_seller.user),
                                   ('www.localhost:8000', 'dl_www_sid', self.customer),
                                   ('api.localhost:8000', 'dl_api_sid', self.customer)):
            c = Client(HTTP_HOST=host)
            with override_settings(SESSION_COOKIE_NAME=cookie):
                c.force_login(user)
            for path in ('/products/categories/new/', '/categories/new/', f'/categories/{cat.pk}/edit/',
                         f'/products/categories/{cat.pk}/delete/', '/api/categories/'):
                for method in ('get', 'post'):
                    self.assertEqual(getattr(c, method)(path, {'name': 'X'}).status_code, 404, f'{host} {method} {path}')
        self.assertEqual(Category.objects.count(), 1)
