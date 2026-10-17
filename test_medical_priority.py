"""Focused regression tests for essential goods classification and priority."""
import unittest

from decision import needs_approval, priority
from prepare_data import to_orders
import pandas as pd


class MedicalPriorityTests(unittest.TestCase):
    def test_medical_priority_beats_ordinary_when_stock_is_critical(self):
        medicine = priority(0.20, 5, 2, 1, 1)
        office = priority(0.80, 2, 2, 20, 1)
        self.assertGreater(medicine, office)

    def test_criticality_is_clamped(self):
        self.assertEqual(priority(2, 8, 2, 1, 0), priority(1, 5, 2, 1, 0))

    def test_high_criticality_action_requires_approval(self):
        self.assertTrue(needs_approval("expedite", 5))
        self.assertFalse(needs_approval("monitor", 5))

    def test_health_beauty_alone_is_not_medical(self):
        # Minimal DataCo-shaped input; broad department is not proof of medicine.
        row = {
            "Order Id": 1, "order_ts": pd.Timestamp("2025-01-01"),
            "Days for shipping (real)": 2, "Days for shipment (scheduled)": 2,
            "Late_delivery_risk": 0, "Delivery Status": "Shipping on time",
            "Shipping Mode": "Standard Class", "Market": "US", "Order Region": "East",
            "Department Name": "Health and Beauty", "Category Name": "Personal Care",
            "Customer Segment": "Consumer", "Order Item Quantity": 1, "Sales": 10,
            "Order Item Product Price": 10, "Product Card Id": 1,
            "Product Name": "Generic Beauty Lotion", "Order Status": "COMPLETE",
        }
        # to_orders expects source column names as well as parsed order_ts.
        frame = pd.DataFrame([row])
        out = to_orders(frame)
        self.assertEqual(out.iloc[0]["essential_goods_type"], "other")
        self.assertEqual(int(out.iloc[0]["criticality"]), 3)

    def test_medicine_keyword_is_classified(self):
        row = {
            "Order Id": 2, "order_ts": pd.Timestamp("2025-01-01"),
            "Days for shipping (real)": 2, "Days for shipment (scheduled)": 2,
            "Late_delivery_risk": 0, "Delivery Status": "Shipping on time",
            "Shipping Mode": "Standard Class", "Market": "US", "Order Region": "East",
            "Department Name": "Health and Beauty", "Category Name": "Personal Care",
            "Customer Segment": "Consumer", "Order Item Quantity": 1, "Sales": 10,
            "Order Item Product Price": 10, "Product Card Id": 2,
            "Product Name": "Insulin medicine", "Order Status": "COMPLETE",
        }
        out = to_orders(pd.DataFrame([row]))
        self.assertEqual(out.iloc[0]["essential_goods_type"], "medicine")
        self.assertEqual(int(out.iloc[0]["criticality"]), 5)


if __name__ == "__main__":
    unittest.main()
