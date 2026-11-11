const defaultApiBaseUrl = "http://127.0.0.1:8000";

export function getApiBaseUrl() {
  const configuredUrl = import.meta.env?.VITE_API_BASE_URL;
  return (configuredUrl || defaultApiBaseUrl).replace(/\/$/, "");
}

export async function fetchRecommendations(request, fetchImpl = fetch) {
  const response = await fetchImpl(`${getApiBaseUrl()}/api/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The recommendation service returned an invalid response.");
  }

  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? `: ${data.detail}` : "";
    throw new Error(`Recommendation request failed (${response.status})${detail}`);
  }

  return data;
}

export function normalizeRecommendations(data) {
  if (!data || !Array.isArray(data.recommendations)) {
    throw new Error("The recommendation response is missing recommendations.");
  }

  const budgetSummary = data.budget && typeof data.budget === "object"
    ? data.budget
    : { budget: data.budget ?? null };
  return {
    recommendationSetId: data.recommendation_set_id ?? null,
    budget: toNumberOrNull(budgetSummary.budget),
    recommendedTotal: toNumberOrNull(budgetSummary.recommended_total),
    remaining: toNumberOrNull(budgetSummary.remaining),
    withinBudget: budgetSummary.within_budget ?? null,
    demoData: Boolean(data.demo_data),
    searchMode: data.search_mode ?? null,
    products: data.recommendations.map((product, index) => normalizeProduct(product, index)),
  };
}

function normalizeProduct(product, index) {
  const source = product && typeof product === "object" ? product : {};
  return {
    // These aliases are defensive transport mappings; absent values remain null.
    id: source.id ?? source.product_id ?? null,
    title: source.title ?? source.name ?? null,
    description: source.description ?? null,
    price: toNumberOrNull(source.price),
    currency: source.currency ?? "USD",
    imageUrl: source.imageUrl ?? source.image_url ?? null,
    productUrl: source.productUrl ?? source.product_url ?? source.url ?? null,
    merchant: source.merchant ?? null,
    rating: toNumberOrNull(source.rating),
    reason: source.reason ?? source.recommendation_reason ?? null,
    category: source.category ?? null,
    source: source.source ?? null,
    pros: Array.isArray(source.pros) ? source.pros : [],
    cons: Array.isArray(source.cons) ? source.cons : [],
    quantity: 1,
    rowKey: source.id ?? source.product_id ?? `recommendation-${index + 1}`,
    raw: product,
  };
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
