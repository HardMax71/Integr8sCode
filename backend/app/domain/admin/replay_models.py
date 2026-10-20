from dataclasses import dataclass, field

from app.domain.events import EventSummary
from app.domain.replay import ReplayFilter


@dataclass
class ReplaySessionData:
    """Unified replay session data for both preview and actual replay."""

    total_events: int
    replay_id: str
    dry_run: bool
    filter: ReplayFilter
    events_preview: list[EventSummary] = field(default_factory=list)
