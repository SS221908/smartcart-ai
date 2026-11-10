"""Channel3 product catalog and conversational agent REST integration.

API keys are read only from environment variables. The API follows Channel3's
published /v1/search and conversations endpoints.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from smartcart_agent import Product

BASE_URL = "https://api.trychannel3.com/v1"


class Channel3Error(RuntimeError):
    pass


class Channel3Client:
    def __init__(self, api_key: str | None = None, timeout: int = 25):
        self.api_key = api_key or os.getenv("CHANNEL3_API_KEY", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                 bearer: str | None = None, accept: str = "application/json") -> bytes:
        if not self.api_key:
            raise Channel3Error("CHANNEL3_API_KEY is not configured")
        headers = {"Content-Type": "application/json", "Accept": accept}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        else:
            headers["x-api-key"] = self.api_key
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise Channel3Error(f"Channel3 returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise Channel3Error(f"Channel3 request failed: {exc.reason}") from exc

    def search_products(self, query: str, budget: float, limit: int = 20,
                        user_id: str | None = None) -> list[Product]:
        """Search structured products and offers, applying a per-item price cap."""
        body = {
            "query": query,
            "filters": {
                "price": {"max_price": float(budget)},
                "availability": ["InStock"],
            },
            "limit": max(1, min(int(limit), 50)),
        }
        headers_user = user_id.strip() if user_id else ""
        if headers_user:
            # The optional attribution header is supported by Channel3 catalog calls.
            return self._search_with_user(body, headers_user)
        response = json.loads(self._request("POST", "/search", body))
        return self._products_from_response(response)

    def _search_with_user(self, body: dict[str, Any], user_id: str) -> list[Product]:
        headers = {
            "x-api-key": self.api_key,
            "x-user-id": user_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request = urllib.request.Request(
            BASE_URL + "/search", data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise Channel3Error(f"Channel3 returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise Channel3Error(f"Channel3 request failed: {exc.reason}") from exc
        return self._products_from_response(payload)

    @staticmethod
    def _products_from_response(payload: dict[str, Any]) -> list[Product]:
        products = []
        for row in payload.get("products", []):
            offers = row.get("offers") or []
            valid = []
            for offer in offers:
                availability = str(offer.get("availability") or "unknown")
                price_obj = offer.get("price")
                price = price_obj.get("price") if isinstance(price_obj, dict) else price_obj
                currency = price_obj.get("currency", "USD") if isinstance(price_obj, dict) else "USD"
                try:
                    numeric_price = float(price)
                except (TypeError, ValueError):
                    continue
                if availability.lower() in {"instock", "in stock", "available"} and currency.upper() == "USD":
                    valid.append((numeric_price, offer, currency))
            if not valid:
                continue
            price, offer, currency = min(valid, key=lambda item: item[0])
            category = row.get("category") or "other"
            if isinstance(category, dict):
                category = category.get("title") or category.get("slug") or "other"
            brands = row.get("brands") or []
            brand = ", ".join(b.get("name", "") for b in brands if isinstance(b, dict))
            image = ""
            for candidate in row.get("images") or []:
                if isinstance(candidate, dict):
                    image = candidate.get("cleaned_url") or candidate.get("url") or ""
                    if image:
                        break
            attrs = row.get("structured_attributes") or {}
            attrs = {str(k): str(v) for k, v in attrs.items()} if isinstance(attrs, dict) else {}
            tags = [str(x) for x in (row.get("key_features") or []) if x]
            products.append(Product(
                id=str(row.get("id") or ""),
                name=str(row.get("title") or "Unnamed product"),
                category=str(category), price=price, currency=str(currency), brand=brand,
                description=str(row.get("description") or ""), attributes=attrs, tags=tags,
                image_url=image, url=str(offer.get("url") or row.get("url") or ""),
                merchant=str(offer.get("domain") or ""), availability=str(offer.get("availability") or "InStock"),
                source="Channel3",
            ))
        return products

    def create_client_token(self) -> dict[str, str]:
        """Create a short-lived token for the Channel3 shopping conversation API."""
        payload = json.loads(self._request("POST", "/conversations/client_tokens", {}))
        token = payload.get("token")
        if not token:
            raise Channel3Error("Channel3 did not return a client token")
        return {"token": str(token), "expires_at": str(payload.get("expires_at") or "")}

    def conversation_turn(self, token: str, message: str,
                          conversation_id: str | None = None) -> dict[str, str]:
        """Send one user turn and collect Channel3's streamed assistant text."""
        body: dict[str, Any] = {"message": {"role": "user", "parts": [{"type": "text", "text": message}]}}
        if conversation_id:
            body["conversation_id"] = conversation_id
        raw = self._request("POST", "/conversations", body, bearer=token,
                            accept="text/event-stream, application/json")
        current_event = ""
        conversation = conversation_id or ""
        assistant_text: list[str] = []

        # HTTP body is small enough for a full read for the demo service. Parse
        # event framing after receiving it while retaining the event boundaries.
        for block in raw.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n\n"):
            event_name = ""
            data_lines = []
            for line in block.splitlines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if not data_lines:
                continue
            data_text = "\n".join(data_lines)
            try:
                event = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            kind = str(event.get("type") or event_name)
            if kind == "turn.started":
                conversation = str(event.get("conversation_id") or conversation)
            elif kind == "part.delta":
                delta = event.get("delta", "")
                if isinstance(delta, dict):
                    delta = delta.get("text", "")
                if isinstance(delta, str):
                    assistant_text.append(delta)
            elif kind == "turn.completed":
                complete = _message_text(event.get("message"))
                if complete:
                    assistant_text = [complete]
            elif kind in {"error", "turn.failed"}:
                raise Channel3Error(str(event.get("message") or event.get("error") or "Agent turn failed"))
        return {"conversation_id": conversation, "text": "".join(assistant_text)}


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    found = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if text:
                found.append(str(text))
    if found:
        return "".join(found)
    return str(message.get("text") or "")
