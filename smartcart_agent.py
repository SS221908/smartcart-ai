"""SmartCart intake, ranking, and hard budget guardrails."""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import math
import re
from typing import Iterable


@dataclass
class StudentRequest:
    goal: str
    budget: float | None
    owns: list[str] | None = None
    use_case: str | None = None
    priorities: list[str] | None = None
    device_details: str | None = None
    must_haves: list[str] | None = None


@dataclass
class Product:
    id: str
    name: str
    category: str
    price: float
    currency: str = "USD"
    brand: str = ""
    description: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    image_url: str = ""
    url: str = ""
    merchant: str = ""
    availability: str = "InStock"
    source: str = ""

    def search_text(self) -> str:
        pairs = [f"{key} {value}" for key, value in self.attributes.items()]
        return " ".join([self.name, self.brand, self.category, self.description, *self.tags, *pairs])


@dataclass
class Recommendation:
    product: Product
    score: float
    reason: str


QUESTIONS = {
    "budget": "What is your maximum budget? For example, $300.",
    "owns": "What do you already own that you can use, such as a laptop, desktop, monitor, keyboard, or storage? Say 'nothing else' if you are starting from scratch.",
    "use_case": "What will you use the setup for: basic coding, game development, local AI, or something else?",
    "priorities": "Which two matter most: performance, RAM, graphics, storage, screen quality, or keeping costs low?",
    "device_details": "What is your laptop or desktop model, and do you know whether its RAM or graphics can be upgraded? If you are unsure, say 'not sure' so I will avoid assuming an upgrade will fit.",
    "must_haves": "Any must-have requirements, such as a minimum RAM amount or screen size? Say 'none' if you do not have any.",
}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", value.lower()))


def _requirement_tokens(values: list[str]) -> set[str]:
    ignored = {"at", "least", "minimum", "maximum", "max", "min", "need", "needs", "must", "have", "with", "a", "an", "the", "for", "of", "or", "and", "please"}
    return _tokens(" ".join(values)) - ignored


def _cents(value: float) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def next_question(request: StudentRequest) -> dict[str, str | None]:
    """Choose the next intake question. None means ready to search."""
    checks = [
        ("budget", request.budget is not None and request.budget > 0),
        ("owns", request.owns is not None),
        ("use_case", bool(request.use_case and request.use_case.strip())),
        ("priorities", request.priorities is not None),
    ]
    for field_name, complete in checks:
        if not complete:
            return {"status": "needs_input", "field": field_name, "question": QUESTIONS[field_name]}
    owns_words = _tokens(" ".join(request.owns or []))
    priority_words = _priority_terms(request.priorities or [])
    if owns_words & {"laptop", "desktop", "computer", "pc"} and priority_words & {"ram", "gpu"} and request.device_details is None:
        return {"status": "needs_input", "field": "device_details", "question": QUESTIONS["device_details"]}
    if request.must_haves is None:
        return {"status": "needs_input", "field": "must_haves", "question": QUESTIONS["must_haves"]}
    return {"status": "ready", "field": None, "question": None}


def parse_initial_message(message: str) -> StudentRequest:
    """Extract only obvious starter fields; ask the student to confirm the rest."""
    text = message.strip()
    patterns = [
        r"(?:under|below|up to|within|budget(?: of| is)?|less than|maximum|max)\s*\$?\s*(\d[\d,]*(?:\.\d{1,2})?)",
        r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)",
    ]
    budget = None
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                budget = float(match.group(1).replace(",", ""))
                break
            except ValueError:
                pass
    lowered = text.lower()
    if any(term in lowered for term in ("local ai", "run ai locally", "machine learning")):
        use_case = "local AI and machine learning"
    elif any(term in lowered for term in ("game development", "gaming", "game dev")):
        use_case = "game development"
    elif any(term in lowered for term in ("coding", "programming", "developer")):
        use_case = "coding"
    else:
        use_case = None
    return StudentRequest(
        goal=text or "student setup", budget=budget, owns=None,
        use_case=use_case, priorities=None, device_details=None, must_haves=None,
    )


def request_to_search_query(request: StudentRequest) -> str:
    parts = [request.goal]
    if request.use_case:
        parts.append(f"for {request.use_case}")
    if request.priorities:
        parts.append("prioritize " + ", ".join(request.priorities))
    if request.device_details:
        parts.append("device details: " + request.device_details)
    if request.must_haves:
        parts.append("requirements: " + ", ".join(request.must_haves))
    if request.owns:
        parts.append("exclude items already owned: " + ", ".join(request.owns))
    return ". ".join(parts)


