import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase

from catalog.models import ProductVariant, StockMovement
from catalog.services.stock import InsufficientStock, StockError, adjust_stock, take_stock
from dash.tests import factories as f


def _variant(stock=5, seller=None):
    seller = seller or f.make_seller()
    sub = f.make_category('S', f.make_category('C'))
    return f.make_product(seller, sub, '100', stock=stock).variant


class StockServiceTests(TestCase):
    def test_add_remove_set_write_movements(self):
        v = _variant(5)
        adjust_stock(v.pk, 'add', 10, reason='Restock')
        adjust_stock(v.pk, 'remove', 3, reason='Damaged')
        adjust_stock(v.pk, 'set', 20, reason='Count')
        v.refresh_from_db()
        self.assertEqual(v.stock, 20)
        rows = list(StockMovement.objects.filter(variant=v).order_by('id').values_list('kind', 'delta', 'balance_after', 'reason'))
        self.assertEqual(rows, [('add', 10, 15, 'Restock'), ('remove', -3, 12, 'Damaged'), ('set', 8, 20, 'Count')])

    def test_cannot_remove_more_than_available(self):
        v = _variant(2)
        with self.assertRaises(InsufficientStock):
            adjust_stock(v.pk, 'remove', 3)
        v.refresh_from_db()
        self.assertEqual(v.stock, 2)
        self.assertFalse(StockMovement.objects.filter(variant=v).exists())

    def test_negative_quantity_rejected_and_other_sellers_variant_is_not_found(self):
        v, other = _variant(5), f.make_seller()
        with self.assertRaises(StockError):
            adjust_stock(v.pk, 'add', -1)
        with self.assertRaises(ProductVariant.DoesNotExist):
            adjust_stock(v.pk, 'add', 1, seller=other)

    def test_take_stock_is_all_or_nothing(self):
        a, b = _variant(5), _variant(1)
        from django.db import transaction
        with self.assertRaises(InsufficientStock), transaction.atomic():
            take_stock([(a.pk, 2), (b.pk, 2)])
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.stock, b.stock), (5, 1))

    def test_moq_is_enforced(self):
        v = _variant(50)
        ProductVariant.objects.filter(pk=v.pk).update(moq=5)
        from django.db import transaction
        with self.assertRaises(StockError), transaction.atomic():
            take_stock([(v.pk, 2)])


class StockConcurrencyTests(TransactionTestCase):
    """Real threads and real row locks: two buyers race for the last unit."""

    def test_two_concurrent_orders_cannot_oversell(self):
        v = _variant(1)
        barrier = threading.Barrier(2)
        results = []

        def buy():
            try:
                barrier.wait(timeout=5)
                adjust_stock(v.pk, 'sale', 1, reference='race')
                results.append('ok')
            except InsufficientStock:
                results.append('sold-out')
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            for fut in [pool.submit(buy), pool.submit(buy)]:
                fut.result()
        v.refresh_from_db()
        self.assertEqual(sorted(results), ['ok', 'sold-out'])
        self.assertEqual(v.stock, 0)
        self.assertEqual(StockMovement.objects.filter(variant=v, kind='sale').count(), 1)

    def test_many_buyers_never_drive_stock_negative(self):
        v = _variant(3)
        results = []

        def buy():
            try:
                adjust_stock(v.pk, 'sale', 1)
                results.append(1)
            except InsufficientStock:
                results.append(0)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=8) as pool:
            for fut in [pool.submit(buy) for _ in range(8)]:
                fut.result()
        v.refresh_from_db()
        self.assertEqual(sum(results), 3)
        self.assertEqual(v.stock, 0)
