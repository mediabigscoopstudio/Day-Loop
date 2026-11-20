from decimal import Decimal as D

from django.test import SimpleTestCase

from catalog.models import chargeable_weight_kg, volumetric_weight_kg


class WeightTests(SimpleTestCase):
    def test_volumetric_formula(self):
        self.assertEqual(volumetric_weight_kg(30, 20, 10), D('1.200'))        # 6000 / 5000
        self.assertEqual(volumetric_weight_kg(10, 10, 10), D('0.200'))
        self.assertEqual(volumetric_weight_kg('25.5', '12', '8'), D('0.490'))  # 2448 / 5000

    def test_chargeable_is_the_larger_of_dead_and_volumetric(self):
        self.assertEqual(chargeable_weight_kg(500, 30, 20, 10), D('1.200'))   # volumetric wins
        self.assertEqual(chargeable_weight_kg(2500, 30, 20, 10), D('2.500'))  # dead weight wins
        self.assertEqual(chargeable_weight_kg(1200, 30, 20, 10), D('1.200'))  # tie

    def test_missing_dimensions_fall_back_to_dead_weight(self):
        self.assertEqual(volumetric_weight_kg(None, 10, 10), D('0.000'))
        self.assertEqual(chargeable_weight_kg(750, None, None, None), D('0.750'))
        self.assertEqual(chargeable_weight_kg(None, None, None, None), D('0.000'))
