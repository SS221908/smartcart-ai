import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


SUPPORTED_CURRENCY = "USD"


@dataclass(frozen=True)
class CatalogProduct:
    price: Decimal
    currency: str


def load_catalog(raw_catalog: str | None = None) -> dict[str, CatalogProduct]:
    raw = raw_catalog if raw_catalog is not None else os.getenv("PRODUCT_CATALOG_JSON", "")
    if not raw:
        return {}
    try:
        source = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PRODUCT_CATALOG_JSON must be valid JSON") from exc
    if not isinstance(source, dict):
        raise ValueError("PRODUCT_CATALOG_JSON must be an object keyed by product ID")

    catalog: dict[str, CatalogProduct] = {}
    for product_id, product in source.items():
        if not isinstance(product_id, str) or not product_id or not isinstance(product, dict):
            raise ValueError("Each catalog entry must have a product ID and object value")
        try:
            price = Decimal(str(product["price"]))
        except (KeyError, InvalidOperation, TypeError) as exc:
            raise ValueError(f"Catalog product {product_id} has an invalid price") from exc
        currency = product.get("currency", SUPPORTED_CURRENCY)
        if price <= 0 or currency != SUPPORTED_CURRENCY:
            raise ValueError(f"Catalog product {product_id} must use a positive USD price")
        catalog[product_id] = CatalogProduct(price=price, currency=currency)
    return catalog


def validate_cart(payload: dict[str, Any], catalog: dict[str, CatalogProduct]) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Cart must contain at least one item")
    budget = _decimal(payload.get("budget"), "budget")
    if budget <= 0:
        raise ValueError("Budget must be greater than zero")

    subtotal = Decimal("0")
    validated_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each cart item must be an object")
        product_id = item.get("id")
        if not isinstance(product_id, str) or not product_id:
            raise ValueError("Each cart item requires a product ID")
        if product_id not in catalog:
            raise ValueError(f"Unknown product ID: {product_id}")
        product = catalog[product_id]
        client_price = _decimal(item.get("price"), f"price for {product_id}")
        if client_price != product.price:
            raise ValueError(f"Price mismatch for {product_id}")
        if item.get("currency") != product.currency:
            raise ValueError(f"Currency mismatch for {product_id}")
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValueError(f"Quantity for {product_id} must be a positive whole number")
        line_total = product.price * quantity
        subtotal += line_total
        validated_items.append({"id": product_id, "price": str(product.price), "currency": product.currency, "quantity": quantity, "line_total": str(line_total)})

    client_total = payload.get("client_total")
    if client_total is not None and _decimal(client_total, "client_total") != subtotal:
        raise ValueError("Client total does not match the server total")

    return {"items": validated_items, "currency": SUPPORTED_CURRENCY, "budget": str(budget), "subtotal": str(subtotal), "remaining": str(budget - subtotal), "over_budget": subtotal > budget}


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result
