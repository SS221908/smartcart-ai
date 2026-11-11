# PayPal SmartCart

PayPal SmartCart is a budget-aware shopping assistant for students and other cost-conscious shoppers. It combines teammate-owned recommendation and intake logic with a React shopping experience, AG Grid cart editing, server-side cart validation, and PayPal Sandbox checkout.

The application is designed around one reliable flow:

```text
Student request
  → teammate intake and recommendation logic
  → normalized product catalogue
  → product selection and comparison
  → editable AG Grid cart
  → budget dashboard
  → server-side cart validation
  → PayPal Sandbox approval and capture
  → confirmation
```

## Current architecture

The teammate runtime is loaded directly into the main FastAPI process. There is one backend port; a separate recommendation server on port `8001` is not required.

```text
React/Vite frontend       http://localhost:5173
Unified FastAPI backend   http://127.0.0.1:8000
```

The backend loads the teammate source from `smartcart-ai/` through `backend/teammate_runtime.py`.

### Repository structure

```text
frontend/
  React/Vite application
  Product catalogue UI
  AG Grid cart
  Theme and 3D scene
  PayPal checkout UI

backend/
  main.py                 Unified FastAPI application
  teammate_runtime.py     Loads teammate recommendation runtime
  cart_validation.py      Authoritative cart validation
  paypal_service.py       Server-only PayPal integration
  test_*.py               Backend tests

smartcart-ai/
  api.py                  Teammate intake and recommendation routes
  smartcart_agent.py      Intake, ranking, and budget logic
  integrations/            Channel3, Elastic, and Kernel connectors
```

## Backend routes

All routes run on port `8000`:

```text
GET  /health
GET  /api/health

POST /api/intake/start
POST /api/intake/next
POST /api/recommendations

POST /api/cart/validate

POST /api/paypal/orders
POST /api/paypal/orders/{order_id}/capture
```

The frontend calls only the unified backend. The backend invokes the teammate recommendation functions in-process.

## Frontend experience

The current interface includes:

- Student request form with goal, budget, owned equipment, use case, priorities, device details, and must-haves.
- Light/dark theme toggle.
- Glassmorphism panels and responsive layout.
- Procedural React Three Fiber showroom backdrop.
- WebGL fallback and reduced-motion support.
- Product catalogue cards instead of a technical comparison table.
- Product imagery when supplied by the API, with generated visual placeholders when absent.
- Bold price and “Why it fits” recommendation reasoning.
- Merchant names linked to product pages when available.
- AG Grid cart with editable quantities, row totals, and remove actions.
- Budget dashboard with subtotal, remaining budget, progress, and over-budget warnings.
- Explicit PayPal Sandbox checkout approval step.

The internal search mode, such as `channel3_elastic_fallback`, is retained in API data for diagnostics but is not presented as the primary shopper-facing product source. The customer-facing source is the catalog item and merchant link.

## Prerequisites

Install locally:

- Python 3.11 or newer.
- Node.js and npm.
- Git.
- A PayPal Developer account for Sandbox checkout.
- Optional: Postman for API testing.

Verify installations:

```powershell
py --version
node --version
npm --version
```

## Environment configuration

Copy `.env.example` to `.env` in the project root:

```powershell
Copy-Item .env.example .env
```

Never commit `.env`. Never place PayPal secrets in frontend `VITE_*` variables.

### Required for demo recommendations

```dotenv
SMARTCART_DEMO=true
```

Demo recommendations are fictional and must remain labeled as demo data.

### Required for real catalog recommendations

```dotenv
SMARTCART_DEMO=false
CHANNEL3_API_KEY=your-channel3-key
```

The teammate service uses Channel3 for catalog search when the key is configured.

### Required for PayPal Sandbox checkout

```dotenv
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-client-secret
```

Use a PayPal Sandbox Business account and a Sandbox Personal account for testing. Do not use live PayPal credentials.

### Optional integrations

```dotenv
ELASTICSEARCH_URL=
ELASTIC_API_KEY=
ELASTIC_INDEX=smartcart-products-v1
KERNEL_API_KEY=
```

Elastic provides optional reranking. Kernel provides optional read-only public product-page inspection. Neither is required for the core recommendation-to-checkout flow.

