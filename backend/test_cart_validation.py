import unittest
from decimal import Decimal

from cart_validation import CatalogProduct, validate_cart


CATALOG = {
    "laptop-1": CatalogProduct(Decimal("100.00"), "USD"),
    "stand-1": CatalogProduct(Decimal("25.00"), "USD"),
}


class CartValidationTests(unittest.TestCase):
    def test_valid_cart_recalculates_server_total(self):
        result = validate_cart({"items": [{"id": "laptop-1", "price": 100, "currency": "USD", "quantity": 2}], "budget": 300, "client_total": 200}, CATALOG)
        self.assertEqual(result["subtotal"], "200.00")
        self.assertFalse(result["over_budget"])

    def test_unknown_product_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown product ID"):
            validate_cart({"items": [{"id": "unknown", "price": 1, "currency": "USD", "quantity": 1}], "budget": 300}, CATALOG)

    def test_modified_price_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Price mismatch"):
            validate_cart({"items": [{"id": "laptop-1", "price": 1, "currency": "USD", "quantity": 1}], "budget": 300}, CATALOG)

    def test_modified_client_total_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Client total"):
            validate_cart({"items": [{"id": "laptop-1", "price": 100, "currency": "USD", "quantity": 1}], "budget": 300, "client_total": 1}, CATALOG)

    def test_invalid_quantity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive whole number"):
            validate_cart({"items": [{"id": "laptop-1", "price": 100, "currency": "USD", "quantity": 0}], "budget": 300}, CATALOG)


if __name__ == "__main__":
    unittest.main()
