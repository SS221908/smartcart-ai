"""Elastic hybrid retrieval for ranking the current Channel3 candidate set.

Requires an Elastic Cloud Serverless/9.4+ deployment with semantic_text support
and an account that can use its configured inference endpoint.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from smartcart_agent import Product


class ElasticError(RuntimeError):
    pass


class ElasticCatalogSearch:
    def __init__(self):
        self.base_url = os.getenv("ELASTICSEARCH_URL", "").rstrip("/")
        self.api_key = os.getenv("ELASTIC_API_KEY", "")
        self.index = os.getenv("ELASTIC_INDEX", "smartcart-products-v1")
        self.timeout = 25

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _request(self, method: str, path: str, body: Any = None,
                 content_type: str = "application/json", allow_404: bool = False) -> Any:
        if not self.configured:
            raise ElasticError("Set ELASTICSEARCH_URL and ELASTIC_API_KEY to enable Elastic")
        headers = {"Authorization": f"ApiKey {self.api_key}", "Content-Type": content_type}
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise ElasticError(f"Elasticsearch returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ElasticError(f"Elasticsearch request failed: {exc.reason}") from exc

    def ensure_index(self) -> None:
        present = self._request("HEAD", f"/{self.index}", allow_404=True)
        if present is not None:
            return
        mapping = {
            "mappings": {"properties": {
                "product_id": {"type": "keyword"},
                "title": {"type": "text"},
                "brand": {"type": "keyword"},
                "category": {"type": "keyword"},
                "price": {"type": "float"},
                "availability": {"type": "keyword"},
                "product_text": {"type": "text"},
                "semantic_text": {"type": "semantic_text"},
            }}
        }
        self._request("PUT", f"/{self.index}", mapping)

    def index_products(self, products: list[Product]) -> None:
        if not products:
            return
        self.ensure_index()
        lines = []
        for product in products:
            text = product.search_text()
            source = {
                "product_id": product.id,
                "title": product.name,
                "brand": product.brand,
                "category": product.category,
                "price": product.price,
                "availability": product.availability,
                "product_text": text,
                "semantic_text": text,
            }
            lines.append(json.dumps({"index": {"_index": self.index, "_id": product.id}}))
            lines.append(json.dumps(source, ensure_ascii=False))
        body = ("\n".join(lines) + "\n").encode("utf-8")
        result = self._request("POST", "/_bulk", body, content_type="application/x-ndjson")
        if result.get("errors"):
            failures = [item for item in result.get("items", []) if item.get("index", {}).get("error")]
            raise ElasticError(f"Some product documents could not be indexed: {failures[:2]}")

    def rerank(self, query: str, products: list[Product], limit: int = 20) -> list[str]:
        """Return Channel3 product IDs in Elastic's lexical+semantic RRF order."""
        if not products:
            return []
        self.index_products(products)
        ids = [p.id for p in products if p.id]
        body = {
            "size": max(1, min(limit, len(ids))),
            "retriever": {
                "rrf": {
                    "filter": {"terms": {"product_id": ids}},
                    "retrievers": [
                        {"standard": {"query": {"multi_match": {
                            "query": query,
                            "fields": ["title^3", "brand^2", "category", "product_text"],
                        }}}},
                        {"standard": {"query": {"match": {"semantic_text": {"query": query}}}}},
                    ],
                }
            },
            "_source": ["product_id"],
        }
        result = self._request("POST", f"/{self.index}/_search", body)
        hits = result.get("hits", {}).get("hits", [])
        return [str(hit.get("_source", {}).get("product_id", hit.get("_id", ""))) for hit in hits]
