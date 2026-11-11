import os
from uuid import uuid4

from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from cart_validation import CatalogProduct, load_catalog, validate_cart
from paypal_service import PayPalServiceError, capture_order, create_order
from teammate_runtime import (
    IntakePayload as TeammateIntakePayload,
    IntakeStartPayload as TeammateIntakeStartPayload,
    RecommendationPayload as TeammateRecommendationPayload,
    teammate_health,
    teammate_intake_next,
    teammate_intake_start,
    teammate_recommendations,
)

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))
load_dotenv()

app = FastAPI(title="StudentCart AI API", version="0.1.0")

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

CATALOG_SNAPSHOTS: dict[str, dict[str, CatalogProduct]] = {}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", **teammate_health()}


@app.get("/health")
def health_alias() -> dict:
    return health()


class CartItem(BaseModel):
    id: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    currency: str
    quantity: int = Field(ge=1)


class CartValidationRequest(BaseModel):
    items: list[CartItem] = Field(min_length=1)
    budget: Decimal = Field(gt=0)
    client_total: Decimal | None = Field(default=None, ge=0)
    recommendation_set_id: str | None = None


class RecommendationRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=300)
    budget: float = Field(gt=0, le=100000)
    owns: list[str] = []
    use_case: str = ""
    priorities: list[str] = []
    device_details: str | None = None
    must_haves: list[str] = []
    user_id: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class IntakeStartRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class IntakeNextRequest(BaseModel):
    goal: str = "coding setup"
    budget: float | None = None
    owns: list[str] = []
    use_case: str | None = None
    priorities: list[str] = []
    device_details: str | None = None
    must_haves: list[str] | None = None


def _register_catalog_snapshot(data: dict) -> str:
    snapshot_id = str(uuid4())
    catalog: dict[str, CatalogProduct] = {}
    for product in data.get("recommendations", []):
        if not isinstance(product, dict) or not product.get("id") or product.get("price") is None:
            continue
        try:
            catalog[str(product["id"])] = CatalogProduct(Decimal(str(product["price"])), str(product.get("currency", "USD")))
        except Exception:
            continue
    CATALOG_SNAPSHOTS[snapshot_id] = catalog
    return snapshot_id


def _catalog_for_request(request: CartValidationRequest) -> dict[str, CatalogProduct]:
    if request.recommendation_set_id:
        return CATALOG_SNAPSHOTS.get(request.recommendation_set_id, {})
    return load_catalog()


@app.post("/api/intake/start")
def intake_start_proxy(request: IntakeStartRequest) -> dict:
    return teammate_intake_start(TeammateIntakeStartPayload(**request.model_dump()))


@app.post("/api/intake/next")
def intake_next_proxy(request: IntakeNextRequest) -> dict:
    return teammate_intake_next(TeammateIntakePayload(**request.model_dump(exclude_none=True)))


@app.post("/api/recommendations")
def recommendations_proxy(request: RecommendationRequest) -> dict:
    try:
        teammate_request = TeammateRecommendationPayload(**request.model_dump(exclude_none=True))
        data = teammate_recommendations(teammate_request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Recommendation runtime failed: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("recommendations"), list):
        raise HTTPException(status_code=502, detail="Recommendation response is missing recommendations")
    data["recommendation_set_id"] = _register_catalog_snapshot(data)
    return data


@app.post("/api/cart/validate")
def cart_validate(request: CartValidationRequest) -> dict:
    try:
        catalog = _catalog_for_request(request)
        if not catalog:
            raise HTTPException(status_code=503, detail="Product catalog is not configured")
        return validate_cart(request.model_dump(mode="json"), catalog)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/paypal/orders")
async def paypal_create_order(request: CartValidationRequest) -> dict:
    try:
        catalog = _catalog_for_request(request)
        if not catalog:
            raise HTTPException(status_code=503, detail="Product catalog is not configured")
        validated = validate_cart(request.model_dump(mode="json"), catalog)
        if validated["over_budget"]:
            raise HTTPException(status_code=422, detail="Cart is over budget")
        return await create_order(validated)
    except HTTPException:
        raise
    except PayPalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/paypal/orders/{order_id}/capture")
async def paypal_capture_order(order_id: str) -> dict:
    if not order_id or len(order_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid PayPal order ID")
    try:
        return await capture_order(order_id)
    except PayPalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
