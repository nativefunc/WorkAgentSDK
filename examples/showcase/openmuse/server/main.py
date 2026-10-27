from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent))

from work_agent_sdk import Device, Local, Runner  # noqa: E402

from openmuse.agent import build_agent, make_model  # noqa: E402
from openmuse.api import account, activity, chats, control, device  # noqa: E402
from openmuse.config import load_settings  # noqa: E402
from openmuse.db import Database  # noqa: E402
from openmuse.relay import Relay  # noqa: E402
from openmuse.state import AppState, set_app_state  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("openmuse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database)
    db.interrupt_running()
    state = AppState(settings=settings, db=db)
    set_app_state(state)

    model = make_model(settings)
    state.model = model
    agent = build_agent(settings, model)

    nodes: list = [Device(user.device, wait=20) for user in db.users()]
    if settings.local:
        nodes.append(Local())
    runner = Runner(agents=[agent], data_dir=str(settings.runner_dir), nodes=nodes)
    async with runner:
        state.runner = runner
        relay = Relay(state)
        state.relay = relay
        relay.start()
        logger.info(
            "OpenMuse started: model %s, %s, data directory %s",
            settings.model,
            "workspace, browser and computer on this machine" if settings.local else "workspace, browser and computer on the user's devices",
            settings.data_dir,
        )
        try:
            yield
        finally:
            await relay.stop()
            state.relay = None
    db.close()
    set_app_state(None)


app = FastAPI(title="OpenMuse", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for module in (account, chats, activity, device, control):
    app.include_router(module.router)


@app.get("/api/health")
async def health():
    from openmuse.state import app_state

    return {"ok": True, "model": app_state().settings.model}
