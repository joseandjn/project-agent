from fastapi import APIRouter

from app.api.v1.routes import auth, chat

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(chat.router, tags=["chat"])
