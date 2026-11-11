import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeRecommendations } from "./recommendations.js";

test("normalizes the confirmed response envelope and preserves missing product facts", () => {
  const result = normalizeRecommendations({
    recommendation_set_id: "set-1",
    budget: 300,
    recommendations: [{ name: "Demo laptop", price: "249.99" }],
  });

  assert.equal(result.budget, 300);
  assert.equal(result.recommendationSetId, "set-1");
  assert.equal(result.products[0].title, "Demo laptop");
  assert.equal(result.products[0].price, 249.99);
  assert.equal(result.products[0].merchant, null);
  assert.equal(result.products[0].rating, null);
});

test("rejects a response without recommendations", () => {
  assert.throws(() => normalizeRecommendations({ budget: 300 }), /missing recommendations/);
});

test("normalizes the teammate budget object and product aliases", () => {
  const result = normalizeRecommendations({
    demo_data: true,
    search_mode: "channel3",
    budget: { currency: "USD", budget: 300, recommended_total: 179.98, remaining: 120.02, within_budget: true },
    recommendations: [{ id: "demo-monitor-1", name: "Demo monitor", price: 89.99, image_url: "image.png", url: "https://example.test/product", source: "fictional demo" }],
  });
  assert.equal(result.budget, 300);
  assert.equal(result.recommendedTotal, 179.98);
  assert.equal(result.remaining, 120.02);
  assert.equal(result.withinBudget, true);
  assert.equal(result.demoData, true);
  assert.equal(result.products[0].title, "Demo monitor");
  assert.equal(result.products[0].productUrl, "https://example.test/product");
});
