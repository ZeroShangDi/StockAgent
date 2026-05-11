"""
用户 API
"""

from typing import Optional, List, Literal
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from .auth import get_current_user_id


router = APIRouter()


# ==================== 模型 ====================


class NotificationChannel(BaseModel):
    """用户通知机器人"""
    channel_id: str
    name: str
    provider: Literal["wecom", "dingtalk"]
    webhook: str
    created_at: datetime
    updated_at: datetime


class UserInfo(BaseModel):
    """用户信息"""
    user_id: str
    username: str
    email: str
    nickname: Optional[str]
    avatar: Optional[str]
    watchlist: List[str]
    preferences: dict
    notification_channels: List[NotificationChannel]
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    """更新用户请求"""
    nickname: Optional[str] = None
    avatar: Optional[str] = None


class UserPreferences(BaseModel):
    """用户偏好"""
    theme: Optional[str] = None
    language: Optional[str] = None
    notification_enabled: Optional[bool] = None


class NotificationChannelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    provider: Literal["wecom", "dingtalk"]
    webhook: str = Field(..., min_length=10)


class NotificationChannelUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    provider: Optional[Literal["wecom", "dingtalk"]] = None
    webhook: Optional[str] = Field(default=None, min_length=10)


def _normalize_notification_channel(raw: dict) -> NotificationChannel:
    created_at = raw.get("created_at")
    updated_at = raw.get("updated_at")
    return NotificationChannel(
        channel_id=str(raw.get("channel_id") or ""),
        name=str(raw.get("name") or ""),
        provider=str(raw.get("provider") or "wecom"),
        webhook=str(raw.get("webhook") or ""),
        created_at=created_at if isinstance(created_at, datetime) else datetime.utcnow(),
        updated_at=updated_at if isinstance(updated_at, datetime) else datetime.utcnow(),
    )


def _normalize_webhook(provider: str, webhook: str) -> str:
    value = str(webhook or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Webhook 不能为空")
    if provider == "wecom" and "qyapi.weixin.qq.com" not in value:
        raise HTTPException(status_code=400, detail="企业微信 Webhook 格式不正确")
    if provider == "dingtalk" and "oapi.dingtalk.com" not in value:
        raise HTTPException(status_code=400, detail="钉钉 Webhook 格式不正确")
    return value


# ==================== API 端点 ====================


@router.get("/me", response_model=UserInfo)
async def get_current_user(user_id: str = Depends(get_current_user_id)):
    """获取当前用户信息"""
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"password_hash": 0},
    )
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        nickname=user.get("nickname"),
        avatar=user.get("avatar"),
        watchlist=user.get("watchlist", []),
        preferences=user.get("preferences", {}),
        notification_channels=[
            _normalize_notification_channel(item)
            for item in user.get("notification_channels", [])
            if isinstance(item, dict)
        ],
        is_admin=user.get("is_admin", False),
    )


