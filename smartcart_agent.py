"""Open-ended SmartCart intake, product ranking, and budget guardrails."""

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
    "budget": "What is your maximum total budget in USD?",
    "owns": "What related items do you already have? For groceries, include ingredients on hand; for other shopping, list anything you do not need to buy. Say 'none' if nothing applies.",
    "use_case": "What will you use the items for, or what is the occasion?",
    "priorities": "Which factors matter most, such as price, quality, style, fit, durability, brand, or convenience?",
    "device_details": "Are there any details that affect fit or compatibility, such as size, model, dietary needs, preferred colors, or measurements? Say 'not sure' if unknown.",
    "must_haves": "What are your non-negotiable requirements? Say 'none' if you do not have any.",
}

_SEARCH_STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with",
    "me", "my", "i", "we", "you", "your", "please", "help", "find", "show",
    "looking", "need", "want", "buy", "get", "shop", "shopping", "item", "items",
    "product", "products", "under", "below", "up", "within", "budget", "usd",
    "dollar", "dollars", "around", "about", "maximum", "max", "setup", "setups",
    "some", "any", "that", "this", "it", "is", "are", "be", "as", "at", "from",
    "string", "null", "undefined", "none", "nothing", "not", "sure", "unknown",
}

_VAGUE_REQUIREMENT_WORDS = {
    "good", "great", "nice", "best", "excellent", "quality", "high", "low",
    "premium", "reliable", "affordable", "cheap", "value",
}
_NEGATION_WORDS = {"no", "not", "without", "exclude", "avoid"}

_OWNERSHIP_FILLER = {
    "i", "we", "already", "own", "owns", "have", "has", "got", "some", "a", "an",
    "the", "my", "our", "none", "nothing", "else", "not", "applicable", "starting",
    "scratch", "from", "no", "and", "or", "n", "a",
}

