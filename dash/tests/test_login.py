from django.core.cache import cache

from .base import DashTestCase, PW

GENERIC = 'Invalid credentials or not authorised'


class LoginRulesTests(DashTestCase):
    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/login/'))

    def test_anonymous_htmx_gets_403_not_redirect(self):
        r = self.client.get('/logout/confirm/', HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 403)

    def test_superuser_can_log_in_by_username_and_email(self):
        for ident in ('root', 'root@example.test', 'ROOT'):
            self.client.logout()
            r = self.post_login(ident)
            self.assertEqual(r.status_code, 302, ident)
            self.assertEqual(r['Location'], '/')
            self.assertEqual(self.client.get('/').status_code, 200)

    def test_non_superusers_are_denied_with_one_generic_message(self):
        for ident in ('staffer', 'cust', 'sell', 'gone'):
            r = self.post_login(ident)
            self.assertEqual(r.status_code, 400, ident)
            self.assertContains(r, GENERIC, status_code=400)
            self.assertEqual(self.client.get('/').status_code, 302, ident)

    def test_wrong_password_and_unknown_user_show_the_same_message(self):
        a = self.post_login('root', 'wrong')
        b = self.post_login('nobody-here', 'wrong')
        self.assertContains(a, GENERIC, status_code=400)
        self.assertContains(b, GENERIC, status_code=400)

    def test_existing_session_of_non_superuser_is_blocked_and_ended(self):
        self.login_as(self.staff)
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_throttle_after_five_failures_blocks_even_correct_password(self):
        for _ in range(5):
            self.post_login('root', 'bad')
        r = self.post_login('root', PW)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.client.get('/').status_code, 302)
        cache.clear()
        self.assertEqual(self.post_login('root', PW).status_code, 302)

    def test_next_redirect_is_safe(self):
        r = self.client.post('/login/', {'identifier': 'root', 'password': PW, 'next': '//evil.example/x'})
        self.assertEqual(r['Location'], '/')
        self.client.logout()
        r = self.client.post('/login/', {'identifier': 'root', 'password': PW, 'next': '/sellers/'})
        self.assertEqual(r['Location'], '/sellers/')

    def test_logout_is_post_only_and_ends_session(self):
        self.login_as(self.superuser)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        r = self.client.post('/logout/', HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], '/login/')
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_django_admin_follows_the_same_rule(self):
        for u in (self.staff, self.customer):
            self.login_as(u)
            r = self.client.get('/admin/')
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r['Location'].startswith('/login/'))
        self.login_as(self.superuser)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_dash_session_cookie_is_isolated(self):
        r = self.post_login('root')
        self.assertIn('dl_dash_sid', r.cookies)
        self.assertNotIn('sessionid', r.cookies)
