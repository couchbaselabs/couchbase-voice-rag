"""Rate limiting middleware built on ``slowapi``.

Import ``limiter`` into routers that need per-endpoint limits and apply
``@limiter.limit("N/period")`` to route handlers. ``main.py`` is expected
to wire ``limiter`` into the FastAPI app exactly once via
``app.state.limiter = limiter`` and register ``SlowAPIMiddleware`` plus
the 429 exception handler.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
