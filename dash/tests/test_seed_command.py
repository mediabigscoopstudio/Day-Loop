from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from catalog.models import Category


class SeedCommandTests(TestCase):
    def test_creates_no_users_and_skips_when_none_available(self):
        User = get_user_model()
        before = User.objects.count()
        call_command('seed_dash_demo', verbosity=0)
        self.assertEqual(User.objects.count(), before)
        self.assertTrue(Category.objects.filter(name='Personal Care', parent=None).exists())

    def test_uses_existing_users_only(self):
        User = get_user_model()
        for i in range(9):
            User.objects.create_user(f'demo{i}', f'demo{i}@example.test', 'x-Pass-12345')
        User.objects.create_superuser('boss', 'boss@example.test', 'x-Pass-12345')
        n = User.objects.count()
        call_command('seed_dash_demo', '--sellers', '3', '--orders', '30', verbosity=0)
        self.assertEqual(User.objects.count(), n)
        from orders.models import Order
        self.assertEqual(Order.objects.count(), 30)
        call_command('seed_dash_demo', '--sellers', '3', '--orders', '5', verbosity=0)   # re-run is safe
        self.assertEqual(User.objects.count(), n)
