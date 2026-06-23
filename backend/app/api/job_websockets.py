import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.job_event_bus import close_job_event_subscription, read_job_event, subscribe_job_events


router = APIRouter(tags=["job-websockets"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/jobs/{job_id}")
async def stream_job_events(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    pubsub = None
    forward_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[None] | None = None
    try:
        pubsub = await asyncio.to_thread(subscribe_job_events, job_id)
        forward_task = asyncio.create_task(_forward_job_events(websocket, pubsub))
        receive_task = asyncio.create_task(_wait_for_disconnect(websocket))
        done, pending = await asyncio.wait(
            {forward_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("job_websocket_stream_failed", extra={"job_id": job_id}, exc_info=True)
    finally:
        for task in (forward_task, receive_task):
            if task and not task.done():
                task.cancel()
        if pubsub is not None:
            await asyncio.to_thread(close_job_event_subscription, pubsub, job_id)


async def _forward_job_events(websocket: WebSocket, pubsub) -> None:
    while True:
        event = await asyncio.to_thread(read_job_event, pubsub)
        if event is not None:
            await websocket.send_json(event)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()
