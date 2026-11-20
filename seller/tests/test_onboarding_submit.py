import json

from catalog.models import Category
from sellers.models import SellerInfoReply, SellerStatusHistory

from .onboarding_helpers import HX, STEP1, OnboardingCase, step2_data, step2_files


class Step3Tests(OnboardingCase):
    def setUp(self):
        super().setUp()
        self.post_step(1, STEP1)
        self.post_step(2, step2_data(), step2_files())

    def test_saves_bank_categories_and_operations(self):
        r = self.post_step(3, self.bank_data(categories=[self.cat.pk, self.cat2.pk], dispatch_days='3'))
        self.assertEqual(r.status_code, 200)
        self.me.refresh_from_db()
        self.assertEqual(self.me.bank.account_holder, 'Fresh Roots Pvt Ltd')
        self.assertEqual({c.pk for c in self.me.categories.all()}, {self.cat.pk, self.cat2.pk})
        self.assertEqual((self.me.dispatch_days, self.me.onboarding_step), (3, 4))
        self.assertContains(r, 'Review')

    def test_validation(self):
        for change, text in (({'ifsc': 'BAD'}, 'valid 11-character IFSC'), ({'account_number': '12ab'}, '9 to 18 digits'),
                             ({'upi_id': 'nobank'}, 'valid UPI'), ({'categories': []}, 'required'), ({'dispatch_days': '0'}, 'greater than or equal to 1'),
                             ({'account_holder': ''}, 'required')):
            self.assertContains(self.post_step(3, self.bank_data(**change)), text, status_code=422)

    def test_only_admin_managed_active_top_level_categories_are_offered(self):
        sub = Category.objects.create(name='Protein', parent=self.cat)
        hidden = Category.objects.create(name='Hidden', is_active=False)
        for bad in (sub.pk, hidden.pk, 99999):
            self.assertContains(self.post_step(3, self.bank_data(categories=[bad])), 'valid choice', status_code=422)
        self.assertEqual(Category.objects.count(), 4)                                       # sellers created nothing

    def test_account_number_is_masked_and_blank_keeps_it(self):
        self.post_step(3, self.bank_data())
        r = self.client.get('/onboarding/?step=3', **HX)
        self.assertContains(r, '••••••••5500'); self.assertNotContains(r, '918273645500')
        self.post_step(3, self.bank_data(account_number=''))
        self.me.refresh_from_db(); self.assertEqual(self.me.bank.account_number, '918273645500')

    def test_changing_bank_details_requires_reverification(self):
        self.post_step(3, self.bank_data())
        type(self.me.bank).objects.filter(seller=self.me).update(verified=True)
        self.post_step(3, self.bank_data(account_number=''))                               # nothing changed
        self.me.refresh_from_db(); self.assertTrue(self.me.bank.verified)
        self.post_step(3, self.bank_data(account_number='999988887777'))
        self.me.refresh_from_db(); self.assertFalse(self.me.bank.verified)


class ReviewAndSubmitTests(OnboardingCase):
    def test_review_lists_missing_items_and_blocks_submission(self):
        self.post_step(1, STEP1)
        self.me.refresh_from_db()
        type(self.me).objects.filter(pk=self.me.pk).update(onboarding_step=4)
        r = self.client.get('/onboarding/?step=4', **HX)
        self.assertContains(r, 'Still missing'); self.assertContains(r, 'FSSAI number'); self.assertContains(r, 'Bank details')
        r = self.client.post('/onboarding/submit/', {'accept_commission': 'on'}, **HX)
        self.assertContains(r, 'Please complete', status_code=422)
        self.me.refresh_from_db(); self.assertEqual(self.me.status, 'draft')

    def test_agreement_is_required(self):
        self.complete_all_steps()
        r = self.client.post('/onboarding/submit/', {}, **HX)
        self.assertContains(r, 'accept the commission agreement', status_code=422)
        self.me.refresh_from_db(); self.assertEqual(self.me.status, 'draft')

    def test_submit_moves_to_pending_and_records_history(self):
        self.complete_all_steps()
        r = self.client.post('/onboarding/submit/', {'accept_commission': 'on'}, **HX)
        self.assertEqual((r.status_code, r['HX-Redirect']), (204, '/status/'))
        self.me.refresh_from_db()
        self.assertEqual(self.me.status, 'pending')
        self.assertIsNotNone(self.me.submitted_at); self.assertIsNotNone(self.me.commission_accepted_at)
        h = SellerStatusHistory.objects.get(seller=self.me)
        self.assertEqual((h.from_status, h.to_status, h.actor), ('draft', 'pending', self.me.user))
        self.assertContains(self.client.get('/status/'), 'under review')
        self.assertEqual(self.client.post('/onboarding/submit/', {'accept_commission': 'on'}, **HX).status_code, 422)  # once only

    def test_review_shows_masked_bank_number(self):
        self.complete_all_steps()
        r = self.client.get('/onboarding/?step=4', **HX)
        self.assertContains(r, '••••••••5500'); self.assertNotContains(r, '918273645500')


class NeedsInfoTests(OnboardingCase):
    def setUp(self):
        super().setUp()
        self.complete_all_steps()
        self.client.post('/onboarding/submit/', {'accept_commission': 'on'}, **HX)
        self.me.refresh_from_db()
        SellerStatusHistory.objects.create(seller=self.me, from_status='pending', to_status='needs_info', reason='Please upload a clearer FSSAI scan', actor=self.superuser)
        type(self.me).objects.filter(pk=self.me.pk).update(status='needs_info')

    def test_status_page_shows_the_admins_request(self):
        r = self.client.get('/status/')
        self.assertContains(r, 'Please upload a clearer FSSAI scan'); self.assertContains(r, 'Reply to the request')

    def test_reply_popup_and_resubmission(self):
        self.assertContains(self.client.get('/status/reply/', **HX), 'clearer FSSAI scan')
        r = self.client.post('/status/reply/', {'message': 'Uploaded a new scan.'}, **HX)
        self.assertEqual(r.status_code, 204)
        self.me.refresh_from_db(); self.assertEqual(self.me.status, 'pending')
        self.assertEqual(SellerInfoReply.objects.get(seller=self.me).message, 'Uploaded a new scan.')
        h = SellerStatusHistory.objects.filter(seller=self.me).first()
        self.assertEqual((h.from_status, h.to_status), ('needs_info', 'pending')); self.assertIn('Uploaded a new scan', h.reason)

    def test_empty_reply_and_reply_when_nothing_is_open(self):
        self.assertContains(self.client.post('/status/reply/', {'message': '  '}, **HX), 'write your reply', status_code=422)
        self.client.post('/status/reply/', {'message': 'ok'}, **HX)
        self.assertContains(self.client.post('/status/reply/', {'message': 'again'}, **HX), 'no open request', status_code=422)

    def test_wizard_is_editable_again_while_info_is_needed(self):
        self.assertContains(self.client.get('/onboarding/?step=1', **HX), 'Legal name')
        self.assertEqual(self.post_step(1, {**STEP1, 'city': 'Mumbai'}).status_code, 200)
        self.me.refresh_from_db(); self.assertEqual(self.me.city, 'Mumbai')
