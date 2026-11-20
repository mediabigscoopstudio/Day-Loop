"""
Creates six months of realistic order history through the REAL checkout and seller
flow, so every number on the admin and seller dashboards comes from the same code
that real orders use (5% margin, 18% GST on the margin, ledger credit on delivery).

Development / staging only. Run it with:
    SEED_ALLOW=1 SEED_PASSWORD='...' python manage.py seed_economics --orders 6000 --days 180
"""
import os
import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from catalog.models import Product, ProductVariant
from orders.models import LedgerEntry, Order, SellerOrder
from orders.services import seller_flow as flow
from orders.services.checkout import CheckoutError, create_order
from orders.services.seller_flow import FlowError
from sellers.models import SellerProfile

User = get_user_model()
S = SellerOrder.Status

ADDRESSES = [
    ('Sunrise Residency, Flat 302', 'Bengaluru', 'Karnataka', '560038'),
    ('12, 5th Cross, Koramangala', 'Bengaluru', 'Karnataka', '560034'),
    ('B-14, Lokhandwala Complex', 'Mumbai', 'Maharashtra', '400053'),
    ('45, Sector 18', 'Noida', 'Uttar Pradesh', '201301'),
    ('7-2-19, Banjara Hills', 'Hyderabad', 'Telangana', '500034'),
    ('CF-88, Salt Lake Sector 1', 'Kolkata', 'West Bengal', '700064'),
    ('23, Anna Nagar 2nd Avenue', 'Chennai', 'Tamil Nadu', '600040'),
    ('9, Satellite Road', 'Ahmedabad', 'Gujarat', '380015'),
]
NAMES = ['Rahul Sharma', 'Priya Nair', 'Arjun Iyer', 'Neha Gupta', 'Kavya Rao',
         'Rohan Mehta', 'Aditi Patel', 'Vikram Singh', 'Sneha Reddy', 'Karan Malhotra']
PAYMENT_METHODS = ['upi', 'card', 'netbanking', 'cod']
PAYMENT_WEIGHTS = [55, 25, 8, 12]
COURIERS = ['Delhivery', 'Shiprocket', 'Blue Dart', 'Ekart']
CANCEL_RATE = 0.03
RETURN_RATE = 0.03
# (minimum order age in days, workflow steps to take): accept, pack, ship, deliver
STAGES = [(1, 1), (2, 2), (4, 3), (7, 4)]


