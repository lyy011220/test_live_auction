from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Scenario:
    name: str
    script: Path
    vus: int
    case_id: str
    expected_final_price: float | None
    max_duration: str
    description: str
    purpose: Literal["correctness", "performance"] = "correctness"
    requires_tokens: bool = True
    target_rates: tuple[int, ...] = ()
    stage_duration: str | None = None
    cooldown_seconds: int = 0
    auction_duration_minutes: int | None = None

