from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from dash.tests import factories as f

HOST = 'seller.localhost:8000'
PW = 'Test-pass-12345!'


@override_settings(
    SESSION_COOKIE_NAME='dl_seller_sid',   # test-client helpers read this name
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],   # tests only: fast
)
class SellerTestCase(TestCase):
    """Users here exist only inside the temporary test database."""

    def setUp(self):
        cache.clear()
        U = get_user_model()
        self.a = self.make_seller('Alpha Foods', 'approved')
        self.b = self.make_seller('Beta Herbs', 'approved')
        self.pending = self.make_seller('Pending Co', 'pending')
        self.draft = self.make_seller('Draft Co', 'draft')
        self.customer = U.objects.create_user('cust', 'cust@example.test', PW)
        self.staff = U.objects.create_user('staffer', 'staff@example.test', PW, is_staff=True)
        self.superuser = U.objects.create_superuser('root', 'root@example.test', PW)
        self.client = Client(HTTP_HOST=HOST)

    def make_seller(self, name, status='approved'):
        s = f.make_seller(name, status)
        s.user.set_password(PW)
        s.user.email = f'{s.user.username}@example.test'
        s.user.save()
        return s

    def login_as(self, user):
        self.client.force_login(user)
        return self.client

    def post_login(self, identifier, password=PW, **extra):
        return self.client.post('/login/', {'identifier': identifier, 'password': password}, **extra)
