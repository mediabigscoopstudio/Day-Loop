from django.core.files.uploadedfile import SimpleUploadedFile

from sellers.models import SellerBank

from .base import PW
from .product_helpers import HX, ProductCase, png


class AccountBase(ProductCase):
    def setUp(self):
        super().setUp()
        SellerBank.objects.create(seller=self.a, account_holder='Alpha Foods', account_number='918273645500', ifsc='HDFC0001234',
                                  bank_name='HDFC Bank', upi_id='alpha@hdfc', verified=True)
        SellerBank.objects.create(seller=self.b, account_holder='Beta Herbs', account_number='111122223333', ifsc='ICIC0004321',
                                  bank_name='ICICI Bank', verified=True)


class AccountPageTests(AccountBase):
    def test_page_shows_my_details_with_masked_bank_and_no_one_elses(self):
        r = self.client.get('/account/')
        for text in ('Alpha Foods', '••••••••5500', 'HDFC0001234', 'Verified', 'Change password', 'Sign out'):
            self.assertContains(r, text)
        self.assertNotContains(r, '918273645500')
        for other in ('Beta Herbs', '111122223333', 'ICIC0004321'):
            self.assertNotContains(r, other)

    def test_unapproved_sellers_can_open_it_read_only(self):
        self.login_as(self.pending.user)
        r = self.client.get('/account/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '/account/profile/'); self.assertNotContains(r, '/account/bank/')
        self.assertContains(r, 'Change password')                                  # password change is always available

    def test_customers_and_anonymous_are_denied(self):
        self.login_as(self.customer)
        self.assertEqual(self.client.get('/account/').status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get('/account/', **HX).status_code, 403)


class ProfileEditTests(AccountBase):
    DATA = dict(business_name='Alpha Foods Co', contact_person='Ravi K', phone='9812345678', email='ravi@alpha.example', city='Mumbai', address='1 Marine Drive')

    def test_edit_saves_and_refreshes_the_account_region(self):
        self.assertContains(self.client.get('/account/profile/', **HX), 'Edit profile')
        r = self.client.post('/account/profile/', self.DATA, **HX)
        self.assertEqual(r.status_code, 204); self.assertIn('account-changed', r['HX-Trigger'])
        self.a.refresh_from_db(); self.assertEqual((self.a.business_name, self.a.city, self.a.phone), ('Alpha Foods Co', 'Mumbai', '9812345678'))
        self.assertContains(self.client.get('/account/'), 'Alpha Foods Co')

    def test_validation(self):
        for change, text in (({'phone': '123'}, 'valid 10-digit'), ({'business_name': ''}, 'required'), ({'email': 'nope'}, 'valid email')):
            self.assertContains(self.client.post('/account/profile/', {**self.DATA, **change}, **HX), text, status_code=422)

    def test_logo_upload_rules_and_legal_fields_are_not_editable(self):
        bad = SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>')
        self.assertContains(self.client.post('/account/profile/', {**self.DATA, 'logo': bad}, **HX), 'scripts', status_code=422)
        self.assertEqual(self.client.post('/account/profile/', {**self.DATA, 'logo': png('logo.png')}, **HX).status_code, 204)
        self.a.refresh_from_db(); self.assertTrue(self.a.logo.name.endswith('logo.png'))
        self.client.post('/account/profile/', {**self.DATA, 'legal_name': 'Hacked Ltd', 'gst_number': '29AAAAA0000A1Z5', 'status': 'rejected', 'code': 'EVIL'}, **HX)
        self.a.refresh_from_db()
        self.assertNotEqual(self.a.legal_name, 'Hacked Ltd'); self.assertEqual(self.a.status, 'approved'); self.assertNotEqual(self.a.code, 'EVIL')

    def test_unapproved_sellers_cannot_edit(self):
        self.login_as(self.pending.user)
        self.assertEqual(self.client.get('/account/profile/', **HX).status_code, 403)
        self.assertEqual(self.client.post('/account/profile/', self.DATA, **HX).status_code, 403)


class BankEditTests(AccountBase):
    def bank(self, **over):
        d = dict(account_holder='Alpha Foods', account_number='', ifsc='HDFC0001234', bank_name='HDFC Bank', upi_id='alpha@hdfc', current_password=PW)
        d.update(over)
        return d

    def test_the_current_password_is_required(self):
        r = self.client.post('/account/bank/', self.bank(account_number='555566667777', current_password='wrong'), **HX)
        self.assertContains(r, 'not correct', status_code=422)
        self.a.bank.refresh_from_db(); self.assertEqual(self.a.bank.account_number, '918273645500')

    def test_changed_details_need_reverification_and_stay_masked(self):
        r = self.client.post('/account/bank/', self.bank(account_number='555566667777'), **HX)
        self.assertEqual(r.status_code, 204); self.assertIn('re-verified', r['HX-Trigger'])
        b = SellerBank.objects.get(seller=self.a)
        self.assertEqual((b.account_number, b.verified), ('555566667777', False))
        page = self.client.get('/account/')
        self.assertContains(page, 'Pending verification'); self.assertContains(page, '••••••••7777'); self.assertNotContains(page, '555566667777')

    def test_blank_number_keeps_it_and_unchanged_details_stay_verified(self):
        self.assertEqual(self.client.post('/account/bank/', self.bank(upi_id='new@hdfc'), **HX).status_code, 204)
        b = SellerBank.objects.get(seller=self.a)
        self.assertEqual((b.account_number, b.upi_id, b.verified), ('918273645500', 'new@hdfc', True))
        self.client.post('/account/bank/', self.bank(ifsc='SBIN0001234'), **HX)
        self.assertFalse(SellerBank.objects.get(seller=self.a).verified)

    def test_validation(self):
        for change, text in (({'ifsc': 'BAD'}, 'valid 11-character IFSC'), ({'account_number': '12'}, '9 to 18 digits'), ({'upi_id': 'x'}, 'valid UPI')):
            self.assertContains(self.client.post('/account/bank/', self.bank(**change), **HX), text, status_code=422)

    def test_the_form_never_prefills_the_full_number(self):
        r = self.client.get('/account/bank/', **HX)
        self.assertContains(r, '••••••••5500'); self.assertNotContains(r, '918273645500')

    def test_another_sellers_bank_is_untouched(self):
        self.client.post('/account/bank/', self.bank(account_number='555566667777', ifsc='SBIN0009999'), **HX)
        other = SellerBank.objects.get(seller=self.b)
        self.assertEqual((other.account_number, other.ifsc, other.verified), ('111122223333', 'ICIC0004321', True))

    def test_unapproved_sellers_cannot_change_bank_details(self):
        self.login_as(self.pending.user)
        self.assertEqual(self.client.post('/account/bank/', self.bank(account_number='555566667777'), **HX).status_code, 403)
