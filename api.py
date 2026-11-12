"""HTTP interface for Person 1's SmartCart AI/recommendation work.

Run with: uvicorn api:app --reload --port 8000
"""

import os
import json
import re
from fastapi.middleware.cors import CORSMiddleware
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from integrations.channel3 import Channel3Client, Channel3Error
from integrations.elastic_search import ElasticCatalogSearch, ElasticError
from integrations.kernel_inspector import KernelInspectorError, inspect_product_page
from smartcart_agent import (
    Product, StudentRequest, build_budget_summary, demo_catalog, next_question,
    parse_initial_message, product_to_dict, recommend, request_to_search_query,
)

load_dotenv()

app = FastAPI(title="SmartCart AI", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_INSTRUCTIONS = """You are SmartCart, a helpful shopping assistant for any shopper-entered product, category, multi-item bundle, or shopping goal. There is no fixed list of supported categories. Ask focused follow-up questions about budget, items already owned or materials already on hand, intended use or occasion, priorities, and non-negotiable requirements. Adapt questions to the request and never assume a particular kind of product. Explain tradeoffs in plain language. Treat catalog results and prices supplied by the app as the source of truth; never invent specifications, prices, availability, claims, or product links. The recommendation service enforces the budget and returns the only product cards the UI should show. Never claim a purchase was made and never initiate checkout. The user must review and explicitly approve the cart."""


class IntakePayload(BaseModel):
    goal: str = Field(default="shopping request", min_length=2, max_length=300, description="What the shopper wants to buy, in their own words; any product category is supported.")
    budget: float | None = Field(default=None, gt=0, le=100000, description="Maximum total spend in USD.")
    owns: str | list[str] | None = Field(default=None, description="Items already owned or materials already on hand. Accepts an array or comma/newline-separated text; use [] or 'none' if nothing applies.")
    use_case: str | None = Field(default=None, max_length=300, description="Intended use, event, meal plan, or other shopping context.")
    priorities: str | list[str] | None = Field(default=None, description="Preferences. Accepts an array or comma/newline-separated text; use [] or 'none' if nothing applies.")
    device_details: str | None = Field(default=None, max_length=300, description="Optional compatibility, size, dietary, color, or measurement details.")
    must_haves: str | list[str] | None = Field(default=None, description="Non-negotiable requirements. Accepts an array or comma/newline-separated text; use [] or 'none' if nothing applies.")


class RecommendationPayload(IntakePayload):
    user_id: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=20, ge=1, le=50)


class AgentTurnPayload(BaseModel):
    client_token: str = Field(min_length=8, max_length=1000)
    message: str = Field(min_length=1, max_length=3000)
    conversation_id: str | None = Field(default=None, max_length=200)
    profile: IntakePayload | None = None


