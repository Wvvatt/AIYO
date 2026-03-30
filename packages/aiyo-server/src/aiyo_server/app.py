"""AIYO Server FastAPI application."""

import os

from aiyo.agent.agent import Agent
from aiyo.agent.middleware import MiddlewareChain
from aiyo.agent.mode import AgentMode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .middleware_web import WebStreamMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AIYO Server",
        description="Web API and UI for AIYO agent",
        version="0.1.0",
    )

    # WebSocket endpoint for chat
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()

        # Create agent with web stream middleware
        web_middleware = WebStreamMiddleware()
        web_middleware.bind(ws)

        agent = Agent(mode=AgentMode.READONLY)
        agent.middleware = MiddlewareChain([web_middleware])

        # Send welcome message
        await ws.send_json(
            {
                "type": "welcome",
                "model": agent.model if hasattr(agent, "model") else "default",
                "version": "0.1.0",
            }
        )

        try:
            while True:
                # Receive message from client
                data = await ws.receive_json()
                msg_type = data.get("type", "chat")

                if msg_type == "chat":
                    text = data.get("text", "").strip()
                    if not text:
                        continue

                    try:
                        await agent.chat(text)
                    except Exception as e:
                        await web_middleware.on_error(str(e))

                elif msg_type == "cancel":
                    # Cancel current operation (handled by agent)
                    pass

                elif msg_type == "reset":
                    # Reset conversation context
                    if hasattr(agent, "reset"):
                        agent.reset()
                    await ws.send_json({"type": "reset_done"})

                elif msg_type == "compact":
                    # Compact conversation history
                    if hasattr(agent, "compact"):
                        agent.compact()
                    await ws.send_json({"type": "compact_done"})

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await web_middleware.on_error(f"Server error: {str(e)}")
            except:
                pass
        finally:
            web_middleware.unbind()

    # Mount static files for WebUI
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