def _category_key(product: Product) -> str:
    text = _tokens(product.category + " " + product.name + " " + " ".join(product.tags))
    aliases = {
        "computer": {"computer", "laptop", "notebook", "desktop", "pc"},
        "monitor": {"monitor", "display", "screen"},
        "ram": {"ram", "memory", "dimm", "sodimm"},
        "gpu": {"gpu", "graphics", "video"},
        "storage": {"storage", "ssd", "hdd", "drive", "disk"},
        "keyboard": {"keyboard"},
        "mouse": {"mouse"},
        "dock": {"dock", "hub"},
        "headset": {"headset", "headphones"},
    }
    for canonical, terms in aliases.items():
        if text & terms:
            return canonical
    return (product.category or "other").strip().lower() or "other"


def _owned_category_tokens(owns: list[str]) -> set[str]:
    words = _tokens(" ".join(owns))
    owned: set[str] = set()
    if words & {"computer", "laptop", "notebook", "desktop", "pc"}:
        owned.add("computer")
    if words & {"monitor", "display", "screen"}:
        owned.add("monitor")
    if words & {"ram", "memory"}:
        owned.add("ram")
    if words & {"gpu", "graphics"}:
        owned.add("gpu")
    if words & {"ssd", "storage", "hdd", "drive"}:
        owned.add("storage")
    for item in ("keyboard", "mouse", "dock", "headset"):
        if item in words:
            owned.add(item)
    return owned


def _priority_terms(priorities: list[str]) -> set[str]:
    aliases = {
        "performance": {"performance", "fast", "speed", "cpu", "processor"},
        "ram": {"ram", "memory"},
        "gpu": {"gpu", "graphics", "video"},
        "storage": {"storage", "ssd", "hdd", "drive"},
        "monitor": {"monitor", "display", "screen"},
        "value": {"budget", "cheap", "affordable", "cost", "value"},
    }
    tokens = _tokens(" ".join(priorities))
    mapped = set(tokens)
    for canonical, words in aliases.items():
        if tokens & words:
            mapped.add(canonical)
    return mapped


def _product_score(product: Product, priorities: set[str]) -> tuple[float, list[str]]:
    text = _tokens(product.search_text())
    category = _category_key(product)
    mapped = {
        "monitor": {"monitor", "display", "screen"},
        "ram": {"ram", "memory"},
        "gpu": {"gpu", "graphics", "video"},
        "storage": {"storage", "ssd", "hdd", "drive"},
        "performance": {"performance", "fast", "cpu", "processor"},
        "value": {"budget", "affordable", "value", "cheap"},
    }
    matches = []
    score = 1.0
    for p in priorities:
        terms = mapped.get(p, {p})
        if p == category or text & terms:
            score += 4.0
            matches.append(p)
    return score, matches


