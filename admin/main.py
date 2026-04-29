"""FastAPI application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .database import init_db
from .deps import get_current_user_optional

logger = logging.getLogger(__name__)

# Configure logging once (idempotent)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_ADMIN_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _ADMIN_DIR / "templates"
_STATIC_DIR = _ADMIN_DIR / "static"

# Module-level templates object (imported by route modules)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="VOICES KG Admin & API",
        version="0.1.0",
        description="Admin, auth, and public REST API for the VOICES KG.",
    )

    @app.on_event("startup")
    async def _startup() -> None:
        try:
            init_db()
            logger.info("DB ready at %s", settings.database_url)
        except Exception as exc:  # pragma: no cover
            logger.error("DB init failed: %s", exc)

    # --- Routers (imported here to avoid circular refs) ---
    from .routes import admin as admin_routes
    from .routes import api as api_routes
    from .routes import auth as auth_routes

    app.include_router(auth_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(api_routes.router)

    # Static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Top-level health
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    # Root — small landing / redirect to /admin if logged in else login
    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        user = get_current_user_optional(request)
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "user": user,
                "title": "VOICES KG",
                "content_block": "home",
            },
        )

    # Global error handler
    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s: %s", request.url.path, exc)
        # JSON for /api/*, HTML otherwise
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"error": "internal_error", "detail": str(exc)},
                status_code=500,
            )
        try:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "user": None, "error": str(exc), "code": 500},
                status_code=500,
            )
        except Exception:
            return JSONResponse({"error": "internal_error"}, status_code=500)

    return app


app = create_app()
