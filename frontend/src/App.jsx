import { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import SceneBackdrop from "./components/SceneBackdrop.jsx";
import { fetchRecommendations, normalizeRecommendations } from "./api/recommendations.js";
import { capturePayPalOrder, createPayPalOrder } from "./api/paypal.js";
import { addProducts, buildCartValidationPayload, calculateBudgetSummary, calculateSubtotal, productKey, removeProduct, updateQuantity } from "./cart/cart.js";

const initialForm = { goal: "coding setup", budget: "300", owns: "monitor, keyboard", use_case: "coding for college classes", priorities: "RAM, performance, value", device_details: "", must_haves: "" };

export default function App() {
  const [theme, setTheme] = useState("light");
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [cart, setCart] = useState([]);
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [payment, setPayment] = useState({ status: "idle", orderId: "", approvalUrl: "", error: "" });

  function updateField(event) { setForm((current) => ({ ...current, [event.target.name]: event.target.value })); }

  async function handleSubmit(event) {
    event.preventDefault();
    const budget = Number(form.budget);
    if (!form.goal.trim() || !Number.isFinite(budget) || budget <= 0) {
      setError("Enter a goal and a budget greater than zero.");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setError("");
    try {
      const data = await fetchRecommendations({ goal: form.goal.trim(), budget, owns: splitList(form.owns), use_case: form.use_case.trim(), priorities: splitList(form.priorities), device_details: form.device_details.trim() || null, must_haves: splitList(form.must_haves) });
      setResult(normalizeRecommendations(data));
      setCart([]);
      setSelectedProducts([]);
      setPayment({ status: "idle", orderId: "", approvalUrl: "", error: "" });
      setStatus("success");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  }

  const subtotal = useMemo(() => calculateSubtotal(cart), [cart]);
  const budget = Number(result?.budget ?? form.budget);
  const budgetSummary = useMemo(() => calculateBudgetSummary(budget, subtotal), [budget, subtotal]);
  const focus = cart.length ? "cart" : result ? "recommendations" : "idle";

  async function handleCreateOrder() {
    if (cart.length === 0) return setPayment({ status: "error", orderId: "", approvalUrl: "", error: "Add at least one item before checkout." });
    if (budgetSummary.overBudget) return setPayment({ status: "error", orderId: "", approvalUrl: "", error: "Reduce the cart so it is within budget before checkout." });
    if (cart.some((product) => !product.id || product.price === null || !product.currency)) return setPayment({ status: "error", orderId: "", approvalUrl: "", error: "Checkout requires verified product IDs and prices." });
    setPayment({ status: "loading", orderId: "", approvalUrl: "", error: "" });
    try {
      const order = await createPayPalOrder(buildCartValidationPayload(cart, budget, result?.recommendationSetId));
      setPayment({ status: "approval", orderId: order.order_id, approvalUrl: order.approval_url, error: "" });
    } catch (paymentError) {
      setPayment({ status: "error", orderId: "", approvalUrl: "", error: paymentError.message });
    }
  }

  async function handleCapture() {
    setPayment((current) => ({ ...current, status: "capturing", error: "" }));
    try {
      const capture = await capturePayPalOrder(payment.orderId);
      if (capture.status !== "COMPLETED") throw new Error(`PayPal returned status: ${capture.status}`);
      setPayment((current) => ({ ...current, status: "complete", error: "" }));
    } catch (paymentError) {
      setPayment((current) => ({ ...current, status: "error", error: paymentError.message }));
    }
  }

  return <div className={`app-shell theme-${theme}`}>
    <SceneBackdrop theme={theme} productCount={result?.products.length ?? 0} focus={focus} />
    <main className="shell">
      <header className="topbar glass-panel">
        <div className="brand-lockup"><span className="brand-mark" aria-label="PayPal logo"><svg viewBox="0 0 42 32" role="img" aria-hidden="true"><path className="paypal-p paypal-p-back" d="M14 3h10.5c7.3 0 11.3 3.5 10 9.2-1.1 5-5.1 7.8-11.4 7.8h-4.4l-1.7 8H9.8L14 3Z" /><path className="paypal-p paypal-p-front" d="M10.2 3h10.5c7.3 0 11.3 3.5 10 9.2-1.1 5-5.1 7.8-11.4 7.8h-4.4l-1.7 8H6L10.2 3Z" /></svg></span><span>PayPal SmartCart</span></div>
        <button type="button" className="theme-toggle" onClick={() => setTheme((current) => current === "light" ? "dark" : "light")} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}><span>{theme === "light" ? "☾" : "☀"}</span>{theme === "light" ? "Dark mode" : "Light mode"}</button>
      </header>

      <section className="hero glass-panel"><div><p className="eyebrow">AI-powered student shopping</p><h1>Build a smarter cart for your budget.</h1><p className="intro">Describe what you need. SmartCart turns your priorities into catalog-backed picks you can compare before you spend.</p></div><span className="demo-badge">{result?.demoData ? "Demo catalogue" : "Catalog-backed"}</span></section>

      <section className="panel request-panel glass-panel">
        <div className="section-heading"><div><p className="eyebrow">Step 1</p><h2>Describe your setup</h2></div><span className="status-label">{status === "loading" ? "Thinking…" : "Ready"}</span></div>
        <form onSubmit={handleSubmit}>
          <label>What are you trying to buy?<input name="goal" value={form.goal} onChange={updateField} required /></label>
          <div className="form-grid"><label>Budget (USD)<input name="budget" type="number" min="1" step="0.01" value={form.budget} onChange={updateField} required /></label><label>Already own<input name="owns" value={form.owns} onChange={updateField} placeholder="monitor, keyboard" /></label></div>
          <label>Use case<input name="use_case" value={form.use_case} onChange={updateField} /></label>
          <label>Device details (optional)<input name="device_details" value={form.device_details} onChange={updateField} placeholder="laptop model or upgrade details" /></label>
          <div className="form-grid"><label>Priorities<input name="priorities" value={form.priorities} onChange={updateField} placeholder="performance, value" /></label><label>Must-haves<input name="must_haves" value={form.must_haves} onChange={updateField} placeholder="USB-C, 16GB RAM" /></label></div>
          <button className="primary-button" type="submit" disabled={status === "loading"}>{status === "loading" ? "Finding smart matches…" : "Find smart matches"}</button>
        </form>
        {status === "error" && <p className="message error" role="alert">{error}</p>}
      </section>

      {status === "success" && result && <RecommendationResults result={result} selectedProducts={selectedProducts} setSelectedProducts={setSelectedProducts} onAdd={() => setCart((current) => addProducts(current, selectedProducts))} />}
      {status === "success" && result && <BudgetDashboard summary={budgetSummary} />}
      {status === "success" && result && <CartSection cart={cart} setCart={setCart} subtotal={subtotal} remainingBudget={budgetSummary.remaining} />}
      {status === "success" && result && <CheckoutPanel cart={cart} summary={budgetSummary} payment={payment} onCreateOrder={handleCreateOrder} onCapture={handleCapture} onCancel={() => setPayment({ status: "cancelled", orderId: "", approvalUrl: "", error: "" })} />}
    </main>
  </div>;
}

function ProductVisual({ product, index }) {
  if (product.imageUrl) return <img className="product-image" src={product.imageUrl} alt="" loading="lazy" />;
  return <div className={`product-art product-art-${index % 3}`} aria-hidden="true"><span>{product.category?.slice(0, 1).toUpperCase() || "✦"}</span><i /></div>;
}

function RecommendationResults({ result, selectedProducts, setSelectedProducts, onAdd }) {
  function toggleProduct(product) {
    const key = productKey(product);
    setSelectedProducts((current) => current.some((item) => productKey(item) === key) ? current.filter((item) => productKey(item) !== key) : [...current, product]);
  }

  return <section className="results catalogue-section"><div className="section-heading"><div><p className="eyebrow">Step 2</p><h2>Curated for your setup</h2><p className="section-subtitle">Compare visual product cards, then choose what belongs in your cart.</p></div><span className="budget-pill">Budget: ${Number(result.budget ?? 0).toFixed(2)}</span></div>
    {result.products.length === 0 ? <p className="panel message">No recommendations matched this request. Try broadening your requirements.</p> : <><div className="catalogue-grid">{result.products.map((product, index) => <article className={`product-card glass-panel ${selectedProducts.some((item) => productKey(item) === productKey(product)) ? "product-card-selected" : ""}`} key={product.id ?? product.rowKey}>
      <div className="product-card-top"><span className="catalogue-chip">{product.source === "fictional demo" ? "Demo item" : "Catalog item"}</span><button type="button" className="select-product" onClick={() => toggleProduct(product)} aria-pressed={selectedProducts.some((item) => productKey(item) === productKey(product))}>{selectedProducts.some((item) => productKey(item) === productKey(product)) ? "Selected" : "Select"}</button></div>
      <ProductVisual product={product} index={index} />
      <div className="product-card-body"><p className="product-category">{product.category || "Recommended pick"}</p><h3>{product.title ?? "Untitled recommendation"}</h3><div className="product-price">{product.price === null ? "Price unavailable" : `$${product.price.toFixed(2)} ${product.currency}`}</div>{product.reason && <p className="fit-reason"><strong>Why it fits</strong><span>{product.reason}</span></p>}<div className="merchant-row">{product.merchant && product.productUrl ? <a href={product.productUrl} target="_blank" rel="noreferrer">{product.merchant} <span>↗</span></a> : <span>Merchant unavailable</span>}</div></div>
    </article>)}</div><div className="catalogue-actions"><span>{selectedProducts.length} selected for cart</span><button className="primary-button" type="button" onClick={onAdd} disabled={selectedProducts.length === 0}>Add selected to cart</button></div></>}
  </section>;
}

function BudgetDashboard({ summary }) {
  return <section className={`budget-dashboard panel glass-panel ${summary.overBudget ? "budget-dashboard-over" : ""}`} aria-label="Budget summary"><div className="budget-dashboard-heading"><div><p className="eyebrow">Budget review</p><h2>{summary.overBudget ? "Adjust your cart before checkout" : "You’re within budget"}</h2></div><strong className="budget-total">${summary.budget.toFixed(2)}</strong></div><div className="budget-metrics"><div><span>Requested budget</span><strong>${summary.budget.toFixed(2)}</strong></div><div><span>Cart subtotal</span><strong>${summary.subtotal.toFixed(2)}</strong></div><div><span>{summary.overBudget ? "Over budget by" : "Remaining"}</span><strong>${Math.abs(summary.remaining).toFixed(2)}</strong></div></div><div className="budget-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={summary.percentUsed} aria-label={`${summary.percentUsed.toFixed(0)} percent of budget used`}><span style={{ width: `${summary.percentUsed}%` }} /></div><p className={summary.overBudget ? "message error" : "message"}>{summary.overBudget ? "Your cart is over the requested budget. Remove items or reduce quantities before checkout." : `${summary.percentUsed.toFixed(0)}% of your budget is currently allocated.`}</p></section>;
}

function CartSection({ cart, setCart, subtotal, remainingBudget }) {
  const columns = useMemo(() => [
    { field: "title", headerName: "Product", flex: 2, minWidth: 220, valueFormatter: ({ value }) => value ?? "Untitled recommendation" },
    { field: "price", headerName: "Price", width: 130, valueFormatter: ({ value, data }) => value === null ? "Unavailable" : `$${Number(value).toFixed(2)} ${data.currency}` },
    { field: "quantity", headerName: "Quantity", width: 130, editable: true, valueParser: ({ newValue }) => Number(newValue), onCellValueChanged: (event) => { const next = Number(event.newValue); const key = productKey(event.data); if (!Number.isInteger(next) || next < 1) { event.node.setDataValue("quantity", event.oldValue); return; } setCart((current) => updateQuantity(current, key, next)); } },
    { headerName: "Row total", width: 140, valueGetter: ({ data }) => Number.isFinite(Number(data.price)) ? Number(data.price) * Number(data.quantity) : null, valueFormatter: ({ value }) => value === null ? "Unavailable" : `$${value.toFixed(2)}` },
    { headerName: "Action", width: 115, cellRenderer: ({ data }) => <button type="button" className="remove-button" onClick={() => setCart((current) => removeProduct(current, productKey(data)))}>Remove</button> },
  ], [setCart]);
  return <section className="results cart-section"><div className="section-heading"><div><p className="eyebrow">Step 3</p><h2>Shape your cart</h2><p className="section-subtitle">Edit quantities, remove items, and watch your total recalculate.</p></div><span className={remainingBudget < 0 ? "budget-pill over" : "budget-pill"}>{remainingBudget < 0 ? "Over budget" : "Remaining"}: ${Math.abs(remainingBudget).toFixed(2)}</span></div><div className="cart-card glass-panel">{cart.length === 0 ? <div className="empty-cart"><span className="empty-cart-icon">＋</span><h3>Your cart is ready for a pick</h3><p>Select one or more recommendations above to begin.</p></div> : <><div className="cart-toolbar"><span>{cart.length} item{cart.length === 1 ? "" : "s"}</span><strong>Subtotal ${subtotal.toFixed(2)}</strong></div><div className="grid-shell ag-theme-quartz"><AgGridReact rowData={cart} columnDefs={columns} getRowId={(params) => String(productKey(params.data))} domLayout="autoHeight" rowHeight={72} headerHeight={58} /></div></>}</div></section>;
}

function CheckoutPanel({ cart, summary, payment, onCreateOrder, onCapture, onCancel }) {
  const isBlocked = cart.length === 0 || summary.overBudget || cart.some((product) => !product.id || product.price === null);
  return <section className="panel checkout-panel glass-panel" aria-label="PayPal Sandbox checkout"><div className="section-heading"><div><p className="eyebrow">Step 4</p><h2>Approve checkout</h2></div><span className="paypal-badge">PayPal Sandbox</span></div><p className="message">The server will validate the final cart again before creating a PayPal order.</p>{payment.status === "complete" ? <div className="payment-success" role="status"><h3>Payment complete</h3><p>Your PayPal Sandbox order was captured successfully.</p><strong>Order ID: {payment.orderId}</strong></div> : <><div className="checkout-total"><span>Final total</span><strong>${summary.subtotal.toFixed(2)} USD</strong></div>{payment.status === "idle" && <button className="primary-button" type="button" onClick={onCreateOrder} disabled={isBlocked}>Approve final cart</button>}{payment.status === "loading" && <p className="message">Creating your PayPal Sandbox order…</p>}{payment.status === "approval" && <div className="approval-actions"><a className="paypal-link" href={payment.approvalUrl} target="_blank" rel="noreferrer">Open PayPal approval</a><button className="primary-button" type="button" onClick={onCapture} disabled={!payment.orderId}>I approved — capture payment</button><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button></div>}{payment.status === "capturing" && <p className="message">Capturing the approved Sandbox payment…</p>}{payment.status === "cancelled" && <p className="message">Payment approval was cancelled. Your cart was not charged.</p>}{payment.status === "error" && <p className="message error" role="alert">{payment.error}</p>}</>}</section>;
}

function splitList(value) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
