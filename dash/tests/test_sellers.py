import json

from sellers.models import SellerProfile, SellerStatusHistory

from . import factories as f
from .base import DashTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


class SellerDecisionTests(DashTestCase):
    def setUp(self):
        super().setUp()
        self.seller = f.make_seller('Veda Nutrition', status='pending')
        self.login_as(self.superuser)

    def test_approve_writes_history_and_status(self):
        r = self.client.post(f'/sellers/{self.seller.pk}/approve/', **HX)
        self.assertEqual(r.status_code, 204)
        trig = json.loads(r['HX-Trigger'])
        self.assertTrue(trig['closeModal'] and trig['sellers-changed'])
        self.assertIn('Veda Nutrition approved', trig['toast']['message'])
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.status, 'approved')
        self.assertIsNotNone(self.seller.decided_at)
        h = SellerStatusHistory.objects.get(seller=self.seller)
        self.assertEqual((h.from_status, h.to_status, h.actor), ('pending', 'approved', self.superuser))

    def test_reject_requires_a_reason_and_rerenders_the_modal(self):
        r = self.client.post(f'/sellers/{self.seller.pk}/reject/', {'reason': '  '}, **HX)
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, 'A reason is required', status_code=422)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.status, 'pending')
        self.assertFalse(SellerStatusHistory.objects.exists())

    def test_reject_with_reason_is_recorded(self):
        r = self.client.post(f'/sellers/{self.seller.pk}/reject/', {'reason': 'GST number invalid'}, **HX)
        self.assertEqual(r.status_code, 204)
        h = SellerStatusHistory.objects.get()
        self.assertEqual((h.to_status, h.reason, h.actor), ('rejected', 'GST number invalid', self.superuser))

    def test_request_info_sets_needs_info(self):
        self.client.post(f'/sellers/{self.seller.pk}/request-info/', {'reason': 'Upload FSSAI'}, **HX)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.status, 'needs_info')

    def test_same_decision_twice_is_blocked(self):
        self.client.post(f'/sellers/{self.seller.pk}/approve/', **HX)
        r = self.client.post(f'/sellers/{self.seller.pk}/approve/', **HX)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(SellerStatusHistory.objects.count(), 1)

    def test_confirm_modals_render_with_warning_text(self):
        for action, word in (('approve', 'Approve'), ('reject', 'Reject'), ('request-info', 'information')):
            r = self.client.get(f'/sellers/{self.seller.pk}/{action}/', **HX)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, word)
            self.assertContains(r, 'consequence')

    def test_unknown_action_404(self):
        self.assertEqual(self.client.get(f'/sellers/{self.seller.pk}/delete/', **HX).status_code, 404)

    def test_detail_modal_shows_history(self):
        self.client.post(f'/sellers/{self.seller.pk}/approve/', **HX)
        r = self.client.get(f'/sellers/{self.seller.pk}/', **HX)
        self.assertContains(r, 'Pending → Approved')

    def test_non_superusers_cannot_decide_or_view(self):
        urls = [('get', f'/sellers/{self.seller.pk}/'), ('get', f'/sellers/{self.seller.pk}/approve/'),
                ('post', f'/sellers/{self.seller.pk}/approve/'), ('post', f'/sellers/{self.seller.pk}/reject/'),
                ('get', '/sellers/')]
        for user in (self.staff, self.customer, self.seller_user):
            self.login_as(user)
            for method, url in urls:
                r = getattr(self.client, method)(url, **HX)
                self.assertEqual(r.status_code, 403, f'{method} {url} as {user.username}')
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.status, 'pending')


class SellerListTests(DashTestCase):
    def setUp(self):
        super().setUp()
        f.make_seller('Alpha Foods', 'pending'); f.make_seller('Beta Herbs', 'approved')
        f.make_seller('Gamma Care', 'rejected'); f.make_seller('Delta Fit', 'needs_info')
        self.login_as(self.superuser)

    def names(self, qs=''):
        r = self.client.get('/sellers/' + qs)
        self.assertEqual(r.status_code, 200)
        return [s.business_name for s in r.context['page'].object_list]

    def test_tabs_filter_and_counts(self):
        self.assertEqual(len(self.names()), 4)
        self.assertEqual(self.names('?status=pending'), ['Alpha Foods'])
        self.assertEqual(self.names('?status=needs_info'), ['Delta Fit'])
        self.assertEqual(self.client.get('/sellers/').context['counts']['approved'], 1)

    def test_search_and_sort(self):
        self.assertEqual(self.names('?q=herbs'), ['Beta Herbs'])
        self.assertEqual(self.names('?sort=name&dir=asc'), ['Alpha Foods', 'Beta Herbs', 'Delta Fit', 'Gamma Care'])
        self.assertEqual(self.names('?sort=name&dir=desc')[0], 'Gamma Care')

    def test_bad_params_do_not_crash(self):
        self.assertEqual(self.client.get('/sellers/?status=zzz&sort=%27;drop&page=abc&dir=up').status_code, 200)
        self.assertEqual(self.client.get('/sellers/?page=999').status_code, 200)

    def test_empty_state(self):
        SellerProfile.objects.all().delete()
        self.assertContains(self.client.get('/sellers/'), 'No sellers yet')