class Command(BaseCommand):
    help = 'Create realistic order history through the real checkout and seller flow (development / staging only).'

    def add_arguments(self, parser):
        parser.add_argument('--orders', type=int, default=6000)
        parser.add_argument('--customers', type=int, default=400)
        parser.add_argument('--days', type=int, default=180)

    def handle(self, *args, **opts):
        if not settings.DEBUG and os.environ.get('SEED_ALLOW') != '1':
            raise CommandError('Set SEED_ALLOW=1 to run this on a server. It creates demo orders on the live site.')
        password = os.environ.get('SEED_PASSWORD')
        if not password:
            raise CommandError('Set SEED_PASSWORD first.')

        variants = list(ProductVariant.objects.filter(
            is_active=True, product__status=Product.Status.LIVE,
            seller__status=SellerProfile.Status.APPROVED,
        ).select_related('product', 'seller'))
        if not variants:
            raise CommandError('No live products from approved sellers. Seed the catalogue first.')
        # Demo stock so six months of orders never run out. Only the stock count changes.
        ProductVariant.objects.filter(pk__in=[v.pk for v in variants]).update(stock=10000)

        customers = self._customers(opts['customers'], password)
        cust_weights = [1 / (i + 1) ** 0.8 for i in range(len(customers))]   # a few heavy repeat buyers

        days, total_orders = opts['days'], opts['orders']
        today = timezone.localdate()
        dates = [today - timedelta(days=days - 1 - d) for d in range(days)]
        # Sales grow about 2.4x over the period, and weekends are busier.
        weights = [(0.6 + 0.8 * d / max(days - 1, 1)) * (1.3 if dates[d].weekday() >= 5 else 1.0)
                   for d in range(days)]
        scale = total_orders / sum(weights)

        created = skipped = 0
        for d, day in enumerate(dates):
            for _ in range(round(weights[d] * scale)):
                placed = self._stamp(day)
                customer = random.choices(customers, cust_weights)[0]
                try:
                    with transaction.atomic():
                        order = create_order(
                            customer, self._cart(variants), address=self._address(),
                            payment_method=random.choices(PAYMENT_METHODS, PAYMENT_WEIGHTS)[0],
                            payment_status=Order.PaymentStatus.PAID, now=placed,
                        )
                        self._progress(order, placed)
                except CheckoutError:
                    skipped += 1
                    continue
                created += 1

        window_start = timezone.now() - timedelta(days=days + 1)
        totals = (SellerOrder.objects.filter(order__placed_at__gte=window_start)
                  .exclude(status=S.CANCELLED)
                  .aggregate(purchase=Sum('purchase_value'), margin=Sum('margin'), payout=Sum('payout')))
        purchase = totals['purchase'] or 0
        margin = totals['margin'] or 0
        payout = totals['payout'] or 0
        self.stdout.write(self.style.SUCCESS(f'Created {created} orders over {days} days ({skipped} skipped).'))
        self.stdout.write(f'Purchase value: ₹{purchase:,.2f}')
        self.stdout.write(f'Platform margin: ₹{margin:,.2f}')
        self.stdout.write(f'Seller payouts (before returns): ₹{payout:,.2f}')

    # ---------- helpers ----------

    def _customers(self, n, password):
        hashed = make_password(password)   # hash once; hashing per user would be slow
        users = []
        for i in range(1, n + 1):
            email = f'shopper{i:04d}@dayloop.test'
            user, _ = User.objects.get_or_create(username=email, defaults={'email': email, 'password': hashed})
            users.append(user)
        return users

    def _stamp(self, day):
        t = time(random.randint(8, 22), random.randint(0, 59), random.randint(0, 59))
        placed = timezone.make_aware(datetime.combine(day, t))
        now = timezone.now()
        return placed if placed <= now else now - timedelta(minutes=random.randint(5, 180))

    def _cart(self, variants):
        k = min(random.choices([1, 2, 3, 4], [45, 30, 15, 10])[0], len(variants))
        return [(v.pk, random.choices([1, 2, 3], [60, 30, 10])[0]) for v in random.sample(variants, k)]

    def _address(self):
        line1, city, state, pin = random.choice(ADDRESSES)
        return {'name': random.choice(NAMES), 'line1': line1, 'city': city, 'state': state, 'pincode': pin}

    def _progress(self, order, placed):
        """Walk each seller order through the real seller flow, then backdate its timestamps."""
        now = timezone.now()
        age = (now - placed).days
        for so in order.seller_orders.select_related('seller'):
            seller = so.seller
            if age >= 1 and random.random() < CANCEL_RATE:
                try:
                    flow.cancel(seller, so.pk, None, reason='Item out of stock at dispatch')
                except FlowError:
                    pass
                continue
            target = max((steps for min_age, steps in STAGES if age >= min_age), default=0)
            if target == 0:
                continue
            for _ in range(target):
                flow.advance(seller, so.pk, None, courier=random.choice(COURIERS),
                             awb=f'AWB{random.randint(10**9, 10**10 - 1)}')
            dated = {'created_at': placed}
            if target >= 3:
                dated['shipped_at'] = placed + timedelta(days=2)
            if target >= 4:
                dated['delivered_at'] = placed + timedelta(days=5)
                LedgerEntry.objects.filter(seller_order=so, kind=LedgerEntry.Kind.CREDIT).update(
                    created_at=placed + timedelta(days=5))
                if random.random() < RETURN_RATE:
                    flow.mark_returned(seller, so.pk, None, reason='Customer returned the item')
                    LedgerEntry.objects.filter(seller_order=so, kind=LedgerEntry.Kind.DEBIT).update(
                        created_at=min(placed + timedelta(days=9), now))
            SellerOrder.objects.filter(pk=so.pk).update(**dated)

        statuses = set(order.seller_orders.values_list('status', flat=True))
        if statuses == {S.CANCELLED}:
            order.status, order.payment_status = Order.Status.CANCELLED, Order.PaymentStatus.REFUNDED
        elif statuses <= {S.DELIVERED, S.RETURNED, S.CANCELLED}:
            order.status = Order.Status.DELIVERED
        elif statuses & {S.SHIPPED, S.DELIVERED, S.RETURNED}:
            order.status = Order.Status.SHIPPED
        else:
            order.status = Order.Status.PROCESSING
        order.save(update_fields=['status', 'payment_status'])