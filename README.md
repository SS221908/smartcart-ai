# SmartCart Person 1 AI and Recommendations

This folder contains the AI conversation handoff, student intake, catalog search, transparent budget scoring, and optional sponsor connectors. Person 2 can call the HTTP routes in `api.py` from the React app and use the returned product IDs and URLs in the cart.

## What is implemented

- A student intake that collects budget, existing equipment, intended use, top priorities, and must-have requirements, one missing item at a time.
- If a student owns a laptop and prioritizes RAM or graphics, intake asks about the device and upgrade support; it does not assume laptop internals can be upgraded.
- Channel3 structured product search with an availability filter and a per-item max-price filter.
- Channel3's conversational shopping agent token and turn endpoints for AI replies and refinements.
- Local ranking with explicit reasons, exclusion of already-owned categories, current USD prices, and a hard total-budget cap. The recommender builds a small set with no duplicate categories.
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

## API contract for Person 2

### 1. Ask the next intake question

Start with the student's natural-language request using `POST /api/intake/start`:

```json
{"message": "Help me build a coding setup under $300"}
```

This extracts the obvious goal, budget, and use case, then asks for missing information. It deliberately asks what equipment the student already owns instead of guessing.

`POST /api/intake/next`

```json
{
  "goal": "coding setup",
  "budget": 300,
  "owns": ["laptop", "monitor"],
  "use_case": "basic coding",
  "priorities": ["storage", "value"],
  "device_details": "not sure",
  "must_haves": []
}
```

If a field is unanswered, the response includes `status: "needs_input"`, the field name, and the question to show. Represent an explicit answer of “none” as an empty list; `null` means it is still unanswered.

### 2. Get budget-safe product recommendations

`POST /api/recommendations`

Send the same student fields. It returns product name, current price, merchant, image, product URL, fit explanation, and budget totals. The selected items are guaranteed to stay within the requested total budget based on the returned prices. Reconfirm price and availability before checkout.

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
