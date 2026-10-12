from fastapi import APIRouter

from app.api.v2.routes import chat

api_router_v2 = APIRouter()
api_router_v2.include_router(chat.router, tags=["chat v2"])
