from decimal import Decimal as D

from django.test import SimpleTestCase

from orders.services.money import compute_money, line_gst, to_paise


class MoneyFormulaTests(SimpleTestCase):
    def test_spec_example_10000(self):
        m = compute_money('10000')
        self.assertEqual((m.margin, m.margin_gst, m.payout), (D('500.00'), D('90.00'), D('9410.00')))
        self.assertEqual(m.purchase_value, D('10000.00'))

    def test_gst_applies_to_margin_only(self):
        m = compute_money('10000')
        self.assertNotEqual(m.margin_gst, D('1800.00'))          # not 18% of the goods
        self.assertEqual(m.margin_gst, m.margin * D('0.18'))

    def test_payout_identity_and_paise_rounding(self):
        for value in ('1', '99.99', '1234.56', '333.33', '0.01', '7777.77', '123456.78'):
            m = compute_money(value)
            self.assertEqual(m.payout, m.purchase_value - m.margin - m.margin_gst, value)
            for part in (m.margin, m.margin_gst, m.payout):
                self.assertEqual(part, part.quantize(D('0.01')), value)

    def test_rounding_is_half_up(self):
        self.assertEqual(compute_money('10.10').margin, D('0.51'))      # 0.505 -> 0.51
        self.assertEqual(to_paise('2.675'), D('2.68'))

    def test_zero(self):
        m = compute_money('0')
        self.assertEqual((m.margin, m.margin_gst, m.payout), (D('0.00'), D('0.00'), D('0.00')))

    def test_rates_are_snapshot_inputs(self):
        m = compute_money('10000', commission_rate='0.10', gst_rate_on_margin='0.18')
        self.assertEqual((m.margin, m.margin_gst, m.payout), (D('1000.00'), D('180.00'), D('8820.00')))
        self.assertEqual((m.commission_rate, m.gst_rate_on_margin), (D('0.10'), D('0.18')))

    def test_customer_line_gst_is_separate(self):
        self.assertEqual(line_gst('500', 2, 18), D('180.00'))
        self.assertEqual(line_gst('99.99', 3, 5), D('15.00'))
