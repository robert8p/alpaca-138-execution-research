from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Alpaca 13.8% Research Lab — Retired", version="retired-2026-09-03")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "retired",
        "database": "not_initialised",
        "replacement": "canonical market-data-leading-indicators project",
    }


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html><head><title>Research service retired</title></head>
        <body><h1>Research service retired</h1>
        <p>The completed A138 research artefacts have been preserved in the canonical investment database.</p>
        <p>This endpoint no longer initialises or depends on the legacy Supabase project.</p></body></html>""",
        status_code=410,
    )


@app.get("/{path:path}")
def retired(path: str) -> JSONResponse:
    return JSONResponse(
        {
            "status": "retired",
            "path": path,
            "database": "not_initialised",
            "replacement": "canonical market-data-leading-indicators project",
        },
        status_code=410,
    )
