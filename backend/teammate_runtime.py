"""Load the teammate SmartCart runtime into the unified backend process."""

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEAMMATE_ROOT = PROJECT_ROOT / "smartcart-ai"
TEAMMATE_API_FILE = TEAMMATE_ROOT / "api.py"

if str(TEAMMATE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEAMMATE_ROOT))

spec = importlib.util.spec_from_file_location("studentcart_teammate_api", TEAMMATE_API_FILE)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load teammate API from {TEAMMATE_API_FILE}")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

IntakePayload = module.IntakePayload
RecommendationPayload = module.RecommendationPayload
IntakeStartPayload = module.IntakeStartPayload
teammate_health = module.health
teammate_intake_next = module.intake_next
teammate_intake_start = module.intake_start
teammate_recommendations = module.recommendations
