"""
智能工作台 API。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.assistant import assistant_service

from .auth import get_current_user_id


router = APIRouter(prefix="/assistant", tags=["Assistant"])


class AssistantConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="会话标题")


class AssistantMessageStreamRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=6000, description="用户输入")


@router.get("/conversations")
async def list_assistant_conversations(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "items": await assistant_service.list_conversations(user_id=user_id, limit=max(1, min(limit, 50))),
    }


@router.post("/conversations")
async def create_assistant_conversation(
    body: AssistantConversationCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return await assistant_service.create_conversation(user_id=user_id, title=body.title)


@router.get("/conversations/{conversation_id}")
async def get_assistant_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    try:
        return await assistant_service.get_conversation(user_id=user_id, conversation_id=conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_assistant_message(
    conversation_id: str,
    body: AssistantMessageStreamRequest,
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse:
    async def event_stream():
        try:
            async for event in assistant_service.stream_message(
                user_id=user_id,
                conversation_id=conversation_id,
                content=body.content,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except ValueError as exc:
            payload = {"type": "error", "detail": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            payload = {"type": "error", "detail": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/artifacts/{artifact_id}")
async def get_assistant_artifact(
    artifact_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    artifact = await assistant_service.get_artifact(user_id=user_id, artifact_id=artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
