import json
from datetime import date, timedelta

from django.utils import timezone

from catalog.models import Product, ProductVariant
from dash.tests import factories as f

from .base import SellerTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


def variant_data(**over):
    d = dict(label='1 kg Chocolate', sku='ALP-WHEY-1KG', mrp='1500', price='1299', moq='1', stock='40', low_stock_threshold='10',
             batch_number='B-2411', manufactured_on=date.today().isoformat(), expires_on=(date.today() + timedelta(days=365)).isoformat(),
             hsn_code='210690', gst_rate='18', country_of_origin='India', dispatch_days='2',
             length_cm='30', width_cm='20', height_cm='10', weight_g='1100')
    d.update(over)
    return d


class VariantBase(SellerTestCase):
    def setUp(self):
        super().setUp()
        self.sub = f.make_category('Protein', f.make_category('Wellness'))
        self.sub.default_gst_rate = 12; self.sub.save()
        self.product = Product.objects.create(seller=self.a, subcategory=self.sub, name='Whey Protein', status='draft')
        self.login_as(self.a.user)
        self.url = f'/products/{self.product.pk}/variants/new/'

    def add(self, **over):
        return self.client.post(self.url, variant_data(**over), **HX)


class VariantFormTests(VariantBase):
    def test_modal_is_a_bottom_sheet_with_category_default_gst_and_suggested_sku(self):
        r = self.client.get(self.url, **HX)
        self.assertContains(r, 'class="modal lg sheet"')
        self.assertContains(r, 'ALPH-WHEY-PRO-STD')                       # suggested SKU: seller code + product + label
        self.assertContains(r, '<option value="12" selected>')            # GST defaults to the category's rate
        self.assertContains(r, 'Volumetric weight'); self.assertContains(r, 'data-weights')

    def test_valid_variant_is_saved_for_this_seller_and_product(self):
        r = self.add()
        self.assertEqual(r.status_code, 204)
        trig = json.loads(r['HX-Trigger'])
        self.assertTrue(trig['variants-changed'] and trig['closeModal'])
        v = ProductVariant.objects.get()
        self.assertEqual((v.product_id, v.seller_id, v.sku, v.price), (self.product.pk, self.a.pk, 'ALP-WHEY-1KG', 1299))
        self.assertTrue(v.is_complete)
        self.assertEqual(str(v.volumetric_kg), '1.200'); self.assertEqual(str(v.chargeable_kg), '1.200')

    def test_validation_rules(self):
        today = date.today()
        cases = [({'price': '1600'}, 'cannot be higher than MRP'),
                 ({'manufactured_on': today.isoformat(), 'expires_on': today.isoformat()}, 'after the manufacture date'),
                 ({'manufactured_on': today.isoformat(), 'expires_on': (today - timedelta(days=3)).isoformat()}, 'after the manufacture date'),
                 ({'gst_rate': '14'}, 'valid choice'), ({'hsn_code': '12'}, '4, 6 or 8 digits'), ({'moq': '0'}, 'at least 1'),
                 ({'label': ''}, 'required'), ({'sku': ''}, 'required'), ({'mrp': '-5', 'price': '-6'}, 'greater than zero'), ({'price': '0'}, 'greater than zero'),
                 ({'height_cm': ''}, 'all three dimensions')]
        for change, text in cases:
            r = self.add(**change)
            self.assertContains(r, text, status_code=422)
        self.assertEqual(ProductVariant.objects.count(), 0)

    def test_sku_must_be_unique_for_the_seller_only(self):
        self.assertEqual(self.add().status_code, 204)
        self.assertContains(self.add(label='2 kg'), 'already use this SKU', status_code=422)
        other = Product.objects.create(seller=self.b, subcategory=self.sub, name='Other', status='draft')
        self.login_as(self.b.user)
        r = self.client.post(f'/products/{other.pk}/variants/new/', variant_data(), **HX)
        self.assertEqual(r.status_code, 204)                                 # same SKU, different seller: fine

    def test_edit_keeps_its_own_sku_and_updates(self):
        self.add()
        v = ProductVariant.objects.get()
        r = self.client.post(f'/products/{self.product.pk}/variants/{v.pk}/', variant_data(price='1199', stock='5'), **HX)
        self.assertEqual(r.status_code, 204)
        v.refresh_from_db(); self.assertEqual((int(v.price), v.stock), (1199, 5))
        self.assertContains(self.client.get(f'/products/{self.product.pk}/variants/{v.pk}/', **HX), '1.200 kg')

    def test_dimensions_all_blank_is_allowed_but_variant_stays_incomplete(self):
        r = self.add(length_cm='', width_cm='', height_cm='', weight_g='')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ProductVariant.objects.get().is_complete)


