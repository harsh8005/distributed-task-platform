from fastapi import FastAPI

from app.database import Base, engine
from app.routers.auth import router as auth_router

app = FastAPI(title="Distributed Task Platform")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