_SYNONYM_GROUPS = (
    {"gpu", "graphic", "graphics", "video", "visual"},
    {"ram", "memory", "dimm", "sodimm"},
    {"dress", "gown", "bridal"},
    {"wedding", "bridal", "bride"},
    {"grocery", "food", "produce", "grocer", "ingredient", "pantry"},
    {"clothing", "clothe", "apparel", "garment", "fashion", "outfit"},
    {"shoe", "footwear", "sneaker", "boot"},
    {"headphone", "headset", "earbud"},
    {"monitor", "display", "screen"},
    {"vegetable", "produce", "veggie"},
    {"baby", "infant", "newborn"},
    {"pet", "dog", "cat", "canine", "feline"},
    {"comfort", "comfortable", "soft"},
    {"durability", "durable", "longlasting"},
    {"style", "stylish", "fashion", "design"},
    {"fit", "size", "sizing"},
    {"fresh", "freshness", "ripe"},
    {"organic", "natural"},
    {"value", "affordable", "cheap", "budget"},
)


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", value.lower())
    normalized = set()
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("sses"):
            word = word[:-2]
        elif len(word) > 4 and word.endswith(("ches", "shes", "xes", "zes")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        normalized.add(word)
    return normalized


def _requirement_tokens(values: list[str]) -> set[str]:
    ignored = _SEARCH_STOP_WORDS | _VAGUE_REQUIREMENT_WORDS | {
        "at", "least", "minimum", "min", "must", "have", "needs", "need", "require", "required",
    }
    return _tokens(" ".join(values)) - ignored


def _related_terms(term: str) -> set[str]:
    # Resolve connected synonym groups too (for example, wedding -> bridal -> gown).
    related = {term}
    changed = True
    while changed:
        changed = False
        for group in _SYNONYM_GROUPS:
            if related & group and not group <= related:
                related.update(group)
                changed = True
    return related


def _search_terms(value: str) -> set[str]:
    return _tokens(value) - _SEARCH_STOP_WORDS


def _requirement_phrases(values: list[str]) -> list[set[str]]:
    ignored = _SEARCH_STOP_WORDS | _VAGUE_REQUIREMENT_WORDS | {
        "at", "least", "minimum", "min", "must", "have", "needs", "need", "require", "required",
    }
    phrases = []
    for value in values:
        tokens = _tokens(value)
        # Keep negative phrasing in the external catalog query, but do not turn
        # "not black" into a positive requirement for black products.
        if tokens & _NEGATION_WORDS:
            continue
        terms = tokens - ignored
        if terms:
            phrases.append(terms)
    return phrases


def _phrase_matches(terms: set[str], product_terms: set[str]) -> bool:
    if not terms:
        return True
    hits = sum(bool(_related_terms(term) & product_terms) for term in terms)
    # Allow minor catalog wording gaps while still requiring the distinctive
    # parts of each requirement. Subjective words are removed before this check.
    required_hits = 1 if len(terms) == 1 else math.ceil(len(terms) * 0.6)
    return hits >= required_hits


def _product_is_owned(product: Product, owns: list[str]) -> bool:
    # Compare concrete owned items with the product name. A broad entry such as
    # "clothes" or "food" should not suppress every item in that category.
    identity_terms = _tokens(product.name)
    for owned_item in owns:
        terms = _tokens(owned_item) - _OWNERSHIP_FILLER - _SEARCH_STOP_WORDS
        if not terms:
            continue
        hits = sum(bool(_related_terms(term) & identity_terms) for term in terms)
        required_hits = 1 if len(terms) == 1 else math.ceil(len(terms) * 0.75)
        if hits >= required_hits:
            return True
    return False


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
    if request.must_haves is None:
        return {"status": "needs_input", "field": "must_haves", "question": QUESTIONS["must_haves"]}
    return {"status": "ready", "field": None, "question": None}


def parse_initial_message(message: str) -> StudentRequest:
    """Extract an obvious shopping goal and budget; ask the shopper for the rest."""
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
    context_text = re.sub(
        r"\b(?:under|below|up to|within|budget(?: of| is)?|less than|maximum|max)\s*\$?\s*\d[\d,]*(?:\.\d{1,2})?",
        " ", text, flags=re.IGNORECASE,
    )
    context_text = re.sub(r"\$\s*\d[\d,]*(?:\.\d{1,2})?", " ", context_text)
    context_match = re.search(r"\bfor\s+(?:my|a|an|the)\s+([^,.;!?]+)", context_text, re.IGNORECASE)
    use_case = context_match.group(1).strip() if context_match else None
    return StudentRequest(
        goal=text or "shopping request", budget=budget, owns=None,
        use_case=use_case, priorities=None, device_details=None, must_haves=None,
    )


def request_to_search_query(request: StudentRequest, include_preferences: bool = True) -> str:
    """Build a catalog query; optionally broaden to goal and use case only."""
    parts = [request.goal]
    if request.use_case:
        parts.append(request.use_case)
    if include_preferences:
        if request.device_details:
            parts.append(request.device_details)
        if request.priorities:
            parts.extend(request.priorities)
        if request.must_haves:
            parts.extend(request.must_haves)

    query_parts = []
    seen = set()
    for part in parts:
        cleaned = part.strip()
        cleaned = re.sub(
            r"\b(?:under|below|up to|within|budget(?: of| is)?|less than|maximum|max)\s*\$?\s*\d[\d,]*(?:\.\d{1,2})?",
            " ", cleaned, flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\$\s*\d[\d,]*(?:\.\d{1,2})?", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;")
        cleaned = re.sub(
            r"^(?:help me find|find me|show me|i am looking for|i'm looking for|looking for|i need|we need)\s+",
            "", cleaned, flags=re.IGNORECASE,
        ).strip()
        key = " ".join(sorted(_tokens(cleaned)))
        if cleaned and _search_terms(cleaned) and key not in seen:
            query_parts.append(cleaned)
            seen.add(key)
    return " ".join(query_parts)


def _category_key(product: Product) -> str:
    """Use the catalog's category label as-is; unknown categories need no mapping."""
    return " ".join(_tokens(product.category)) or "other"


def _priority_terms(priorities: list[str]) -> set[str]:
    aliases = {
        "performance": {"performance", "fast", "speed", "cpu", "processor"},
        "ram": {"ram", "memory"},
        "gpu": {"gpu", "graphics", "video"},
        "storage": {"storage", "ssd", "hdd", "drive"},
        "monitor": {"monitor", "display", "screen"},
        "value": {"budget", "cheap", "affordable", "cost", "price", "value"},
        "comfort": {"comfort", "comfortable", "soft"},
        "durability": {"durability", "durable", "longlasting"},
        "style": {"style", "stylish", "fashion", "design"},
        "fit": {"fit", "size", "sizing"},
        "freshness": {"fresh", "freshness", "ripe"},
        "organic": {"organic", "natural"},
        "convenience": {"convenient", "convenience", "easy", "portable"},
    }
    tokens = _search_terms(" ".join(priorities))
    mapped = set(tokens)
    for canonical, words in aliases.items():
        if tokens & words:
            mapped.add(canonical)
    return mapped


def _product_score(product: Product, request: StudentRequest) -> tuple[float, list[str]]:
    text = _tokens(product.search_text())
    category = _category_key(product)
    intent_terms = _search_terms(f"{request.goal} {request.use_case or ''}")
    intent_hits = {term for term in intent_terms if _related_terms(term) & text}
    score = 1.0
    score += min(6.0, 2.0 * len(intent_hits))
    if intent_terms and len(intent_hits) >= min(2, len(intent_terms)):
        score += 1.0
    matches = sorted(intent_hits)

    priority_terms = _priority_terms(request.priorities or [])
    priority_hits = {term for term in priority_terms if _related_terms(term) & text or term == category}
    score += 3.0 * len(priority_hits)
    matches.extend(term for term in sorted(priority_hits) if term not in matches)

    for phrase in _requirement_phrases(request.must_haves or []):
        phrase_hits = [term for term in phrase if _related_terms(term) & text]
        score += 2.0 * len(phrase_hits) / max(1, len(phrase))
        matches.extend(term for term in phrase_hits if term not in matches)

    if any(term in priority_terms for term in {"value", "price", "affordable", "cheap", "budget"}):
        score += max(0.0, 2.5 * (1.0 - product.price / max(request.budget or 1.0, 1.0)))
    return score, matches


def recommend(request: StudentRequest, products: Iterable[Product], limit: int = 4) -> list[Recommendation]:
    """Choose a relevant set of products that never exceeds the total budget.

    The selection only uses current catalog prices. It does not invent product
    specifications; hard requirements are checked only when clearly present in
    the product's structured attributes or text.
    """
    if request.budget is None or not math.isfinite(request.budget) or request.budget <= 0:
        return []
    budget_cents = _cents(request.budget)
    must_haves = _requirement_phrases(request.must_haves or [])
    owns = [item for item in (request.owns or []) if _tokens(item) - _OWNERSHIP_FILLER - _SEARCH_STOP_WORDS]
    candidates: list[tuple[Product, float, list[str], str]] = []

    for product in products:
        if not math.isfinite(product.price) or product.currency.upper() != "USD" or product.price < 0 or _cents(product.price) > budget_cents:
            continue
        if product.availability.lower() not in {"instock", "in stock", "available", "unknown"}:
            continue
        category = _category_key(product)
        if _product_is_owned(product, owns):
            continue
        text = _tokens(product.search_text())
        if must_haves and not all(_phrase_matches(phrase, text) for phrase in must_haves):
            continue
        score, matched = _product_score(product, request)
        score += max(0.0, 0.75 * (1.0 - product.price / max(request.budget, 1.0)))
        matched_text = ", ".join(matched) if matched else "your stated goal"
        reason = f"Fits {matched_text}; current listed price is ${product.price:.2f}."
        candidates.append((product, score, matched, reason))

    # Keep a short candidate list for a budget-safe mix of relevant options.
    candidates.sort(key=lambda row: (-row[1], row[0].price, row[0].name.lower()))
    candidates = candidates[:24]
    best: tuple[float, tuple[int, ...]] | None = None
    max_items = min(limit, 4)
    for count in range(1, max_items + 1):
        for indexes in combinations(range(len(candidates)), count):
            rows = [candidates[i] for i in indexes]
            total_cents = sum(_cents(row[0].price) for row in rows)
            if total_cents > budget_cents:
                continue
            # Category variety is a preference, not a restriction. This allows
            # grocery lists, clothing options, and other repeated-category buys.
            categories = [_category_key(row[0]) for row in rows]
            distinct_categories = len(set(categories))
            repeated_categories = count - distinct_categories
            score = (
                sum(row[1] for row in rows)
                + 1.0 * (count - 1)
                + 1.25 * max(0, distinct_categories - 1)
                - 0.5 * repeated_categories
            )
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
    """Fictional cross-category examples; replace these with live catalog results."""
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
        Product("demo-grocery-apples", "Demo bag of fresh apples", "groceries", 5.49,
                attributes={"type": "produce", "quantity": "3 lb"}, tags=["grocery", "fruit", "snack"], source="fictional demo"),
        Product("demo-grocery-pasta", "Demo whole grain pasta", "groceries", 3.29,
                attributes={"diet": "vegetarian", "quantity": "1 lb"}, tags=["grocery", "pantry", "meal"], source="fictional demo"),
        Product("demo-grocery-beans", "Demo black beans, 4 pack", "groceries", 4.79,
                attributes={"diet": "vegetarian", "quantity": "4 cans"}, tags=["grocery", "pantry", "protein"], source="fictional demo"),
        Product("demo-dress-wedding", "Demo ivory wedding gown", "dresses", 249.99,
                attributes={"occasion": "wedding", "color": "ivory"}, tags=["bridal", "formal", "dress"], source="fictional demo"),
        Product("demo-clothing-shirt", "Demo cotton casual shirt", "clothing", 24.99,
                attributes={"material": "cotton", "fit": "regular"}, tags=["apparel", "casual", "clothing"], source="fictional demo"),
        Product("demo-shoes-sneaker", "Demo everyday walking sneakers", "shoes", 54.99,
                attributes={"use": "walking", "fit": "unisex"}, tags=["footwear", "comfort", "shoe"], source="fictional demo"),
    ]


def demo() -> None:
    examples = [
        StudentRequest(
            goal="coding setup", budget=300.00, owns=["laptop", "monitor"],
            use_case="basic coding", priorities=["storage", "value"], must_haves=[],
        ),
        StudentRequest(
            goal="groceries", budget=50.00, owns=["olive oil"],
            use_case="weekday meals", priorities=["vegetarian", "value"], must_haves=["vegetarian"],
        ),
        StudentRequest(
            goal="wedding dress", budget=500.00, owns=[],
            use_case="my wedding", priorities=["style", "comfort"],
            device_details="size 8, ivory", must_haves=["wedding gown"],
        ),
    ]
    catalog = demo_catalog()
    for request in examples:
        picks = recommend(request, catalog)
        print(f"Goal: {request.goal} | Budget: ${request.budget:.2f}")
        for item in picks:
            print(f"- {item.product.name} (${item.product.price:.2f}): {item.reason}")
        print("Budget summary:", build_budget_summary(request, picks))
        print()
    print("Demo catalog data and prices are fictional placeholders.")


if __name__ == "__main__":
    demo()
