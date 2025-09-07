from .events import router as events_router
from .settings import router as settings_router
from .users import router as users_router

__all__ = ["events_router", "settings_router", "users_router"]
