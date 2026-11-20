import json

from django.db import connection
from django.test.utils import CaptureQueriesContext

from catalog.models import Product
from dash.tests import factories as f

from .product_helpers import HX, ProductCase


class ProductListTests(ProductCase):
    def setUp(self):
        super().setUp()
        self.live = f.make_product(self.a, self.sub, '800', stock=50, name='Live One')
        self.low = f.make_product(self.a, self.sub2, '300', stock=4, name='Low Stock')
        self.out = f.make_product(self.a, self.sub, '100', stock=0, name='Out Item', is_active=False)
        self.draft = self.product(name='Draft Item')
        self.theirs = f.make_product(self.b, self.sub, '999', stock=9, name='Beta Secret')

    def names(self, qs=''):
        r = self.client.get('/products/' + qs)
        self.assertEqual(r.status_code, 200, qs)
        return {p.name for p in r.context['page'].object_list}

    def test_only_my_products_are_listed(self):
        names = self.names()
        self.assertEqual(names, {'Live One', 'Low Stock', 'Out Item', 'Draft Item'})
        self.assertNotContains(self.client.get('/products/'), 'Beta Secret')

    def test_filters_tabs_and_search(self):
        self.assertEqual(self.names('?status=live'), {'Live One', 'Low Stock'})
        self.assertEqual(self.names('?status=inactive'), {'Out Item'})
        self.assertEqual(self.names('?status=draft'), {'Draft Item'})
        self.assertEqual(self.names(f'?category={self.cat2.pk}'), {'Low Stock'})
        self.assertEqual(self.names('?stock=low'), {'Low Stock'})
        self.assertEqual(self.names('?stock=out'), {'Out Item', 'Draft Item'})      # a draft with no variants has no stock
        self.assertEqual(self.names('?stock=in'), {'Live One'})
        self.assertEqual(self.names('?q=live'), {'Live One'})
        self.assertEqual(self.names('?status=bogus&category=x&stock=zzz&page=-9'), {'Live One', 'Low Stock', 'Out Item', 'Draft Item'})

    def test_status_tab_counts_are_mine_only(self):
        counts = self.client.get('/products/').context['counts']
        self.assertEqual((counts['all'], counts['live'], counts['inactive'], counts['draft']), (4, 2, 1, 1))

    def test_no_n_plus_one(self):
        self.client.get('/products/')
        with CaptureQueriesContext(connection) as small:
            self.client.get('/products/')
        for i in range(10):
            f.make_product(self.a, self.sub, '100', name=f'Extra {i}')
        with CaptureQueriesContext(connection) as large:
            self.client.get('/products/')
        self.assertEqual(len(small), len(large))

    def test_cards_for_phones_and_table_for_desktop_are_both_present(self):
        r = self.client.get('/products/')
        self.assertContains(r, 'class="table-wrap show-desktop"'); self.assertContains(r, 'class="card-list show-mobile"')

    def test_empty_states_and_notices(self):
        Product.objects.filter(seller=self.a).delete()
        self.assertContains(self.client.get('/products/'), 'No products yet')
        self.product(name='Only')
        self.assertContains(self.client.get('/products/?q=zzzz'), 'No products match')
        self.assertContains(self.client.get('/products/?submitted=1'), 'submitted for review')
        self.assertContains(self.client.get('/products/?notice=review'), 'being reviewed')

    def test_unapproved_sellers_cannot_open_the_list(self):
        self.login_as(self.pending.user)
        r = self.client.get('/products/')
        self.assertEqual((r.status_code, r['Location']), (302, '/status/'))
        self.assertEqual(self.client.get('/products/', **HX).status_code, 403)


class BulkAndDuplicateTests(ProductCase):
    def setUp(self):
        super().setUp()
        self.live = f.make_product(self.a, self.sub, '800', stock=5, name='Live')
        self.off = f.make_product(self.a, self.sub, '800', stock=5, name='Off', is_active=False)
        self.draft = self.product(name='Draft')
        self.theirs = f.make_product(self.b, self.sub, '800', stock=5, name='Theirs')

    def test_confirm_popup_counts_only_eligible_products(self):
        ids = f'ids={self.live.pk}&ids={self.off.pk}&ids={self.draft.pk}&ids={self.theirs.pk}'
        r = self.client.get(f'/products/bulk/?action=deactivate&{ids}', **HX)
        self.assertContains(r, 'Deactivate 1 product'); self.assertContains(r, 'no longer see them')

    def test_apply_only_changes_my_live_and_inactive_products(self):
        r = self.client.post('/products/bulk/', {'action': 'deactivate', 'ids': f'{self.live.pk},{self.draft.pk},{self.theirs.pk}'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.assertIn('1 product deactivated', json.loads(r['HX-Trigger'])['toast']['message'])
        for p, expected in ((self.live, 'inactive'), (self.draft, 'draft'), (self.theirs, 'live')):
            p.refresh_from_db(); self.assertEqual(p.status, expected, p.name)
        self.client.post('/products/bulk/', {'action': 'activate', 'ids': f'{self.live.pk},{self.off.pk}'}, **HX)
        self.live.refresh_from_db(); self.off.refresh_from_db()
        self.assertEqual((self.live.status, self.off.status), ('live', 'live'))

    def test_empty_or_invalid_selection_is_handled(self):
        self.assertContains(self.client.get('/products/bulk/?action=activate', **HX), 'Select live or inactive')
        self.assertContains(self.client.get(f'/products/bulk/?action=activate&ids={self.draft.pk}', **HX), 'Select live or inactive')
        self.assertEqual(self.client.post('/products/bulk/', {'action': 'delete', 'ids': '1'}, **HX).status_code, 422)

    def test_duplicate_redirects_to_the_new_draft(self):
        r = self.client.post(f'/products/{self.live.pk}/duplicate/', **HX)
        copy = Product.objects.get(name='Copy of Live')
        self.assertEqual((r.status_code, r['HX-Redirect']), (204, f'/products/{copy.pk}/edit/?saved=1'))
        self.assertEqual((copy.status, copy.seller_id), ('draft', self.a.pk))

    def test_cannot_duplicate_or_bulk_change_another_sellers_product(self):
        self.assertEqual(self.client.post(f'/products/{self.theirs.pk}/duplicate/', **HX).status_code, 404)
        self.assertFalse(Product.objects.filter(name='Copy of Theirs').exists())
