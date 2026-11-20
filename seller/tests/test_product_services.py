from datetime import date, timedelta
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from catalog.models import Product, ProductHighlight, ProductVariant
from dash.tests import factories as f
from seller.richtext import clean_html, to_text
from seller.services import products as svc


class RichTextTests(SimpleTestCase):
    def test_dangerous_html_is_removed(self):
        dirty = '<p onclick="x()">Hi <script>alert(1)</script><a href="javascript:x">link</a><img src=x onerror=y></p><style>b{}</style>'
        out = clean_html(dirty)
        for bad in ('script', 'onclick', 'href', 'onerror', '<img', 'style', 'javascript', 'alert'):
            self.assertNotIn(bad, out)
        self.assertIn('Hi', out); self.assertIn('link', out)

    def test_allowed_formatting_is_kept_and_normalised(self):
        self.assertEqual(clean_html('<strong>bold</strong> <em>it</em><ul><li>a</li><li>b</li></ul>'),
                         '<b>bold</b> <i>it</i><ul><li>a</li><li>b</li></ul>')

    def test_unclosed_tags_are_closed_and_text_is_escaped(self):
        self.assertEqual(clean_html('<b>open <i>x'), '<b>open <i>x</i></b>')
        self.assertEqual(clean_html('1 < 2 & 3'), '1 &lt; 2 &amp; 3')

    def test_length_cap_and_text_extraction(self):
        self.assertLessEqual(len(clean_html('a' * 50000)), 8000)
        self.assertEqual(to_text('<p>Hello <b>big</b></p><ul><li>x</li></ul>'), 'Hello big x')


class ProductServiceBase(TestCase):
    def setUp(self):
        self.sub = f.make_category('Protein', f.make_category('Wellness'))
        self.s1, self.s2 = f.make_seller('Alpha'), f.make_seller('Beta')

    def draft(self, seller=None, **kw):
        p = f.make_product(seller or self.s1, self.sub, '500', stock=5, status='draft', **kw)
        Product.objects.filter(pk=p.pk).update(thumbnail='products/thumbs/t.png')
        p.refresh_from_db()
        return p


class ReviewGateTests(ProductServiceBase):
    def test_complete_product_can_be_submitted(self):
        p = self.draft()
        sections, done, blockers = svc.readiness(p)
        self.assertEqual(blockers, [])
        out = svc.submit_for_review(self.s1, p.pk)
        self.assertEqual(out.status, 'pending'); self.assertIsNotNone(out.submitted_at)
        self.assertTrue(out.meta_title)                         # SEO auto-filled on submit

    def test_cannot_submit_without_a_variant(self):
        p = self.draft(); p.variants.all().delete()
        with self.assertRaisesMessage(svc.ProductError, 'Add at least one variant'):
            svc.submit_for_review(self.s1, p.pk)
        p.refresh_from_db(); self.assertEqual(p.status, 'draft')

    def test_variant_needs_price_stock_expiry_and_full_dimensions(self):
        for change, word in (({'stock': 0}, 'stock'), ({'expires_on': None}, 'expiry date'), ({'length_cm': None}, 'dimensions'),
                             ({'weight_g': None}, 'dimensions'), ({'height_cm': 0}, 'dimensions')):
            p = self.draft()
            ProductVariant.objects.filter(product=p).update(**change)
            with self.assertRaises(svc.ProductError) as ctx:
                svc.submit_for_review(self.s1, p.pk)
            self.assertIn(word, str(ctx.exception), change)
            p.refresh_from_db(); self.assertEqual(p.status, 'draft')

    def test_needs_a_thumbnail_and_an_approved_seller(self):
        p = self.draft(); Product.objects.filter(pk=p.pk).update(thumbnail='')
        with self.assertRaisesMessage(svc.ProductError, 'thumbnail'):
            svc.submit_for_review(self.s1, p.pk)
        q = self.draft(); self.s1.status = 'pending'; self.s1.save()
        with self.assertRaisesMessage(svc.ProductError, 'not approved'):
            svc.submit_for_review(self.s1, q.pk)

    def test_only_drafts_and_rejected_products_can_be_submitted(self):
        for status in ('pending', 'live', 'inactive'):
            p = self.draft(); Product.objects.filter(pk=p.pk).update(status=status)
            with self.assertRaises(svc.ProductError):
                svc.submit_for_review(self.s1, p.pk)
        r = self.draft(); Product.objects.filter(pk=r.pk).update(status='rejected', rejection_reason='Blurry image')
        out = svc.submit_for_review(self.s1, r.pk)
        self.assertEqual((out.status, out.rejection_reason), ('pending', ''))

    def test_checklist_counts_sections(self):
        p = self.draft()
        sections, done, _ = svc.readiness(p)
        self.assertEqual([s['key'] for s in sections], ['basics', 'variants', 'media', 'seo', 'aplus'])
        self.assertEqual(done, 2)                                # basics + variants; media/seo/aplus still empty
        for i in range(3):
            ProductHighlight.objects.create(product=p, text=f'h{i}', sort_order=i)
        p.images.create(image='products/1/a.png')
        p.meta_title, p.meta_description = 'T', 'D'
        self.assertEqual(svc.readiness(p)[1], 4)

    def test_another_sellers_product_is_not_found(self):
        p = self.draft()
        for call in (lambda: svc.submit_for_review(self.s2, p.pk), lambda: svc.get_product(self.s2, p.pk),
                     lambda: svc.duplicate(self.s2, p.pk)):
            with self.assertRaises(Product.DoesNotExist):
                call()


