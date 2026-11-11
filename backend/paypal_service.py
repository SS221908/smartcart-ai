import os
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx


class PayPalServiceError(RuntimeError):
    pass


def _paypal_error(response: httpx.Response, operation: str) -> PayPalServiceError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    name = payload.get("name") if isinstance(payload, dict) else None
    message = payload.get("message") if isinstance(payload, dict) else None
    issues = payload.get("details") if isinstance(payload, dict) else None
    issue_text = ""
    if isinstance(issues, list):
        codes = [str(item.get("issue")) for item in issues if isinstance(item, dict) and item.get("issue")]
        if codes:
            issue_text = f"; issues: {', '.join(codes)}"
    label = f" ({name})" if name else ""
    detail = f": {message}" if message else ""
    return PayPalServiceError(f"PayPal {operation} failed with HTTP {response.status_code}{label}{detail}{issue_text}")


def _settings() -> tuple[str, str, str]:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    base_url = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    if not client_id or not client_secret:
        raise PayPalServiceError("PayPal Sandbox credentials are not configured")
    return client_id, client_secret, base_url


async def _access_token(client: httpx.AsyncClient, client_id: str, client_secret: str, base_url: str) -> str:
    response = await client.post(
        f"{base_url}/v1/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
    )
    if response.is_error:
        raise _paypal_error(response, "authentication")
    token = response.json().get("access_token")
    if not token:
        raise PayPalServiceError("PayPal authentication returned no access token")
    return token


async def create_order(validated_cart: dict[str, Any]) -> dict[str, str]:
    client_id, client_secret, base_url = _settings()
    subtotal = Decimal(validated_cart["subtotal"])
    purchase_items = [
        {
            "name": item["id"],
            "quantity": str(item["quantity"]),
            "unit_amount": {"currency_code": item["currency"], "value": item["price"]},
        }
        for item in validated_cart["items"]
    ]
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": "studentcart-cart",
            "amount": {"currency_code": validated_cart["currency"], "value": f"{subtotal:.2f}", "breakdown": {"item_total": {"currency_code": validated_cart["currency"], "value": f"{subtotal:.2f}"}}},
            "items": purchase_items,
        }],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        token = await _access_token(client, client_id, client_secret, base_url)
        response = await client.post(
            f"{base_url}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "PayPal-Request-Id": str(uuid4())},
            json=body,
        )
    if response.is_error:
        raise _paypal_error(response, "order creation")
    data = response.json()
    approval_url = next((link["href"] for link in data.get("links", []) if link.get("rel") == "approve"), None)
    if not data.get("id") or not approval_url:
        raise PayPalServiceError("PayPal order response did not include an approval link")
    return {"order_id": data["id"], "approval_url": approval_url, "status": data.get("status", "CREATED")}


async def capture_order(order_id: str) -> dict[str, Any]:
    client_id, client_secret, base_url = _settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        token = await _access_token(client, client_id, client_secret, base_url)
        response = await client.post(
            f"{base_url}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "PayPal-Request-Id": str(uuid4())},
            json={},
        )
    if response.is_error:
        raise _paypal_error(response, "order capture")
    data = response.json()
    return {"order_id": data.get("id", order_id), "status": data.get("status", "UNKNOWN"), "raw": data}
