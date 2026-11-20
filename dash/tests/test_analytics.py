from django.utils import timezone

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class AnalyticsTests(DashTestCase):
    def test_renders_empty(self):
        self.login_as(self.superuser)
        r = self.client.get('/analytics/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No cohorts yet'); self.assertContains(r, 'No product sales')

    def test_renders_with_data_and_ranges(self):
        sub = f.make_category('S', f.make_category('C')); p = f.make_product(f.make_seller('Prana'), sub, '900', name='Whey')
        u = f.make_user('u')
        f.make_order(u, timezone.now(), [(p, 2)]); f.make_order(u, timezone.now(), [(p, 1)])
        self.login_as(self.superuser)
        for rng in ('7d', '30d', '90d', '12m', 'today'):
            self.assertEqual(self.client.get(f'/analytics/?range={rng}').status_code, 200, rng)
        r = self.client.get('/analytics/?range=30d')
        self.assertContains(r, 'Whey'); self.assertContains(r, 'Prana')
        nv = self.client.get('/api/new-vs-repeat/?range=30d').json()
        self.assertEqual((sum(nv['new']), sum(nv['repeat'])), (1, 1))
        sub_rev = self.client.get('/api/category-revenue/?range=30d&level=subcategory').json()
        self.assertEqual(sub_rev['rows'][0]['name'], 'S')

    def test_forbidden_for_non_superusers(self):
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            self.assertEqual(self.client.get('/analytics/', **HX).status_code, 403)
            self.assertEqual(self.client.get('/api/new-vs-repeat/').status_code, 403)
