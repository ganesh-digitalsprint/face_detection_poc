from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.manager import manager as ws_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "message": "Live alert feed connected."})
        while True:
            # We don't expect inbound messages, but keep the receive loop
            # alive so disconnects are detected promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)