class BulkSizesAndDeleteTests(VariantBase):
    def test_add_several_sizes_creates_placeholder_rows(self):
        r = self.client.post(f'/products/{self.product.pk}/variants/sizes/', {'sizes': '250 g\n500 g, 1 kg\n500 g'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.assertIn('3 variants added', json.loads(r['HX-Trigger'])['toast']['message'])
        rows = ProductVariant.objects.filter(product=self.product)
        self.assertEqual(sorted(v.label for v in rows), ['1 kg', '250 g', '500 g'])
        self.assertTrue(all(not v.is_complete and v.gst_rate == 12 for v in rows))      # category default GST; still to be filled in
        self.assertEqual(len({v.sku for v in rows}), 3)
        r2 = self.client.post(f'/products/{self.product.pk}/variants/sizes/', {'sizes': '250 g, 2 kg'}, **HX)
        self.assertIn('1 variant added', json.loads(r2['HX-Trigger'])['toast']['message'])    # duplicates skipped

    def test_sizes_validation(self):
        for sizes, text in (('', 'required'), (','.join(f's{i}' for i in range(13)), 'up to 12')):
            self.assertContains(self.client.post(f'/products/{self.product.pk}/variants/sizes/', {'sizes': sizes}, **HX), text, status_code=422)

    def test_delete_confirm_then_delete(self):
        self.add(); v = ProductVariant.objects.get()
        self.assertContains(self.client.get(f'/products/{self.product.pk}/variants/{v.pk}/delete/', **HX), 'cannot be undone')
        self.assertEqual(self.client.post(f'/products/{self.product.pk}/variants/{v.pk}/delete/', **HX).status_code, 204)
        self.assertFalse(ProductVariant.objects.exists())

    def test_ordered_variants_cannot_be_deleted(self):
        p = f.make_product(self.a, self.sub, '500', stock=5)
        f.make_order(f.make_user('c'), timezone.now(), [(p, 1)])
        v = p.variant
        self.assertContains(self.client.get(f'/products/{p.pk}/variants/{v.pk}/delete/', **HX), 'has been ordered')
        self.assertContains(self.client.post(f'/products/{p.pk}/variants/{v.pk}/delete/', **HX), 'has been ordered', status_code=422)
        self.assertTrue(ProductVariant.objects.filter(pk=v.pk).exists())

    def test_list_partial_shows_what_each_variant_still_needs(self):
        self.client.post(f'/products/{self.product.pk}/variants/sizes/', {'sizes': '250 g'}, **HX)
        r = self.client.get(f'/products/{self.product.pk}/variants/', **HX)
        self.assertContains(r, 'Needs: price, stock, expiry date, package dimensions and weight')


class VariantAccessTests(VariantBase):
    def setUp(self):
        super().setUp()
        self.add(); self.variant = ProductVariant.objects.get()

    def test_other_sellers_products_and_variants_are_404(self):
        self.login_as(self.b.user)
        pk, vid = self.product.pk, self.variant.pk
        for method, url in (('get', f'/products/{pk}/variants/'), ('get', f'/products/{pk}/variants/new/'), ('post', f'/products/{pk}/variants/new/'),
                            ('get', f'/products/{pk}/variants/{vid}/'), ('post', f'/products/{pk}/variants/{vid}/'),
                            ('get', f'/products/{pk}/variants/{vid}/delete/'), ('post', f'/products/{pk}/variants/{vid}/delete/'),
                            ('get', f'/products/{pk}/variants/sizes/'), ('post', f'/products/{pk}/variants/sizes/')):
            r = getattr(self.client, method)(url, variant_data(sku='B-SKU'), **HX)
            self.assertEqual(r.status_code, 404, f'{method} {url}')
        self.variant.refresh_from_db()
        self.assertEqual((self.variant.sku, self.variant.seller_id), ('ALP-WHEY-1KG', self.a.pk))
        self.assertEqual(ProductVariant.objects.count(), 1)

    def test_a_variant_id_from_another_product_does_not_resolve(self):
        other = Product.objects.create(seller=self.a, subcategory=self.sub, name='Other product', status='draft')
        r = self.client.get(f'/products/{other.pk}/variants/{self.variant.pk}/', **HX)
        self.assertEqual(r.status_code, 404)

    def test_products_under_review_are_locked(self):
        Product.objects.filter(pk=self.product.pk).update(status='pending')
        for method, url in (('get', self.url), ('post', self.url), ('get', f'/products/{self.product.pk}/variants/{self.variant.pk}/'),
                            ('post', f'/products/{self.product.pk}/variants/{self.variant.pk}/delete/')):
            self.assertEqual(getattr(self.client, method)(url, variant_data(sku='NEW'), **HX).status_code, 403, f'{method} {url}')

    def test_unapproved_and_non_sellers_are_denied(self):
        for user in (self.pending.user, self.draft.user):
            self.login_as(user)
            self.assertEqual(self.client.get(self.url, **HX).status_code, 403)
        self.login_as(self.customer)
        self.assertEqual(self.client.get(self.url, **HX).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url, **HX).status_code, 403)