class ProductPagePayload(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class IntakeStartPayload(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


def _student_request(payload: IntakePayload) -> StudentRequest:
    """Convert API values while ignoring Swagger's literal placeholder examples."""
    empty_text = {"", "string", "null", "undefined", "n/a", "not applicable", "not sure", "unknown", "none", "nothing"}

    def clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned.lower() in empty_text:
            return None
        return cleaned

    def clean_list(values: str | list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if isinstance(values, str):
            values = [values]
        cleaned = [
            part.strip()
            for item in values
            for part in re.split(r"[,;\n]", item)
            if part.strip().lower() not in empty_text
        ]
        if cleaned and all(item.lower() in {"no", "none", "nothing", "nothing else", "no requirements", "not applicable"} for item in cleaned):
            return []
        return cleaned

    return StudentRequest(
        goal=clean_text(payload.goal) or "shopping request", budget=payload.budget,
        owns=clean_list(payload.owns), use_case=clean_text(payload.use_case),
        priorities=clean_list(payload.priorities), device_details=clean_text(payload.device_details),
        must_haves=clean_list(payload.must_haves),
    )


@app.get("/health")
def health() -> dict[str, Any]:
    channel3 = Channel3Client()
    elastic = ElasticCatalogSearch()
    return {
        "status": "ok",
        "channel3_configured": channel3.configured,
        "elastic_configured": elastic.configured,
        "kernel_configured": bool(os.getenv("KERNEL_API_KEY")),
        "demo_catalog_enabled": os.getenv("SMARTCART_DEMO", "false").lower() == "true",
    }


@app.post("/api/intake/next")
def intake_next(payload: IntakePayload) -> dict[str, str | None]:
    """Return the next required clarification or mark the profile ready."""
    return next_question(_student_request(payload))


@app.post("/api/intake/start")
def intake_start(payload: IntakeStartPayload) -> dict[str, Any]:
    """Parse the obvious first-turn goal/budget, then return the next question."""
    request = parse_initial_message(payload.message)
    profile = {
        "goal": request.goal,
        "budget": request.budget,
        "owns": request.owns,
        "use_case": request.use_case,
        "priorities": request.priorities,
        "device_details": request.device_details,
        "must_haves": request.must_haves,
    }
    return {"profile": profile, **next_question(request)}


@app.post("/api/recommendations")
def recommendations(payload: RecommendationPayload) -> dict[str, Any]:
    """Fetch real products, optionally rerank with Elastic, and enforce budget."""
    request = _student_request(payload)
    intake = next_question(request)
    if intake["status"] != "ready":
        raise HTTPException(status_code=422, detail={"message": "Complete the shopping details first.", **intake})

    channel3 = Channel3Client()
    demo_mode = os.getenv("SMARTCART_DEMO", "false").lower() == "true"
    queries_tried: list[str] = []
    products: list[Product] = []
    if channel3.configured:
        try:
            # Start with the full request. If search or local filtering finds no
            # usable products, retry using only the free-text goal and context.
            # This is category-agnostic and keeps price/availability filters.
            query_options = [
                request_to_search_query(request),
                request_to_search_query(request, include_preferences=False),
            ]
            products_by_key: dict[str, Product] = {}
            for query in dict.fromkeys(q for q in query_options if q):
                queries_tried.append(query)
                found = channel3.search_products(
                    query, request.budget or 0,
                    limit=payload.limit, user_id=payload.user_id,
                )
                for product in found:
                    key = product.id or f"{product.name}|{product.brand}|{product.price}|{product.merchant}"
                    products_by_key[key] = product
                products = list(products_by_key.values())
                if recommend(request, products):
                    break
        except Channel3Error as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    elif demo_mode:
        products = demo_catalog()
    else:
        raise HTTPException(status_code=503, detail="Set CHANNEL3_API_KEY, or set SMARTCART_DEMO=true for fictional demo data.")

    search_mode = "channel3"
    elastic = ElasticCatalogSearch()
    if elastic.configured and products:
        try:
            query = queries_tried[-1] if queries_tried else request_to_search_query(request)
            ranked_ids = elastic.rerank(query, products, limit=len(products))
            order = {product_id: position for position, product_id in enumerate(ranked_ids)}
            products.sort(key=lambda p: (order.get(p.id, len(order)), p.price))
            search_mode = "channel3+elastic_hybrid_rrf"
        except ElasticError:
            # Catalog results remain usable if optional semantic search is unavailable.
            search_mode = "channel3_elastic_fallback"

    recs = recommend(request, products)
    empty_reason = None
    if not recs:
        if not products:
            empty_reason = "catalog_no_results"
            message = "The catalog returned no in-stock products for this search and budget. Try broader search words or adjust the budget."
        else:
            empty_reason = "no_eligible_products"
            message = "The catalog returned products, but none met the budget, already-owned exclusions, and must-have requirements together. Try loosening a requirement or adjusting the budget."
    else:
        message = None
    return {
        "status": "ready",
        "query": queries_tried[-1] if queries_tried else request_to_search_query(request),
        "queries_tried": queries_tried,
        "search_mode": search_mode,
        "demo_data": bool(demo_mode and not channel3.configured),
        "catalog_results_count": len(products),
        "recommendations": [
            {**product_to_dict(item.product), "score": round(item.score, 3), "reason": item.reason}
            for item in recs
        ],
        "budget": build_budget_summary(request, recs),
        "requires_user_approval": True,
        "empty_reason": empty_reason,
        "message": message,
    }


@app.post("/api/channel3/token")
def channel3_token() -> dict[str, str]:
    """Create a short-lived client token; never expose the Channel3 API key."""
    try:
        return Channel3Client().create_client_token()
    except Channel3Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/channel3/turn")
def channel3_turn(payload: AgentTurnPayload) -> dict[str, str]:
    """Forward one chat turn to Channel3's shopping agent and preserve its ID."""
    if payload.profile is not None:
        profile = _student_request(payload.profile)
        context = {
            "goal": profile.goal,
            "budget_usd": profile.budget,
            "already_owned_or_on_hand": profile.owns,
            "intended_use": profile.use_case,
            "priorities": profile.priorities,
            "device_details": profile.device_details,
            "must_have_requirements": profile.must_haves,
        }
        message = (
            AGENT_INSTRUCTIONS
            + "\nCurrent shopper profile (some fields may still be null): "
            + json.dumps(context, ensure_ascii=False)
            + "\nStudent's latest message: " + payload.message
        )
    else:
        message = AGENT_INSTRUCTIONS + "\nShopper's latest message: " + payload.message
    try:
        return Channel3Client().conversation_turn(
            payload.client_token, message, payload.conversation_id,
        )
    except Channel3Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/kernel/inspect-product")
async def inspect_product(payload: ProductPagePayload) -> dict[str, str]:
    """Optional, read-only Kernel inspection of a user-selected public URL."""
    try:
        return await inspect_product_page(payload.url)
    except KernelInspectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
