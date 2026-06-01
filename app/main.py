from fastapi import FastAPI

app = FastAPI(title="Distributed Task Platform")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
