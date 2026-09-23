from fastapi import FastAPI
from app.routers import projects, steps

app = FastAPI()

app.include_router(projects.router)
app.include_router(steps.router)