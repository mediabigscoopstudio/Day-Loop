from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from dash.services import metrics
from dash.services.dates import build_range

from . import factories as f

TODAY = date(2025, 1, 31)


def at(d, hour=10):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour))


class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dr = build_range(date(2025, 1, 21), TODAY, '7d' if False else 'custom')   # 11 days
        cls.cat = f.make_category('Wellness')
        cls.sub = f.make_category('Protein', parent=cls.cat)
        cls.cat2 = f.make_category('Care')
        cls.sub2 = f.make_category('Skin', parent=cls.cat2)
        cls.s1, cls.s2 = f.make_seller('Prana'), f.make_seller('Ayura')
        cls.p1 = f.make_product(cls.s1, cls.sub, '1000')
        cls.p2 = f.make_product(cls.s2, cls.sub2, '500')
        cls.a, cls.b = f.make_user('a'), f.make_user('b')
        # current period (Jan 21-31)
        f.make_order(cls.a, at(date(2025, 1, 22)), [(cls.p1, 2)])             # 2000
        f.make_order(cls.a, at(date(2025, 1, 25)), [(cls.p2, 1)])             # 500  (a is repeat)
        f.make_order(cls.b, at(date(2025, 1, 30)), [(cls.p1, 1), (cls.p2, 2)])  # 2000
        f.make_order(cls.b, at(date(2025, 1, 30)), [(cls.p1, 5)], status='cancelled')  # excluded
        # prior period (Jan 10-20)
        f.make_order(cls.a, at(date(2025, 1, 12)), [(cls.p1, 1)])             # 1000

    def kpi(self, key):
        return {k['key']: k for k in metrics.overview_kpis(self.dr)}[key]

    def test_kpis_and_deltas(self):
        self.assertEqual(self.kpi('gmv')['value'], Decimal('4500'))
        self.assertEqual(self.kpi('gmv')['delta'], 350.0)          # 4500 vs 1000
        self.assertEqual(self.kpi('orders')['value'], 3)
        self.assertEqual(self.kpi('orders')['delta'], 200.0)       # 3 vs 1
        self.assertEqual(self.kpi('sellers')['value'], 2)
        self.assertEqual(self.kpi('repeat')['value'], 1)           # only customer a has 2+ orders
        self.assertEqual(self.kpi('aov')['value'], Decimal('1500'))

    def test_cancelled_orders_are_excluded(self):
        self.assertEqual(metrics.live_orders(self.dr).count(), 3)

    def test_pending_kpi_counts_current_pending_sellers(self):
        f.make_seller('Waiting', status='pending')
        self.assertEqual(self.kpi('pending')['value'], 1)

    def test_sales_series_fills_empty_days_with_zero(self):
        s = metrics.sales_series(self.dr)
        self.assertEqual(len(s['labels']), 11)
        self.assertEqual(sum(s['gmv']), 4500.0)
        self.assertEqual(s['gmv'][s['labels'].index('Jan 23')], 0)
        self.assertEqual(s['gmv'][s['labels'].index('Jan 30')], 2000.0)

    def test_category_revenue_shares(self):
        c = metrics.category_revenue(self.dr)
        by = {r['name']: r for r in c['rows']}
        self.assertEqual(by['Wellness']['revenue'], 3000.0)
        self.assertEqual(by['Care']['revenue'], 1500.0)
        self.assertEqual(by['Wellness']['share'], 66.7)
        sub = metrics.category_revenue(self.dr, level='subcategory')
        self.assertEqual({r['name'] for r in sub['rows']}, {'Protein', 'Skin'})

    def test_top_sellers_with_growth(self):
        rows = metrics.top_sellers(self.dr)
        self.assertEqual(rows[0]['name'], 'Prana')
        self.assertEqual(rows[0]['gmv'], Decimal('3000'))
        self.assertEqual(rows[0]['growth'], 200.0)       # 3000 vs 1000
        self.assertIsNone(rows[1]['growth'])             # Ayura had no prior sales

    def test_new_vs_repeat_and_cohorts_run(self):
        nv = metrics.new_vs_repeat(self.dr)
        self.assertEqual(sum(nv['new']), 1)       # only b's first-ever order falls in this period
        self.assertEqual(sum(nv['repeat']), 2)    # a's two orders (a first ordered on Jan 12)
        cohorts = metrics.repeat_cohorts()
        self.assertEqual(cohorts[0]['customers'], 2)
        self.assertEqual(cohorts[0]['repeaters'], 1)
        self.assertEqual(cohorts[0]['rate'], 50.0)

    def test_empty_database_ranges_return_zeroes_not_errors(self):
        empty = build_range(date(2020, 1, 1), date(2020, 1, 10))
        self.assertEqual(metrics.overview_kpis(empty)[0]['value'], Decimal('0'))
        self.assertEqual(metrics.category_revenue(empty)['rows'], [])
        self.assertEqual(sum(metrics.sales_series(empty)['gmv']), 0)

    def test_recent_orders_one_query(self):
        with self.assertNumQueries(1):
            rows = metrics.recent_orders()
            [(o.customer.username, o.item_count, o.first_seller) for o in rows]
