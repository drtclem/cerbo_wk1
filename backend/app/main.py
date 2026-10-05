from fastapi import FastAPI

app = FastAPI(title="Cerbo supplement ordering")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
