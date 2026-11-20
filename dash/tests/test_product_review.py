import json

from catalog.models import Product

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class ProductReviewTests(DashTestCase):
    def setUp(self):
        super().setUp()
        sub = f.make_category('S', f.make_category('C'))
        self.p = f.make_product(f.make_seller(), sub, '500', status='pending', name='Whey')
        self.login_as(self.superuser)

    def test_pending_product_shows_review_buttons_in_the_detail_modal(self):
        r = self.client.get(f'/products/{self.p.pk}/', **HX)
        self.assertContains(r, f'/products/{self.p.pk}/review/approve/'); self.assertContains(r, f'/products/{self.p.pk}/review/reject/')

    def test_approve_makes_it_live(self):
        self.assertContains(self.client.get(f'/products/{self.p.pk}/review/approve/', **HX), 'goes live')
        r = self.client.post(f'/products/{self.p.pk}/review/approve/', **HX)
        self.assertEqual(r.status_code, 204)
        self.assertIn('approved and live', json.loads(r['HX-Trigger'])['toast']['message'])
        self.p.refresh_from_db(); self.assertEqual((self.p.status, self.p.rejection_reason), ('live', ''))

    def test_reject_requires_a_reason_and_stores_it(self):
        r = self.client.post(f'/products/{self.p.pk}/review/reject/', {'reason': ' '}, **HX)
        self.assertContains(r, 'A reason is required', status_code=422)
        self.p.refresh_from_db(); self.assertEqual(self.p.status, 'pending')
        self.assertEqual(self.client.post(f'/products/{self.p.pk}/review/reject/', {'reason': 'Blurry thumbnail'}, **HX).status_code, 204)
        self.p.refresh_from_db(); self.assertEqual((self.p.status, self.p.rejection_reason), ('rejected', 'Blurry thumbnail'))

    def test_only_pending_products_can_be_reviewed_and_actions_are_validated(self):
        Product.objects.filter(pk=self.p.pk).update(status='live')
        self.assertContains(self.client.get(f'/products/{self.p.pk}/review/approve/', **HX), 'Nothing to review')
        self.assertEqual(self.client.post(f'/products/{self.p.pk}/review/reject/', {'reason': 'x'}, **HX).status_code, 422)
        self.assertEqual(self.client.get(f'/products/{self.p.pk}/review/delete/', **HX).status_code, 404)

    def test_non_superusers_cannot_review(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for method in ('get', 'post'):
                self.assertEqual(getattr(self.client, method)(f'/products/{self.p.pk}/review/approve/', {'reason': 'x'}, **HX).status_code, 403)
        self.p.refresh_from_db(); self.assertEqual(self.p.status, 'pending')
