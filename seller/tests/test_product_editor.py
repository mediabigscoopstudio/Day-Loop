from django.core.files.uploadedfile import SimpleUploadedFile

from catalog.models import Category, Product
from dash.tests import factories as f

from .product_helpers import HX, ProductCase, png


class EditorCreateTests(ProductCase):
    def test_new_page_has_sections_jump_links_and_disabled_submit(self):
        r = self.client.get('/products/new/')
        for text in ('Add new product', 'sec-basics', 'sec-variants', 'sec-media', 'sec-seo', 'sec-aplus', 'Jump to', 'Quick tips', 'Save the basics first'):
            self.assertContains(r, text)
        self.assertContains(r, 'class="action-bar"')                       # sticky bar for phones
        self.assertNotContains(r, 'sections done')                         # checklist only once the product exists

    def test_save_draft_creates_my_product_with_slug_and_seo(self):
        r = self.client.post('/products/new/', self.basics())
        p = Product.objects.get(name='Whey Protein')
        self.assertEqual((r.status_code, r['Location']), (302, f'/products/{p.pk}/edit/?saved=1'))
        self.assertEqual((p.seller_id, p.status, p.slug, p.subcategory_id), (self.a.pk, 'draft', 'whey-protein', self.sub.pk))
        self.assertEqual(p.meta_title, 'Whey Protein'); self.assertEqual(p.meta_description, 'Clean protein')   # auto-filled
        self.assertContains(self.client.get(r['Location']), 'Draft saved')

    def test_slugs_stay_unique(self):
        self.client.post('/products/new/', self.basics()); self.client.post('/products/new/', self.basics())
        self.assertEqual(sorted(Product.objects.values_list('slug', flat=True)), ['whey-protein', 'whey-protein-2'])

    def test_description_html_is_sanitised(self):
        self.client.post('/products/new/', self.basics(description='<p onclick="x()">Hi <script>alert(1)</script><a href="http://e.x">l</a></p><b>ok</b>'))
        d = Product.objects.get().description
        for bad in ('script', 'onclick', 'href', 'alert'):
            self.assertNotIn(bad, d)
        self.assertIn('<b>ok</b>', d)

    def test_validation_errors_are_shown_and_nothing_is_saved(self):
        for change, text in (({'name': '  '}, 'required'), ({'subcategory': ''}, 'required'), ({'subcategory': self.cat.pk}, 'valid choice'),
                             ({'category': self.cat2.pk}, 'does not belong'), ({'short_description': 'x' * 300}, 'at most 220')):
            r = self.client.post('/products/new/', self.basics(**change))
            self.assertEqual(r.status_code, 422, change)
            self.assertContains(r, text, status_code=422)
        self.assertEqual(Product.objects.count(), 0)

    def test_only_admin_managed_active_subcategories_can_be_chosen(self):
        hidden = Category.objects.create(name='Hidden', parent=self.cat, is_active=False)
        self.assertContains(self.client.post('/products/new/', self.basics(subcategory=hidden.pk)), 'valid choice', status_code=422)

    def test_sellers_cannot_create_categories_through_the_product_form(self):
        before = Category.objects.count()
        self.client.post('/products/new/', self.basics(new_category='Sneaky', new_subcategory='Also sneaky', **{'category_name': 'x'}))
        self.assertEqual(Category.objects.count(), before)

    def test_mass_assignment_cannot_change_owner_or_status(self):
        r = self.client.post('/products/new/', self.basics(seller=self.b.pk, status='live', slug='hacked', rejection_reason='x'))
        p = Product.objects.get()
        self.assertEqual((p.seller_id, p.status, p.slug), (self.a.pk, 'draft', 'whey-protein'))

    def test_highlights_saved_replaced_and_limited(self):
        r = self.client.post('/products/new/', {**self.basics(), 'highlights': ['One', 'Two', 'Three']})
        p = Product.objects.get()
        self.assertEqual([h.text for h in p.highlights.all()], ['One', 'Two', 'Three'])
        self.client.post(f'/products/{p.pk}/edit/', {**self.basics(), 'highlights': ['Only']})
        self.assertEqual([h.text for h in p.highlights.all()], ['Only'])
        bad = self.client.post(f'/products/{p.pk}/edit/', {**self.basics(), 'highlights': [f'h{i}' for i in range(7)]})
        self.assertContains(bad, 'up to 6 highlights', status_code=422)
        self.assertEqual(p.highlights.count(), 1)                          # failed save changed nothing
        self.assertContains(bad, 'id="sec-media" open', status_code=422)                    # the card with the error opens

    def test_thumbnail_is_validated_by_content(self):
        r = self.client.post('/products/new/', {**self.basics(), 'thumbnail': SimpleUploadedFile('t.png', b'not an image')})
        self.assertContains(r, 'Upload a JPG, PNG or WebP', status_code=422)
        r = self.client.post('/products/new/', {**self.basics(), 'thumbnail': png('thumb.png')})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Product.objects.get().thumbnail.name.endswith('thumb.png'))


