from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

# IMPORTANT:
# Register all SQLAlchemy models before anything touches them.
import app.models  # noqa: F401

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import (
    AsyncSessionLocal,
    close_database,
)
from app.core.errors import (
    RequestIdMiddleware,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.services.preferences.languages import seed_languages


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---------------------------------------------------------
    # Startup
    # ---------------------------------------------------------
    async with AsyncSessionLocal() as db:
        await seed_languages(db)

    yield

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------
    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Middleware
# ---------------------------------------------------------

app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# ---------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------

app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,
)

app.add_exception_handler(
    Exception,
    unhandled_exception_handler,
)


# ---------------------------------------------------------
# API
# ---------------------------------------------------------

app.include_router(
    api_router,
    prefix=settings.api_prefix,
)