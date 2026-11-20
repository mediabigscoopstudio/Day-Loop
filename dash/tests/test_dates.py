from datetime import date

from django.test import SimpleTestCase

from dash.services.dates import build_range, delta_pct, parse_range

TODAY = date(2025, 1, 31)


class DateRangeTests(SimpleTestCase):
    def test_presets_cover_equal_length_and_prior_is_adjacent(self):
        for key, days in (('today', 1), ('7d', 7), ('30d', 30), ('90d', 90), ('12m', 365)):
            r = parse_range({'range': key}, today=TODAY)
            self.assertEqual(r.days, days, key)
            self.assertEqual(r.end_date, TODAY)
            p = r.prior
            self.assertEqual(p.days, days, key)
            self.assertEqual(p.end, r.start, 'prior ends exactly where current starts')

    def test_30d_range_jan_2025(self):
        r = parse_range({'range': '30d'}, today=TODAY)
        self.assertEqual(r.start_date, date(2025, 1, 2))
        self.assertEqual(r.prior.start_date, date(2024, 12, 3))
        self.assertEqual(r.prior.end_date, date(2025, 1, 1))

    def test_custom_range_and_prior(self):
        r = parse_range({'range': 'custom', 'start': '2025-01-01', 'end': '2025-01-10'}, today=TODAY)
        self.assertEqual(r.days, 10)
        self.assertEqual(r.prior.start_date, date(2024, 12, 22))
        self.assertEqual(r.prior.end_date, date(2024, 12, 31))

    def test_invalid_input_falls_back_to_default(self):
        for params in ({'range': 'bogus'}, {'range': 'custom'}, {'range': 'custom', 'start': 'x', 'end': 'y'},
                       {'range': 'custom', 'start': '2025-02-01', 'end': '2025-01-01'}, {}):
            self.assertEqual(parse_range(params, today=TODAY).days, 30, params)

    def test_granularity(self):
        self.assertEqual(parse_range({'range': '90d'}, today=TODAY).granularity, 'day')
        self.assertEqual(parse_range({'range': '12m'}, today=TODAY).granularity, 'month')


class DeltaTests(SimpleTestCase):
    def test_delta_math(self):
        self.assertEqual(delta_pct(112, 100), 12.0)
        self.assertEqual(delta_pct(90, 100), -10.0)
        self.assertEqual(delta_pct(0, 0), 0.0)
        self.assertIsNone(delta_pct(50, 0))
        self.assertEqual(delta_pct(100, 100), 0.0)
        self.assertEqual(delta_pct(1, 3), -66.7)