### Other settings

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://localhost:5173
PRODUCT_CATALOG_JSON={}
```

Recommendation responses create server-side catalog snapshots automatically. `PRODUCT_CATALOG_JSON` remains available as a fallback for direct cart-validation tests.

## Local startup

Start only one backend. The teammate API should not be started separately on port `8001`.

### Terminal 1: backend

```powershell
cd "C:\Users\pearl\OneDrive\Documents\ChatGPT\PayPal Hacks\backend"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

The response includes backend status and teammate configuration status:

```text
status
channel3_configured
elastic_configured
kernel_configured
demo_catalog_enabled
```

### Terminal 2: frontend

```powershell
cd "C:\Users\pearl\OneDrive\Documents\ChatGPT\PayPal Hacks\frontend"
npm install
npm test
npm run build
npm run dev
```

Open:

```text
http://localhost:5173
```

## Testing the recommendation flow

Test the unified backend directly:

```powershell
$body = @{
  goal = "coding setup"
  budget = 300
  owns = @("monitor", "keyboard")
  use_case = "coding for college classes"
  priorities = @("RAM", "performance", "value")
  device_details = ""
  must_haves = @()
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/recommendations `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

The response should contain:

```text
recommendations
budget
recommendation_set_id
search_mode
demo_data
requires_user_approval
```

The `recommendation_set_id` connects returned product IDs and prices to later cart validation.

## Testing the cart and budget flow

In the browser:

1. Submit a request.
2. Select products from the catalogue cards.
3. Add selected products to the cart.
4. Edit quantity directly in AG Grid.
5. Try invalid quantities such as `0`, `-1`, `1.5`, and text.
6. Remove a product.
7. Confirm row totals update.
8. Confirm subtotal updates.
9. Confirm remaining budget updates.
10. Add enough items to exceed the budget.
11. Confirm checkout is disabled or blocked when over budget.

The backend remains authoritative. Browser totals are never trusted for payment.

## Testing PayPal Sandbox checkout

1. Configure fresh Sandbox credentials in `.env`.
2. Restart the backend.
3. Submit a recommendation request.
4. Add a product with a verified product ID and price.
5. Confirm the cart is within budget.
6. Click `Approve final cart`.
7. Open the PayPal approval link.
8. Sign in with the Sandbox Personal buyer account.
9. Approve the payment.
10. Return to StudentCart.
11. Click `I approved — capture payment`.
12. Confirm the success state and PayPal order ID.

The PayPal client ID and secret remain server-side. The browser receives only the order ID and approval URL.

## Automated tests

Frontend tests:

```powershell
cd frontend
npm test
```

The current frontend suite covers:

- Recommendation normalization.
- Teammate budget-object normalization.
- Product aliases.
- PayPal API request handling.
- Add/remove cart behavior.
- Quantity validation.
- Subtotal calculations.
- Budget summaries.
- Cross-layer cart validation payloads.

Backend tests:

```powershell
cd backend
..\.venv\Scripts\Activate.ps1
py -m unittest test_cart_validation.py test_paypal_service.py
python -m compileall .
```

## Troubleshooting

### Backend health works but recommendations fail

Check that the teammate runtime is configured:

```dotenv
SMARTCART_DEMO=true
```

For real catalog results, check `CHANNEL3_API_KEY`.

### `/` returns 404

This is normal. Use:

```text
/health
/api/health
/docs
/api/recommendations
```

### PayPal capture returns 502

Restart the backend after changing credentials and create a fresh PayPal order. The backend now returns PayPal error codes such as `ORDER_NOT_APPROVED` or `ORDER_ALREADY_CAPTURED`.

### Port 8001 is still running

Stop the old teammate Uvicorn process. The unified application should run only on port `8000`.

### AG Grid or 3D dependencies are missing

Run:

```powershell
cd frontend
npm install
```

Then rebuild:

```powershell
npm run build
```

## Security rules

- Never commit `.env`.
- Never expose PayPal client secrets in React code.
- Never trust browser prices or totals.
- Never let recommendation logic create or capture PayPal orders.
- Treat demo products as fictional.
- Revalidate product IDs, prices, currencies, and quantities on the backend.
- Rotate any credential that has been exposed in a screenshot, commit, log, or chat.
