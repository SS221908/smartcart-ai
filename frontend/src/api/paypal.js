import { getApiBaseUrl } from "./recommendations.js";

async function postJson(path, body, fetchImpl = fetch) {
  const response = await fetchImpl(`${getApiBaseUrl()}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data;
  try { data = await response.json(); } catch { throw new Error("The payment service returned an invalid response."); }
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Payment request failed (${response.status})`);
  return data;
}

export function createPayPalOrder(payload, fetchImpl = fetch) { return postJson("/api/paypal/orders", payload, fetchImpl); }
export function capturePayPalOrder(orderId, fetchImpl = fetch) { return postJson(`/api/paypal/orders/${encodeURIComponent(orderId)}/capture`, {}, fetchImpl); }