def recommend(request: StudentRequest, products: Iterable[Product], limit: int = 4) -> list[Recommendation]:
    """Choose a diverse set of products that never exceeds the total budget.

    The selection only uses current catalog prices. It does not invent product
    specifications; hard requirements are checked only when clearly present in
    the product's structured attributes or text.
    """
    if request.budget is None or not math.isfinite(request.budget) or request.budget <= 0:
        return []
    budget_cents = _cents(request.budget)
    owned = _owned_category_tokens(request.owns or [])
    priorities = _priority_terms(request.priorities or [])
    must_haves = _requirement_tokens(request.must_haves or [])
    candidates: list[tuple[Product, float, list[str], str]] = []

    for product in products:
        if not math.isfinite(product.price) or product.currency.upper() != "USD" or product.price < 0 or _cents(product.price) > budget_cents:
            continue
        if product.availability.lower() not in {"instock", "in stock", "available", "unknown"}:
            continue
        category = _category_key(product)
        if category in owned:
            continue
        owned_words = _tokens(" ".join(request.owns or []))
        if "laptop" in owned_words and category in {"ram", "gpu"}:
            upgrade_notes = _tokens(request.device_details or "")
            if "upgradeable" not in upgrade_notes and "upgrade" not in upgrade_notes:
                continue
        text = _tokens(product.search_text())
        # Hard requirements should be explicit and supported by catalog data.
        if must_haves and not must_haves.issubset(text):
            continue
        score, matched = _product_score(product, priorities)
        score += max(0.0, 1.5 * (1.0 - product.price / max(request.budget, 1.0)))
        matched_text = ", ".join(matched) if matched else "your stated goal"
        reason = f"Fits {matched_text}; current listed price is ${product.price:.2f}."
        candidates.append((product, score, matched, reason))

    # Keep a short candidate list for combinations; one item per category.
    candidates.sort(key=lambda row: (-row[1], row[0].price, row[0].name.lower()))
    candidates = candidates[:24]
    best: tuple[float, tuple[int, ...]] | None = None
    max_items = min(limit, 4)
    for count in range(1, max_items + 1):
        for indexes in combinations(range(len(candidates)), count):
            rows = [candidates[i] for i in indexes]
            categories = [_category_key(row[0]) for row in rows]
            if len(set(categories)) != len(categories):
                continue
            total_cents = sum(_cents(row[0].price) for row in rows)
            if total_cents > budget_cents:
                continue
            # Reward need-fit and filling more than one distinct need, while
            # keeping the selected bundle below the user's hard budget.
            score = sum(row[1] for row in rows) + 1.25 * (count - 1)
            if best is None or score > best[0]:
                best = (score, indexes)
    if best is None:
        return []

    chosen = [candidates[i] for i in best[1]]
    total_cents = sum(_cents(row[0].price) for row in chosen)
    total = total_cents / 100
    remaining = (budget_cents - total_cents) / 100
    results = []
    for product, score, matched, reason in chosen:
        reasons = [reason]
        if len(chosen) > 1:
            reasons.append(f"This bundle totals ${total:.2f}, leaving ${remaining:.2f} under your budget.")
        if matched:
            reasons.append("Matched priorities: " + ", ".join(matched) + ".")
        results.append(Recommendation(product=product, score=score, reason=" ".join(reasons)))
    return results


def build_budget_summary(request: StudentRequest, recommendations: list[Recommendation]) -> dict[str, object]:
    total_cents = sum(_cents(item.product.price) for item in recommendations)
    budget_value = float(request.budget or 0)
    budget_cents = _cents(budget_value) if math.isfinite(budget_value) else 0
    total = total_cents / 100
    budget = budget_cents / 100
    return {
        "currency": "USD",
        "budget": budget,
        "recommended_total": total,
        "remaining": round(max(0.0, budget - total), 2),
        "within_budget": total <= budget,
        "requires_user_approval": True,
    }


def product_to_dict(product: Product) -> dict[str, object]:
    return asdict(product)


def demo_catalog() -> list[Product]:
    """Fictional data only; replace it with current Channel3 catalog results."""
    return [
        Product("demo-monitor-1", "Demo 24 inch basic monitor", "monitor", 89.99,
                attributes={"screen": "24 inch", "refresh": "75 Hz"}, tags=["coding", "display", "budget"], source="fictional demo"),
        Product("demo-storage-1", "Demo 1 TB external SSD", "storage", 69.99,
                attributes={"capacity": "1 TB", "type": "SSD"}, tags=["coding", "fast", "portable"], source="fictional demo"),
        Product("demo-keyboard-1", "Demo wired keyboard", "keyboard", 19.99,
                attributes={"connection": "wired"}, tags=["accessory", "budget"], source="fictional demo"),
        Product("demo-ram-1", "Demo 16 GB memory kit", "ram", 44.99,
                attributes={"capacity": "16 GB"}, tags=["performance", "memory", "upgrade"], source="fictional demo"),
        Product("demo-gpu-1", "Demo entry graphics card", "gpu", 159.99,
                attributes={"memory": "8 GB"}, tags=["graphics", "performance"], source="fictional demo"),
    ]


def demo() -> None:
    request = StudentRequest(
        goal="coding setup", budget=300.00, owns=["laptop", "monitor"],
        use_case="basic coding", priorities=["storage", "value"], must_haves=[],
    )
    picks = recommend(request, demo_catalog())
    print(f"Goal: {request.goal} | Budget: ${request.budget:.2f}")
    for item in picks:
        print(f"- {item.product.name} (${item.product.price:.2f}): {item.reason}")
    print("Budget summary:", build_budget_summary(request, picks))
    print("Demo catalog data and prices are fictional placeholders.")


if __name__ == "__main__":
    demo()
