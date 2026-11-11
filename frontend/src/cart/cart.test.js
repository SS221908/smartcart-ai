import { test } from "node:test";
import assert from "node:assert/strict";
import { addProducts, buildCartValidationPayload, calculateBudgetSummary, calculateSubtotal, removeProduct, updateQuantity } from "./cart.js";

const laptop = { id: "laptop-1", price: 100, quantity: 1 };
const stand = { id: "stand-1", price: 25, quantity: 1 };

test("adds products without duplicating existing cart items", () => {
  const cart = addProducts([], [laptop, stand]);
  assert.equal(cart.length, 2);
  assert.equal(addProducts(cart, [laptop]).length, 2);
});

test("updates and removes products", () => {
  const cart = updateQuantity([laptop, stand], "laptop-1", 2);
  assert.equal(cart[0].quantity, 2);
  assert.equal(updateQuantity(cart, "laptop-1", 0)[0].quantity, 2);
  assert.deepEqual(removeProduct(cart, "stand-1"), [{ ...laptop, quantity: 2 }]);
});

test("calculates subtotal from price times quantity", () => {
  assert.equal(calculateSubtotal([{ ...laptop, quantity: 2 }, stand]), 225);
});

test("calculates under-budget and over-budget summaries", () => {
  assert.deepEqual(calculateBudgetSummary(300, 225), {
    budget: 300, subtotal: 225, remaining: 75, overBudget: false, percentUsed: 75,
  });
  assert.deepEqual(calculateBudgetSummary(300, 350), {
    budget: 300, subtotal: 350, remaining: -50, overBudget: true, percentUsed: 100,
  });
});

test("builds a cross-layer validation payload without changing client totals", () => {
  const cart = [{ id: "laptop-1", price: 100, currency: "USD", quantity: 2 }];
  assert.deepEqual(buildCartValidationPayload(cart, 300, "set-1"), {
    items: [{ id: "laptop-1", price: 100, currency: "USD", quantity: 2 }],
    budget: 300,
    client_total: 200,
    recommendation_set_id: "set-1",
  });
});
