from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

HOST = 'dash.localhost:8000'
PW = 'Test-pass-12345!'


@override_settings(
    SESSION_COOKIE_NAME='dl_dash_sid',  # test-client helpers read this name
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],  # tests only: fast
)
class DashTestCase(TestCase):
    """Users here exist only inside the temporary test database."""

    def setUp(self):
        cache.clear()
        U = get_user_model()
        self.superuser = U.objects.create_superuser('root', 'root@example.test', PW, first_name='Aarav')
        self.staff = U.objects.create_user('staffer', 'staff@example.test', PW, is_staff=True)
        self.customer = U.objects.create_user('cust', 'cust@example.test', PW)
        self.seller_user = U.objects.create_user('sell', 'sell@example.test', PW)
        self.inactive_super = U.objects.create_superuser('gone', 'gone@example.test', PW)
        self.inactive_super.is_active = False
        self.inactive_super.save()
        self.client = Client(HTTP_HOST=HOST, enforce_csrf_checks=False)

    def login_as(self, user):
        self.client.force_login(user)
        return self.client

    def post_login(self, identifier, password=PW, **extra):
        return self.client.post('/login/', {'identifier': identifier, 'password': password}, **extra)
