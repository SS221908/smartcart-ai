import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from paypal_service import PayPalServiceError, capture_order, create_order


class PayPalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_are_rejected_before_network_call(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(PayPalServiceError, "credentials"):
                await create_order({"subtotal": "10.00", "currency": "USD", "items": []})

    async def test_create_order_returns_approval_link(self):
        token_response = MagicMock()
        token_response.is_error = False
        token_response.json.return_value = {"access_token": "TOKEN-1"}
        order_response = MagicMock()
        order_response.is_error = False
        order_response.json.return_value = {"id": "ORDER-1", "status": "CREATED", "links": [{"rel": "approve", "href": "https://sandbox.example/approve"}]}
        client = AsyncMock()
        client.post.side_effect = [token_response, order_response]
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with patch.dict("os.environ", {"PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret", "PAYPAL_BASE_URL": "https://sandbox.example"}):
            with patch("paypal_service.httpx.AsyncClient", return_value=client):
                result = await create_order({"subtotal": "10.00", "currency": "USD", "items": [{"id": "p-1", "price": "10.00", "currency": "USD", "quantity": 1}]})
        self.assertEqual(result["order_id"], "ORDER-1")
        self.assertIn("approval_url", result)

    async def test_capture_error_preserves_safe_paypal_reason(self):
        token_response = MagicMock()
        token_response.is_error = False
        token_response.json.return_value = {"access_token": "TOKEN-1"}
        capture_response = MagicMock()
        capture_response.is_error = True
        capture_response.status_code = 422
        capture_response.json.return_value = {"name": "UNPROCESSABLE_ENTITY", "message": "The order was not approved", "details": [{"issue": "ORDER_NOT_APPROVED"}]}
        client = AsyncMock()
        client.post.side_effect = [token_response, capture_response]
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with patch.dict("os.environ", {"PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret", "PAYPAL_BASE_URL": "https://sandbox.example"}):
            with patch("paypal_service.httpx.AsyncClient", return_value=client):
                with self.assertRaisesRegex(PayPalServiceError, "ORDER_NOT_APPROVED"):
                    await capture_order("ORDER-1")


if __name__ == "__main__":
    unittest.main()
