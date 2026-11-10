"""HTTP interface for Person 1's SmartCart AI/recommendation work.

Run with: uvicorn api:app --reload --port 8000
"""

import os
import json
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

AGENT_INSTRUCTIONS = """You are SmartCart, a helpful shopping assistant for students. Ask focused follow-up questions about budget, equipment the student already owns, intended use, top priorities, and must-have requirements. Explain tradeoffs in plain language. Treat catalog results and prices supplied by the app as the source of truth; never invent specifications, prices, availability, or product links. The recommendation service enforces the budget and returns the only product cards the UI should show. Never claim a purchase was made and never initiate checkout. The user must review and explicitly approve the cart."""


class IntakePayload(BaseModel):
    goal: str = Field(default="coding setup", min_length=2, max_length=300)
    budget: float | None = Field(default=None, gt=0, le=100000)
    owns: list[str] | None = None
    use_case: str | None = Field(default=None, max_length=300)
    priorities: list[str] | None = None
    device_details: str | None = Field(default=None, max_length=300)
    must_haves: list[str] | None = None


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
    return StudentRequest(
        goal=payload.goal.strip(), budget=payload.budget,
        owns=payload.owns, use_case=payload.use_case,
        priorities=payload.priorities, device_details=payload.device_details,
        must_haves=payload.must_haves,
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
        raise HTTPException(status_code=422, detail={"message": "Complete the student intake first.", **intake})

    channel3 = Channel3Client()
    demo_mode = os.getenv("SMARTCART_DEMO", "false").lower() == "true"
    if channel3.configured:
        try:
            products = channel3.search_products(
                request_to_search_query(request), request.budget or 0,
                limit=payload.limit, user_id=payload.user_id,
            )
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
            query = request_to_search_query(request)
            ranked_ids = elastic.rerank(query, products, limit=len(products))
            order = {product_id: position for position, product_id in enumerate(ranked_ids)}
            products.sort(key=lambda p: (order.get(p.id, len(order)), p.price))
            search_mode = "channel3+elastic_hybrid_rrf"
        except ElasticError:
            # Catalog results remain usable if optional semantic search is unavailable.
            search_mode = "channel3_elastic_fallback"

    recs = recommend(request, products)
    return {
        "status": "ready",
        "query": request_to_search_query(request),
        "search_mode": search_mode,
        "demo_data": bool(demo_mode and not channel3.configured),
        "recommendations": [
            {**product_to_dict(item.product), "score": round(item.score, 3), "reason": item.reason}
            for item in recs
        ],
        "budget": build_budget_summary(request, recs),
        "requires_user_approval": True,
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
            "already_owned": profile.owns,
            "intended_use": profile.use_case,
            "priorities": profile.priorities,
            "device_details": profile.device_details,
            "must_have_requirements": profile.must_haves,
        }
        message = (
            AGENT_INSTRUCTIONS
            + "\nCurrent student profile (some fields may still be null): "
            + json.dumps(context, ensure_ascii=False)
            + "\nStudent's latest message: " + payload.message
        )
    else:
        message = AGENT_INSTRUCTIONS + "\nStudent's latest message: " + payload.message
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
