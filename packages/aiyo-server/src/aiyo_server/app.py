"""AIYO Server FastAPI application."""

import asyncio
import os
from importlib.metadata import version as pkg_version

from aiyo.agent.agent import Agent
from aiyo.agent.mode import AgentMode
from aiyo.config import settings
from aiyo.tools.skills import get_skill_loader
from ext.tools import EXT_TOOLS
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .middleware_webui import WebUiDisplayMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=f"{settings.app_name} Server",
        description=f"Web API and UI for {settings.app_name} agent",
        version=pkg_version("aiyo-server"),
    )

    # WebSocket endpoint for chat
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()

        # Create agent with web stream middleware
        web_middleware = WebUiDisplayMiddleware()
        session_id = f"ws-{id(ws):x}"
        agent = Agent(
            id=session_id,
            mode=AgentMode.NORMAL,
            extra_middleware=[web_middleware],
            extra_tools=EXT_TOOLS,
        )
        web_middleware.bind(ws, model_name=agent.model_name, stats=agent.stats)

        agent_task: asyncio.Task[None] | None = None

        try:
            # Check services health
            services = await web_middleware.check_services_health()

            # Get skills list
            skill_loader = get_skill_loader()
            skills = [
                {"name": name, "description": skill_loader.get_skill(name).description}
                for name in skill_loader.list_skills()
            ]

            # Send welcome message
            await ws.send_json(
                {
                    "type": "welcome",
                    "app_name": settings.app_name,
                    "app_tagline": settings.app_tagline,
                    "model": agent.model_name,
                    "version": pkg_version("aiyo-server"),
                    "skills": skills,
                    "status": {
                        "services": services,
                        "agent": {
                            "mode": "normal",
                            "tool_count": len(agent._tools),
                        },
                    },
                }
            )

            while True:
                data = await ws.receive_json()
                msg_type = data.get("type", "chat")

                if msg_type == "chat":
                    text = data.get("text", "").strip()
                    if not text:
                        continue

                    if agent_task and not agent_task.done():
                        continue  # ignore while agent is busy

                    async def run_chat(message: str) -> None:
                        try:
                            await agent.chat(message)
                        except asyncio.CancelledError:
                            await ws.send_json({"type": "cancelled"})
                        except Exception as e:
                            await web_middleware.on_error(e, {"stage": "chat"})

                    agent_task = asyncio.create_task(run_chat(text))

                elif msg_type == "ask_user_response":
                    web_middleware.set_user_response(
                        {
                            "answers": data.get("answers", {}),
                            "annotations": data.get("annotations", {}),
                            "metadata": data.get("metadata", {"source": "ask_user"}),
                        },
                        ask_user_id=data.get("ask_user_id"),
                    )

                elif msg_type == "cancel":
                    if agent_task and not agent_task.done():
                        agent_task.cancel()

                elif msg_type == "reset":
                    agent.reset()
                    await ws.send_json({"type": "reset_done"})

                elif msg_type == "compact":
                    await agent.compact()
                    await ws.send_json({"type": "compact_done"})

        except WebSocketDisconnect:
            if agent_task and not agent_task.done():
                agent_task.cancel()
        except Exception as e:
            try:
                await web_middleware.on_error(e, {"stage": "websocket_handler"})
            except Exception:
                pass
        finally:
            web_middleware.unbind()

    def _get_dist_dir() -> str:
        return os.getenv("AIYO_CLI_DIST_DIR", os.path.join(os.getcwd(), "dist"))

    @app.get("/download/")
    async def list_downloads():
        dist_dir = _get_dist_dir()
        if not os.path.isdir(dist_dir):
            return JSONResponse(content={"files": []})
        files = sorted(f for f in os.listdir(dist_dir) if os.path.isfile(os.path.join(dist_dir, f)))
        return JSONResponse(content={"files": files})

    @app.get("/download/{filename}")
    async def download_file(filename: str):
        # Prevent path traversal
        if "/" in filename or "\\" in filename or filename.startswith("."):
            return JSONResponse(status_code=400, content={"error": "Invalid filename"})
        dist_dir = _get_dist_dir()
        file_path = os.path.join(dist_dir, filename)
        if not os.path.isfile(file_path):
            return JSONResponse(status_code=404, content={"error": "File not found"})
        return FileResponse(file_path, media_type="application/octet-stream", filename=filename)

    # Mount static files for WebUI
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