class VariantRuleTests(ProductServiceBase):
    def variant(self, p, **kw):
        v = ProductVariant(product=p, seller=p.seller, label='L', sku=kw.pop('sku', 'SKU-X'), mrp=D('100'), price=D('90'), **kw)
        return v

    def test_expiry_must_be_after_manufacture(self):
        p = self.draft()
        today = date.today()
        for mfg, exp in ((today, today), (today, today - timedelta(days=1))):
            with self.assertRaises(ValidationError) as ctx:
                self.variant(p, manufactured_on=mfg, expires_on=exp).full_clean(exclude=['product', 'seller'])
            self.assertIn('expires_on', ctx.exception.message_dict)
        self.variant(p, manufactured_on=today, expires_on=today + timedelta(days=1)).full_clean(exclude=['product', 'seller'])

    def test_price_cannot_exceed_mrp_in_validation_or_database(self):
        p = self.draft()
        v = self.variant(p); v.price = D('120')
        with self.assertRaises(ValidationError) as ctx:
            v.full_clean(exclude=['product', 'seller'])
        self.assertIn('price', ctx.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            v.save()

    def test_gst_rate_limited_to_allowed_slabs(self):
        p = self.draft(); v = self.variant(p); v.gst_rate = 14
        with self.assertRaises(ValidationError):
            v.full_clean(exclude=['product', 'seller'])

    def test_sku_is_unique_per_seller_but_reusable_across_sellers(self):
        p1, p2 = self.draft(self.s1), self.draft(self.s2)
        ProductVariant.objects.filter(product=p1).update(sku='SAME')
        ProductVariant.objects.filter(product=p2).update(sku='SAME')            # different seller: fine
        other = self.variant(p1, sku='SAME')
        with self.assertRaises(IntegrityError), transaction.atomic():
            other.save()

    def test_suggested_skus_are_unique(self):
        p = self.draft()
        a = svc.suggest_sku(self.s1, p, '1 kg Chocolate')
        ProductVariant.objects.filter(product=p).update(sku=a)
        b = svc.suggest_sku(self.s1, p, '1 kg Chocolate')
        self.assertNotEqual(a, b); self.assertLessEqual(len(b), 40)
        self.assertTrue(a.startswith(self.s1.code))


class DuplicateAndBulkTests(ProductServiceBase):
    def test_duplicate_makes_a_draft_with_fresh_skus_and_zero_stock(self):
        p = self.draft(name='Whey')
        ProductHighlight.objects.create(product=p, text='Great', sort_order=0)
        c = svc.duplicate(self.s1, p.pk)
        self.assertEqual((c.status, c.name, c.seller_id), ('draft', 'Copy of Whey', self.s1.pk))
        self.assertNotEqual(c.slug, p.slug)
        v, ov = c.variants.get(), p.variants.get()
        self.assertEqual((v.stock, v.price, v.label), (0, ov.price, ov.label))
        self.assertNotEqual(v.sku, ov.sku)
        self.assertEqual(c.highlights.get().text, 'Great')

    def test_bulk_toggle_only_touches_live_and_inactive(self):
        live = f.make_product(self.s1, self.sub); off = f.make_product(self.s1, self.sub, is_active=False)
        draft, pend = self.draft(), self.draft(); Product.objects.filter(pk=pend.pk).update(status='pending')
        other = f.make_product(self.s2, self.sub)
        ids = [live.pk, off.pk, draft.pk, pend.pk, other.pk]
        self.assertEqual(svc.bulk_set_active(self.s1, ids, activate=False), 1)
        self.assertEqual(svc.bulk_set_active(self.s1, ids, activate=True), 2)
        statuses = dict(Product.objects.filter(pk__in=ids).values_list('pk', 'status'))
        self.assertEqual(statuses[live.pk], 'live'); self.assertEqual(statuses[off.pk], 'live')
        self.assertEqual((statuses[draft.pk], statuses[pend.pk]), ('draft', 'pending'))
        self.assertEqual(statuses[other.pk], 'live')              # untouched: belongs to another seller
