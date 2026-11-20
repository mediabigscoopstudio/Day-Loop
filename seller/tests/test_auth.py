from django.contrib.auth import get_user_model
from django.core.cache import cache

from sellers.models import SellerProfile

from .base import PW, SellerTestCase

GENERIC = 'Invalid credentials or not authorised'
HX = {'HTTP_HX_REQUEST': 'true'}


class SellerLoginTests(SellerTestCase):
    def test_anonymous_is_redirected_and_htmx_gets_403(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/login/'))
        self.assertEqual(self.client.get('/status/', **HX).status_code, 403)

    def test_seller_can_log_in_by_username_or_email(self):
        for ident in (self.a.user.username, self.a.user.email):
            self.client.logout()
            r = self.post_login(ident)
            self.assertEqual(r.status_code, 302, ident)
            self.assertIn('dl_seller_sid', r.cookies)
            self.assertEqual(self.client.get('/status/').status_code, 200)

    def test_customer_staff_superuser_and_inactive_are_denied_with_one_generic_error(self):
        self.a.user.is_active = False; self.a.user.save()
        for ident in ('cust', 'staffer', 'root', self.a.user.username, 'nobody-here'):
            r = self.post_login(ident)
            self.assertContains(r, GENERIC, status_code=400)
            self.assertEqual(self.client.get('/status/').status_code, 302, ident)
        self.assertContains(self.post_login(self.b.user.username, 'wrong'), GENERIC, status_code=400)

    def test_staff_who_is_also_a_seller_is_still_denied(self):
        self.b.user.is_staff = True; self.b.user.save()
        self.assertContains(self.post_login(self.b.user.username), GENERIC, status_code=400)

    def test_existing_non_seller_session_is_ended(self):
        self.login_as(self.customer)
        self.assertEqual(self.client.get('/status/').status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_throttle(self):
        for _ in range(5):
            self.post_login(self.a.user.username, 'bad')
        self.assertEqual(self.post_login(self.a.user.username, PW).status_code, 429)
        cache.clear()
        self.assertEqual(self.post_login(self.a.user.username, PW).status_code, 302)

    def test_next_is_safe(self):
        r = self.client.post('/login/', {'identifier': self.a.user.username, 'password': PW, 'next': '//evil.example'})
        self.assertEqual(r['Location'], '/')

    def test_logout_is_post_only(self):
        self.login_as(self.a.user)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        r = self.client.post('/logout/', **HX)
        self.assertEqual((r.status_code, r['HX-Redirect']), (204, '/login/'))
        self.assertEqual(self.client.get('/status/').status_code, 302)


class UnapprovedGatingTests(SellerTestCase):
    def test_home_sends_unapproved_sellers_to_the_status_page(self):
        for s in (self.pending, self.draft):
            self.login_as(s.user)
            r = self.client.get('/')
            self.assertEqual((r.status_code, r['Location']), (302, '/status/'))

    def test_status_pages_render_for_every_state(self):
        for status, text in (('draft', 'Finish your application'), ('pending', 'under review'), ('approved', 'You’re approved'),
                             ('rejected', 'not approved'), ('needs_info', 'more information')):
            s = self.make_seller(f'S {status}', status)
            self.login_as(s.user)
            self.assertContains(self.client.get('/status/'), text)


class RegistrationTests(SellerTestCase):
    DATA = dict(business_name='Fresh Roots', contact_person='Asha Rao', email='Asha@Example.test', phone='9876543210',
                password1='Str0ng-Pass-77', password2='Str0ng-Pass-77')

    def test_registration_creates_a_draft_seller_and_logs_in(self):
        r = self.client.post('/register/', self.DATA)
        self.assertEqual((r.status_code, r['Location']), (302, '/status/?welcome=1'))
        user = get_user_model().objects.get(email='asha@example.test')
        profile = user.seller_profile
        self.assertEqual((profile.status, profile.business_name, profile.onboarding_step), ('draft', 'Fresh Roots', 1))
        self.assertTrue(profile.code)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertContains(self.client.get('/status/?welcome=1'), 'Welcome, Asha')

    def test_validation_errors(self):
        for change, text in (({'email': 'cust@example.test'}, 'already exists'), ({'email': 'ASHA@x.test', 'password2': 'nope'}, 'do not match'),
                             ({'password1': '12345678', 'password2': '12345678'}, 'entirely numeric'), ({'phone': '12345'}, 'valid 10-digit')):
            before = get_user_model().objects.count()
            r = self.client.post('/register/', {**self.DATA, **change})
            self.assertContains(r, text, status_code=422)
            self.assertEqual(get_user_model().objects.count(), before)
            self.assertFalse(SellerProfile.objects.filter(business_name='Fresh Roots').exists())

    def test_registration_pages_are_public_but_everything_else_is_not(self):
        self.assertEqual(self.client.get('/register/').status_code, 200)
        self.assertEqual(self.client.get('/login/').status_code, 200)
        self.assertEqual(self.client.get('/products/').status_code, 302)