class EditorSubmitTests(ProductCase):
    def test_submit_without_a_complete_variant_is_blocked_and_opens_the_variants_card(self):
        p = self.product()
        r = self.client.post(f'/products/{p.pk}/edit/', self.basics(action='submit'))
        self.assertContains(r, 'Add at least one variant', status_code=422)
        self.assertContains(r, 'id="sec-variants" open', status_code=422)
        p.refresh_from_db(); self.assertEqual(p.status, 'draft')

    def test_submit_complete_product_goes_to_pending_review(self):
        p = self.ready_product()
        r = self.client.post(f'/products/{p.pk}/edit/', self.basics(action='submit', name='Whey Ready'))
        self.assertEqual((r.status_code, r['Location']), (302, '/products/?submitted=1'))
        p.refresh_from_db(); self.assertEqual((p.status, p.name), ('pending', 'Whey Ready'))
        self.assertIsNotNone(p.submitted_at)

    def test_checklist_shows_progress_on_the_edit_page(self):
        p = self.ready_product()
        r = self.client.get(f'/products/{p.pk}/edit/')
        self.assertContains(r, '2 of 5 sections done')

    def test_pending_products_cannot_be_edited(self):
        p = self.ready_product(); Product.objects.filter(pk=p.pk).update(status='pending')
        for method in ('get', 'post'):
            r = getattr(self.client, method)(f'/products/{p.pk}/edit/', self.basics(name='Changed'))
            self.assertEqual((r.status_code, r['Location']), (302, '/products/?notice=review'))
        p.refresh_from_db(); self.assertNotEqual(p.name, 'Changed')

    def test_editing_a_live_product_sends_it_back_for_review(self):
        p = f.make_product(self.a, self.sub, '500', stock=5, name='Live Whey')
        self.assertContains(self.client.get(f'/products/{p.pk}/edit/'), 'sends it back for review')
        r = self.client.post(f'/products/{p.pk}/edit/', self.basics(name='Live Whey v2'))
        self.assertEqual(r['Location'], '/products/?resubmitted=1')
        p.refresh_from_db(); self.assertEqual((p.status, p.name), ('pending', 'Live Whey v2'))

    def test_rejected_product_shows_the_reason_and_can_be_resubmitted(self):
        p = self.ready_product(); Product.objects.filter(pk=p.pk).update(status='rejected', rejection_reason='Image is blurry')
        self.assertContains(self.client.get(f'/products/{p.pk}/edit/'), 'Image is blurry')
        self.client.post(f'/products/{p.pk}/edit/', self.basics(action='submit'))
        p.refresh_from_db(); self.assertEqual((p.status, p.rejection_reason), ('pending', ''))


class EditorAccessTests(ProductCase):
    def test_other_sellers_product_is_404_everywhere(self):
        theirs = self.product(seller=self.b, name='Beta Secret')
        for method, url in (('get', f'/products/{theirs.pk}/edit/'), ('post', f'/products/{theirs.pk}/edit/')):
            self.assertEqual(getattr(self.client, method)(url, self.basics(name='Stolen')).status_code, 404, url)
        theirs.refresh_from_db(); self.assertEqual(theirs.name, 'Beta Secret')

    def test_category_endpoints_do_not_exist_for_sellers_and_options_are_read_only(self):
        for path in ('/categories/', '/categories/new/', '/products/categories/new/', '/products/categories/', '/subcategories/new/'):
            for method in ('get', 'post'):
                self.assertEqual(getattr(self.client, method)(path, {'name': 'X'}).status_code, 404, f'{method} {path}')
        r = self.client.get(f'/products/subcategory-options/?category={self.cat.pk}', **HX)
        self.assertContains(r, 'Protein')
        self.assertEqual(self.client.post('/products/subcategory-options/', {'name': 'X'}, **HX).status_code, 405)
        self.assertEqual(Category.objects.count(), 4)

    def test_unapproved_sellers_cannot_add_products(self):
        for s in (self.pending, self.draft):
            self.login_as(s.user)
            r = self.client.get('/products/new/'); self.assertEqual((r.status_code, r['Location']), (302, '/status/'))
            self.assertEqual(self.client.post('/products/new/', self.basics()).status_code, 302)
        self.assertEqual(Product.objects.count(), 0)
        self.client.logout()
        self.assertEqual(self.client.post('/products/new/', self.basics()).status_code, 302)    # anonymous: to login
        self.assertEqual(Product.objects.count(), 0)
