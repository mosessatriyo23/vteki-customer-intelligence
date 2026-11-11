"""Tests for the development-only pure business CLV calculator."""

import math
import unittest

from services.data.models.business_clv import calculate_business_clv


class BusinessCLVTests(unittest.TestCase):
    def test_formula_uses_gross_revenue_and_explicit_retention(self):
        result = calculate_business_clv(120_000, 50_000, 2, 0.5, 4)
        self.assertEqual(result, {"clv": 720_000.0, "tier": "GOLD"})

    def test_tier_boundaries(self):
        cases = (
            (1_000_000, "PLATINUM"),
            (500_000, "GOLD"),
            (200_000, "SILVER"),
            (199_999.99, "INSUFFICIENT_HISTORY"),
        )
        for historical, tier in cases:
            with self.subTest(historical=historical):
                self.assertEqual(
                    calculate_business_clv(historical, 0, 0, 0, 2)["tier"], tier
                )

    def test_fewer_than_two_transactions_is_always_insufficient(self):
        for count in (0, 1):
            with self.subTest(count=count):
                result = calculate_business_clv(2_000_000, 0, 0, 1, count)
                self.assertEqual(result["tier"], "INSUFFICIENT_HISTORY")

    def test_zero_values_are_valid(self):
        self.assertEqual(
            calculate_business_clv(0, 0, 0, 0, 0),
            {"clv": 0.0, "tier": "INSUFFICIENT_HISTORY"},
        )

    def test_retention_is_required(self):
        with self.assertRaises(TypeError):
            calculate_business_clv(100, 10, 1, transaction_count=2)  # type: ignore

    def test_numeric_inputs_reject_nan_infinity_and_bool(self):
        for value in (math.nan, math.inf, -math.inf, True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    calculate_business_clv(value, 0, 0, 0, 2)
                with self.assertRaises(ValueError):
                    calculate_business_clv(0, value, 0, 0, 2)
                with self.assertRaises(ValueError):
                    calculate_business_clv(0, 0, value, 0, 2)
                with self.assertRaises(ValueError):
                    calculate_business_clv(0, 0, 0, value, 2)

    def test_numeric_inputs_reject_negative_and_retention_above_one(self):
        for position in range(4):
            values = [0, 0, 0, 0]
            values[position] = -1
            with self.subTest(position=position):
                with self.assertRaises(ValueError):
                    calculate_business_clv(*values, 2)
        with self.assertRaises(ValueError):
            calculate_business_clv(0, 0, 0, 1.01, 2)

    def test_transaction_count_is_nonnegative_int_and_rejects_bool(self):
        for value in (-1, 1.5, "2", True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    calculate_business_clv(0, 0, 0, 0, value)


if __name__ == "__main__":
    unittest.main()
