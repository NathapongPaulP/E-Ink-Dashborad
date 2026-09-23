from fastapi import FastAPI
from app.routers import api

app = FastAPI()

app.include_router(api.router)