export function addProducts(cart, products) {
  const next = [...cart];
  for (const product of products) {
    const key = productKey(product);
    if (next.some((item) => productKey(item) === key)) continue;
    next.push({ ...product, quantity: 1 });
  }
  return next;
}

export function removeProduct(cart, productKeyToRemove) {
  return cart.filter((product) => productKey(product) !== productKeyToRemove);
}

export function updateQuantity(cart, productKeyToUpdate, quantity) {
  if (!Number.isInteger(quantity) || quantity < 1) return cart;
  return cart.map((product) => (
    productKey(product) === productKeyToUpdate ? { ...product, quantity } : product
  ));
}

export function calculateSubtotal(cart) {
  return cart.reduce((total, product) => {
    const price = Number(product.price);
    const quantity = Number(product.quantity);
    return Number.isFinite(price) && Number.isFinite(quantity) ? total + price * quantity : total;
  }, 0);
}

export function calculateBudgetSummary(budget, subtotal) {
  const requestedBudget = Number(budget);
  const cartSubtotal = Number(subtotal);
  const safeBudget = Number.isFinite(requestedBudget) ? requestedBudget : 0;
  const safeSubtotal = Number.isFinite(cartSubtotal) ? cartSubtotal : 0;
  return {
    budget: safeBudget,
    subtotal: safeSubtotal,
    remaining: safeBudget - safeSubtotal,
    overBudget: safeSubtotal > safeBudget,
    percentUsed: safeBudget > 0 ? Math.min((safeSubtotal / safeBudget) * 100, 100) : 0,
  };
}

export function buildCartValidationPayload(cart, budget, recommendationSetId = null) {
  return {
    items: cart.map((product) => ({
      id: product.id,
      price: product.price,
      currency: product.currency,
      quantity: product.quantity,
    })),
    budget,
    client_total: calculateSubtotal(cart),
    recommendation_set_id: recommendationSetId,
  };
}

export function productKey(product) {
  return product.id ?? product.rowKey;
}
