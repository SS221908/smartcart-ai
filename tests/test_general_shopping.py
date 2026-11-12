import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from smartcart_agent import Product, StudentRequest, recommend


class FakeChannel3Client:
    configured = True

    def __init__(self, search):
        self.search = search
        self.queries = []

    def search_products(self, query, budget, limit=20, user_id=None):
        self.queries.append(query)
        return self.search(query)


class DisabledElastic:
    configured = False


class GeneralShoppingAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.environment = patch.dict(os.environ, {"SMARTCART_DEMO": "false"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def post_with_catalog(self, payload, search):
        channel = FakeChannel3Client(search)
        self.enterContext(patch.object(api, "Channel3Client", return_value=channel))
        self.enterContext(patch.object(api, "ElasticCatalogSearch", DisabledElastic))
        response = self.client.post("/api/recommendations", json=payload)
        return response, channel

    def test_local_vite_origin_is_allowed_by_cors(self):
        response = self.client.options(
            "/api/recommendations",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_unlisted_category_is_searched_from_free_text(self):
        telescope = Product(
            id="telescope-1",
            name="Beginner tabletop telescope",
            category="optical instruments",
            price=89.99,
            description="A compact telescope for backyard astronomy.",
            tags=["stargazing"],
        )
        response, channel = self.post_with_catalog(
            {
                "goal": "beginner telescope",
                "budget": 150,
                "owns": ["none"],
                "use_case": "backyard stargazing",
                "priorities": ["value, easy setup"],
                "device_details": "string",
                "must_haves": ["string"],
            },
            lambda query: [telescope],
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["recommendations"][0]["id"], "telescope-1")
        self.assertEqual(body["catalog_results_count"], 1)
        self.assertNotIn("string", channel.queries[0].lower())
        self.assertEqual(body["empty_reason"], None)

    def test_broader_retry_recovers_from_overly_narrow_query(self):
        unrelated = Product(
            id="headset-1", name="Gaming headset", category="audio", price=49.99,
        )
        graphics_card = Product(
            id="graphics-1", name="Gaming graphics card", category="computer component",
            price=299.99, tags=["graphics", "performance"],
        )

        def search(query):
            if "graphics" in query.lower():
                return [unrelated]
            return [graphics_card]

        response, channel = self.post_with_catalog(
            {
                "goal": "gaming setup",
                "budget": 1000,
                "owns": ["speaker"],
                "use_case": "gaming for fun",
                "priorities": ["performance"],
                "must_haves": ["good graphics"],
            },
            search,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(len(channel.queries), 2)
        self.assertIn("graphics", channel.queries[0].lower())
        self.assertNotIn("graphics", channel.queries[1].lower())
        self.assertEqual(body["recommendations"][0]["id"], "graphics-1")

    def test_text_lists_and_none_work_without_excluding_a_related_category(self):
        headphones = Product(
            id="wireless-headphones", name="Wireless over-ear headphones",
            category="audio", price=79.99, tags=["wireless", "comfortable"],
        )
        response, channel = self.post_with_catalog(
            {
                "goal": "audio accessories",
                "budget": 100,
                "owns": "speaker",
                "use_case": "video calls",
                "priorities": "comfort\nprice",
                "must_haves": "wireless",
            },
            lambda query: [headphones],
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["id"] for item in body["recommendations"]], ["wireless-headphones"])
        self.assertIn("comfort", channel.queries[0].lower())
        self.assertIn("price", channel.queries[0].lower())

        none_response, _ = self.post_with_catalog(
            {
                "goal": "unlisted item request",
                "budget": 100,
                "owns": "none",
                "use_case": "personal use",
                "priorities": "none",
                "must_haves": "none",
            },
            lambda query: [],
        )
        self.assertEqual(none_response.status_code, 200)
        self.assertEqual(none_response.json()["empty_reason"], "catalog_no_results")
        self.assertIn("catalog returned no", none_response.json()["message"].lower())

    def test_multiple_items_in_an_unlisted_category_stay_under_total_budget(self):
        request = StudentRequest(
            goal="camping gear",
            budget=20,
            owns=[],
            use_case="weekend hiking",
            priorities=[],
            must_haves=[],
        )
        products = [
            Product("lantern", "Camping lantern", "camping equipment", 12),
            Product("compass", "Camping compass", "camping equipment", 8),
            Product("tent", "Camping tent", "camping equipment", 45),
        ]

        picks = recommend(request, products)

        self.assertEqual({item.product.id for item in picks}, {"lantern", "compass"})
        self.assertLessEqual(sum(item.product.price for item in picks), request.budget)


if __name__ == "__main__":
    unittest.main()
