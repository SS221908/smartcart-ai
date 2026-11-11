import { test } from "node:test";
import assert from "node:assert/strict";
import { capturePayPalOrder, createPayPalOrder } from "./paypal.js";

function fakeFetch(expectedPath, payload) {
  return async (url, options) => {
    assert.ok(url.endsWith(expectedPath));
    assert.equal(options.method, "POST");
    return { ok: true, async json() { return payload; } };
  };
}

test("creates an order through the backend", async () => {
  const result = await createPayPalOrder({ items: [], budget: 100 }, fakeFetch("/api/paypal/orders", { order_id: "ORDER-1" }));
  assert.equal(result.order_id, "ORDER-1");
});

test("captures an approved order through the backend", async () => {
  const result = await capturePayPalOrder("ORDER-1", fakeFetch("/api/paypal/orders/ORDER-1/capture", { status: "COMPLETED" }));
  assert.equal(result.status, "COMPLETED");
});
