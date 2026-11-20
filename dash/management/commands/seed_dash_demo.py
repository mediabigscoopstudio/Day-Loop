"""
Optional demo data for the admin dashboards. NOT run automatically.

This command never creates users. Categories are always seeded. Sellers,
products and orders are attached to EXISTING non-superuser accounts only:
  - users without a seller profile become demo sellers (first --sellers of them)
  - the remaining non-superusers become demo customers
If there are not enough users, those parts are skipped with a clear message.

    python manage.py seed_dash_demo [--sellers 6] [--orders 120] [--days 120]
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import Category, Product
from orders.models import Order, OrderItem
from sellers.models import SellerProfile

TAXONOMY = {
    'Wellness Supplements': ['Protein', 'Vitamins', 'Immunity', 'Herbal'],
    'Personal Care': ['Skin Care', 'Hair Care'],
    'Healthy Food & Beverages': ['Superfoods', 'Teas'],
    'Fitness & Recovery': ['Pre-workout', 'Recovery'],
    'Home & Wellness': ['Aromatherapy'],
}
PRODUCTS = ['Whey Isolate', 'Ashwagandha', 'Vitamin C', 'Multivitamin', 'Aloe Gel', 'Hair Oil', 'Green Tea', 'Chia Seeds', 'Creatine', 'BCAA', 'Diffuser Oil']
CITIES = ['Mumbai', 'Pune', 'Bengaluru', 'Delhi', 'Jaipur', 'Hyderabad']
STATUSES = ['delivered'] * 6 + ['shipped', 'processing', 'pending', 'cancelled']


class Command(BaseCommand):
    help = 'Seed sample categories, sellers, products and orders for demos. Creates no users.'

    def add_arguments(self, parser):
        parser.add_argument('--sellers', type=int, default=6)
        parser.add_argument('--orders', type=int, default=120)
        parser.add_argument('--days', type=int, default=120)

    def handle(self, *args, **opts):
        rnd = random.Random(42)
        subs = self._categories()
        User = get_user_model()
        free = list(User.objects.filter(is_superuser=False, seller_profile__isnull=True).order_by('pk'))
        seller_users = free[:opts['sellers']]
        customers = free[opts['sellers']:] or []
        if not seller_users:
            self.stdout.write(self.style.WARNING(
                'No spare non-superuser accounts, so sellers, products and orders were skipped. '
                'Create some users yourself (this command never does) and run it again.'))
            return

        sellers = []
        top_names = list(TAXONOMY)
        for i, u in enumerate(seller_users):
            sp, _ = SellerProfile.objects.get_or_create(user=u, defaults=dict(
                business_name=f'{u.get_username().title()} Wellness', city=rnd.choice(CITIES),
                category=Category.objects.get(name=top_names[i % len(top_names)], parent=None),
                gst_number=f'27AAAAA{1000 + i}A1Z5', fssai_number=f'1000{i:010d}',
                status=rnd.choice(['approved'] * 4 + ['pending', 'needs_info']),
            ))
            sellers.append(sp)
        approved = [s for s in sellers if s.status == 'approved'] or sellers

        products = []
        for s in approved:
            for name in rnd.sample(PRODUCTS, 4):
                p, _ = Product.objects.get_or_create(seller=s, name=name, defaults=dict(
                    subcategory=rnd.choice(subs), brand=s.business_name.split()[0], price=Decimal(rnd.choice([299, 499, 799, 1299, 1899])),
                    stock=rnd.choice([0, 4, 25, 80, 200]), sku=f'{s.pk}-{name[:3].upper()}'))
                products.append(p)

        if not customers:
            self.stdout.write(self.style.WARNING('No spare accounts left to act as customers, so orders were skipped.'))
        else:
            now = timezone.now()
            made = 0
            for _ in range(opts['orders']):
                c = rnd.choice(customers)
                when = now - timedelta(days=rnd.randint(0, opts['days']), hours=rnd.randint(0, 23))
                status = rnd.choice(STATUSES)
                o = Order.objects.create(
                    customer=c, placed_at=when, status=status, payment_method=rnd.choice(['UPI', 'Card', 'COD']),
                    payment_status='failed' if status == 'cancelled' else ('pending' if status == 'pending' else 'paid'),
                    ship_name=c.get_full_name() or c.get_username(), ship_line1='12 Demo Street', ship_city=rnd.choice(CITIES),
                    ship_state='Maharashtra', ship_pincode='400001')
                total = Decimal(0)
                for p in rnd.sample(products, k=rnd.randint(1, min(3, len(products)))):
                    it = OrderItem.objects.create(order=o, product=p, quantity=rnd.randint(1, 3), unit_price=p.price)
                    total += it.line_total
                o.total = total
                o.save(update_fields=['total'])
                made += 1
            self.stdout.write(f'Created {made} orders.')
        self.stdout.write(self.style.SUCCESS(f'Done. {len(sellers)} sellers, {len(products)} products. No users were created.'))

    def _categories(self):
        subs = []
        for order, (top, children) in enumerate(TAXONOMY.items()):
            parent, _ = Category.objects.get_or_create(name=top, parent=None, defaults={'sort_order': order})
            for j, child in enumerate(children):
                sub, _ = Category.objects.get_or_create(name=child, parent=parent, defaults={'sort_order': j})
                subs.append(sub)
        return subs