@router.put("/me")
async def update_user(
    body: UpdateUserRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新用户信息"""
    update_data = {}
    
    if body.nickname is not None:
        update_data["nickname"] = body.nickname
    if body.avatar is not None:
        update_data["avatar"] = body.avatar
    
    if update_data:
        await mongo_manager.update_one(
            "users",
            {"user_id": user_id},
            {"$set": update_data},
        )
    
    return {"message": "更新成功"}


# ==================== 自选股 ====================


@router.get("/me/watchlist", response_model=List[str])
async def get_watchlist(user_id: str = Depends(get_current_user_id)):
    """获取自选股列表"""
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"watchlist": 1},
    )
    
    return user.get("watchlist", []) if user else []


@router.post("/me/watchlist")
async def add_to_watchlist(
    ts_code: str,
    user_id: str = Depends(get_current_user_id),
):
    """添加自选股"""
    await mongo_manager.update_one(
        "users",
        {"user_id": user_id},
        {"$addToSet": {"watchlist": ts_code}},
    )
    
    return {"message": f"已添加 {ts_code}"}


@router.delete("/me/watchlist/{ts_code}")
async def remove_from_watchlist(
    ts_code: str,
    user_id: str = Depends(get_current_user_id),
):
    """移除自选股"""
    await mongo_manager.update_one(
        "users",
        {"user_id": user_id},
        {"$pull": {"watchlist": ts_code}},
    )
    
    return {"message": f"已移除 {ts_code}"}


# ==================== 偏好设置 ====================


@router.put("/me/preferences")
async def update_preferences(
    body: UserPreferences,
    user_id: str = Depends(get_current_user_id),
):
    """更新偏好设置"""
    update_data = {}
    
    if body.theme is not None:
        update_data["preferences.theme"] = body.theme
    if body.language is not None:
        update_data["preferences.language"] = body.language
    if body.notification_enabled is not None:
        update_data["preferences.notification_enabled"] = body.notification_enabled
    
    if update_data:
        await mongo_manager.update_one(
            "users",
            {"user_id": user_id},
            {"$set": update_data},
        )
    
    return {"message": "设置已更新"}


# ==================== 通知机器人 ====================


@router.get("/me/notification-channels", response_model=List[NotificationChannel])
async def get_notification_channels(user_id: str = Depends(get_current_user_id)):
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"notification_channels": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return [
        _normalize_notification_channel(item)
        for item in user.get("notification_channels", [])
        if isinstance(item, dict)
    ]


@router.post("/me/notification-channels", response_model=NotificationChannel, status_code=201)
async def create_notification_channel(
    body: NotificationChannelCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"notification_channels": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    now = datetime.utcnow()
    channel = NotificationChannel(
        channel_id=uuid.uuid4().hex,
        name=body.name.strip(),
        provider=body.provider,
        webhook=_normalize_webhook(body.provider, body.webhook),
        created_at=now,
        updated_at=now,
    )

    channels = [
        item
        for item in user.get("notification_channels", [])
        if isinstance(item, dict)
    ]
    channels.append(channel.model_dump())

    await mongo_manager.update_one(
        "users",
        {"user_id": user_id},
        {"$set": {"notification_channels": channels}},
    )
    return channel


@router.put("/me/notification-channels/{channel_id}", response_model=NotificationChannel)
async def update_notification_channel(
    channel_id: str,
    body: NotificationChannelUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"notification_channels": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    channels = [
        item
        for item in user.get("notification_channels", [])
        if isinstance(item, dict)
    ]
    updated_channel: Optional[NotificationChannel] = None

    for item in channels:
        if str(item.get("channel_id") or "") != channel_id:
            continue
        provider = body.provider or str(item.get("provider") or "wecom")
        webhook = item.get("webhook") or ""
        if body.webhook is not None:
            webhook = _normalize_webhook(provider, body.webhook)
        item["provider"] = provider
        item["name"] = body.name.strip() if body.name is not None else str(item.get("name") or "")
        item["webhook"] = webhook
        item["updated_at"] = datetime.utcnow()
        updated_channel = _normalize_notification_channel(item)
        break

    if updated_channel is None:
        raise HTTPException(status_code=404, detail="通知机器人不存在")

    await mongo_manager.update_one(
        "users",
        {"user_id": user_id},
        {"$set": {"notification_channels": channels}},
    )
    return updated_channel


@router.delete("/me/notification-channels/{channel_id}")
async def delete_notification_channel(
    channel_id: str,
    user_id: str = Depends(get_current_user_id),
):
    user = await mongo_manager.find_one(
        "users",
        {"user_id": user_id},
        projection={"notification_channels": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    channels = [
        item
        for item in user.get("notification_channels", [])
        if isinstance(item, dict) and str(item.get("channel_id") or "") != channel_id
    ]

    await mongo_manager.update_one(
        "users",
        {"user_id": user_id},
        {"$set": {"notification_channels": channels}},
    )
    return {"message": "通知机器人已删除"}
