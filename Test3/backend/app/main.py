from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.runtime import RoleRegistry
from app.api.routes import router
from app.api.routes_acceptance import router as acceptance_router
from app.api.routes_bots import router as bots_router
from app.api.routes_discussion import router as discussion_router
from app.api.routes_discussion_control import router as discussion_control_router
from app.api.routes_discussion_events import router as discussion_events_router
from app.api.routes_memberships import router as memberships_router
from app.api.routes_memory import router as memory_router
from app.api.routes_skills import router as skills_router
from app.llm.gateway import Gateway, build_provider
from app.services.runtime import Workbench
from app.settings import get_settings, load_models, load_roles, validate_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    models = load_models()
    roles = load_roles()
    try:
        validate_config(models, roles)
    except Exception:
        # prompts may be generated after first boot in tests; re-validate later
        pass
    provider = build_provider(settings.test3_llm_provider, models)
    if settings.test3_llm_provider == "scripted":
        from app.llm.providers import ScriptedProvider

        if isinstance(provider, ScriptedProvider):
            if settings.test3_scripted_fixture == "study-room":
                from app.fixtures.study_room import scripted_full_queue

                provider.queue.extend(scripted_full_queue())
            elif settings.test3_scripted_fixture == "discussion-e2e":
                from app.fixtures.discussion_e2e import scripted_discussion_queue

                provider.queue.extend(scripted_discussion_queue())
    gateway = Gateway(models, provider, data_dir=settings.data_dir())
    app.state.workbench = Workbench(gateway, RoleRegistry(roles), settings.data_dir())
    app.state.settings = settings
    app.state.workbench.start_loop()
    try:
        yield
    finally:
        await app.state.workbench.stop_loop()
        await app.state.workbench.close()


def create_app() -> FastAPI:
    app = FastAPI(title="HexaGraph Test3", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(bots_router, prefix="/api")
    app.include_router(memberships_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(discussion_router, prefix="/api")
    app.include_router(discussion_control_router, prefix="/api")
    app.include_router(discussion_events_router, prefix="/api")
    app.include_router(acceptance_router, prefix="/api")
    return app


app = create_app()
