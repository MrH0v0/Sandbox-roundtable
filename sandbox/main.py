from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sandbox.api.routes import router
from sandbox.core.service_container import AppServices, build_services


def create_app(services_factory: Callable[[], AppServices] = build_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = services_factory()
        app.state.services = services
        yield
        await services.workbench_service.aclose()

    app = FastAPI(
        title="Sandbox Roundtable Engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
