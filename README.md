# SmartCart AI and Recommendations

This folder contains the shopping intake, catalog search, budget-aware product ranking, and optional sponsor connectors. Shoppers can enter any natural-language item, category, bundle, or shopping goal; there is no supported-category allowlist. The category examples in this README only illustrate the request format. The frontend can call the HTTP routes in `api.py` and use returned product IDs and URLs in the cart.

## What is implemented

- An adaptive shopper intake that collects budget, items already owned or ingredients on hand, intended use or occasion, priorities, and must-have requirements.
- Channel3 structured product search with an availability filter and a per-item max-price filter.
- Category-agnostic free-text search. The API retries with a broader goal/use-case query if the detailed search returns no budget-eligible recommendations, and returns an explanation when no catalog item qualifies.
- Channel3's conversational shopping agent token and turn endpoints for AI replies and refinements.
- Local ranking with explicit reasons, exclusion of already-owned items, current USD prices, and a hard total-budget cap. Multiple items from the same category are allowed for requests such as grocery lists.
- Optional Elastic hybrid search: Channel3 products are indexed and reranked with lexical + semantic retrieval using reciprocal rank fusion. If Elastic is unavailable, direct Channel3 results still work.
- Optional Kernel browser inspection of a user-selected public HTTPS product page. It only reads the page and returns a short summary; it does not sign in, click, or buy.
- APIMatic PayPal Context Plugin setup notes. APIMatic is a coding-agent plugin that helps Person 2 build the PayPal integration accurately; it is not a runtime AI library.

Channel3 search results provide product and offer records. The product cards in the app should come from `/api/recommendations`, not arbitrary product claims in chat text. The chat response can explain and refine options; the API then returns catalog-backed product data and computes the budget again.

## Start locally

1. Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install the dependencies in `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```
3. Copy `.env.example` to `.env` and add API keys. Never commit `.env`.
4. Start the service:

```bash
uvicorn api:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health`.

With no API keys, set `SMARTCART_DEMO=true` for fictional sample items. Demo product names and prices are placeholders and must not be represented as real listings. Real Channel3 catalog search requires `CHANNEL3_API_KEY`.

## Run backend tests

The focused tests mock Channel3, so they do not need a real API key or a network call:

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

## API contract for Person 2

### 1. Ask the next intake question

Start with the shopper's natural-language request using `POST /api/intake/start`:

```json
{"message": "Help me plan groceries for weekday lunches under $80"}
```

This extracts the obvious goal and budget, then asks for missing information. The questions adapt to general shopping; for groceries, list ingredients already on hand, and for clothing, include relevant size or fit details.

`POST /api/intake/next`

```json
{
  "goal": "groceries for weekday lunches",
  "budget": 80,
  "owns": ["rice", "olive oil"],
  "use_case": "weekday lunches",
  "priorities": ["vegetarian", "value"],
  "device_details": null,
  "must_haves": ["vegetarian"]
}
```

For a clothing request, the same fields can describe a wedding outfit:

```json
{
  "goal": "wedding dress",
  "budget": 500,
  "owns": [],
  "use_case": "my wedding",
  "priorities": ["style", "comfort", "value"],
  "device_details": "size 8, ivory",
  "must_haves": ["floor length"]
}
```

If a field is unanswered, the response includes `status: "needs_input"`, the field name, and the question to show. Represent an explicit answer of “none” as an empty list; `null` means it is still unanswered. In Swagger, replace the sample word `string` with a real value or `[]`; the API ignores those placeholder strings if they are submitted by mistake.

### 2. Get budget-safe product recommendations

`POST /api/recommendations`

Send the same shopper fields. `owns`, `priorities`, and `must_haves` each accept an array or comma/newline-separated text. It returns product name, current price, merchant, image, product URL, fit explanation, and budget totals. Returned items are selected from the catalog and fit within the requested total budget based on the returned prices. Reconfirm price and availability before checkout.

### 3. Use Channel3's AI agent

- `POST /api/channel3/token` returns a short-lived client token. The Channel3 API key stays on the server.
- `POST /api/channel3/turn` takes `client_token`, `message`, and an optional `conversation_id`; it returns assistant text and the conversation ID to send on the next turn.

After intake is complete, give the agent the goal, budget, owned items, priorities, device details, and required specifications in the optional `profile` field. Use `/api/recommendations` for the final structured product cards and hard budget check.

### 4. Optional Kernel page review

`POST /api/kernel/inspect-product` accepts a user-selected public HTTPS product URL and returns a page title, description, and short visible-text sample. Treat those details as unverified; catalog prices from Channel3 remain the product source of record.

## Partner setup notes

- **Channel3:** Set `CHANNEL3_API_KEY`. Search uses `/v1/search`, `x-api-key`, price and availability filters. Its conversational agent uses a server-created client token and conversation turns.
- **Elastic:** Set `ELASTICSEARCH_URL` and `ELASTIC_API_KEY`. The service creates a `semantic_text` field and performs reciprocal-rank-fusion over lexical and semantic results. This requires a compatible Elastic deployment and inference endpoint.
- **Kernel:** Set `KERNEL_API_KEY`; install the optional Python packages from `requirements.txt`. The inspector is called only when a user wants extra information from a product page.
- **APIMatic:** See `APIMATIC_SETUP.md`. Install its PayPal Context Plugin in the coding-agent environment before Person 2 implements PayPal orders.

The Channel3 and Kernel keys must remain server-side. The model can explain products, but prices, available items, budget arithmetic, and checkout approval remain explicit application data and rules.

## Official integration references

- [Channel3 product search](https://channel3.ai/docs/guides/make-a-search)
- [Channel3 conversational agent quickstart](https://channel3.ai/docs/conversations/quickstart)
- [Elastic hybrid search with semantic text](https://www.elastic.co/docs/solutions/search/hybrid-semantic-text)
- [Kernel browser documentation](https://www.kernel.sh/docs/)
- [APIMatic PayPal Context Plugin](https://context.apimatic.io/plugins/paypal/)
