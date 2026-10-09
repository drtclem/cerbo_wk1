"""T20: production ASGI app mounts API under /api and serves the SPA."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.serve import create_serve_app


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>Cerbo</title></head>"
        "<body><div id='root'>spa</div></body></html>",
        encoding="utf-8",
    )
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    return dist


def test_serve_app_runs_api_lifespan_and_spa_fallback(tmp_path: Path) -> None:
    application = create_serve_app(
        database_url=f"sqlite:///{tmp_path / 'serve.db'}",
        dist_dir=_dist(tmp_path),
        demo_mode=False,
    )
    with TestClient(application) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        users = client.get("/api/users")
        assert users.status_code == 200
        names = {row["name"] for row in users.json()}
        assert names == {
            "Dr. Maya Patel",
            "Jane Doe",
            "Sam Lee",
            "Cerbo Admin",
        }

        deep = client.get("/orders/3")
        assert deep.status_code == 200
        assert "text/html" in deep.headers["content-type"]
        assert "spa" in deep.text
        assert "<title>Cerbo</title>" in deep.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text


def test_serve_app_exposes_demo_reset_under_api_when_demo_mode_is_on(
    tmp_path: Path,
) -> None:
    application = create_serve_app(
        database_url=f"sqlite:///{tmp_path / 'serve-demo.db'}",
        dist_dir=_dist(tmp_path),
        demo_mode=True,
    )
    with TestClient(application) as client:
        reset = client.post("/api/demo/reset")
        assert reset.status_code == 204
