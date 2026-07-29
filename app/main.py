from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import fetch_all, fetch_one
from app.migrate import run_migrations
from app.orchestrator import cancel_run, create_run, start_run, unlock_confirmation
from app.protocol import APP_VERSION, PROTOCOL, protocol_hash
from app.storage import StorageClient

settings = get_settings()
settings.validate_web()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("alpaca_138.web")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Alpaca 13.8% Research Lab", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    same_site="lax",
    https_only=True,
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def _authenticated(request: Request) -> bool:
    return request.session.get("user") == settings.app_username


def _require(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")


def _run_context() -> list[dict[str, Any]]:
    runs = fetch_all("select * from research_runs order by created_at desc")
    reports = fetch_all("select * from phase_reports order by created_at desc")
    reports_by_run: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        reports_by_run.setdefault(str(report["run_id"]), []).append(report)
    for run in runs:
        run["reports"] = reports_by_run.get(str(run["id"]), [])
        progress = run.get("progress") or {}
        stages = []
        total_all = completed_all = 0
        for stage, counts in progress.items():
            if stage == "phase" or not isinstance(counts, dict):
                continue
            total = int(counts.get("total") or 0)
            completed = int(counts.get("completed") or 0)
            total_all += total
            completed_all += completed
            stages.append(
                {
                    "name": stage,
                    "label": stage.replace("_", " ").title(),
                    "total": total,
                    "completed": completed,
                    "running": int(counts.get("running") or 0),
                    "queued": int(counts.get("queued") or 0),
                    "failed": int(counts.get("failed") or 0),
                    "pct": round(completed / total * 100, 1) if total else 0,
                }
            )
        run["stage_rows"] = stages
        run["overall_pct"] = round(completed_all / total_all * 100, 1) if total_all else 0
        run["active"] = run["status"] in {"running", "confirmation_running"}
        run["can_unlock"] = (
            run["run_kind"] == "full"
            and run["status"] == "primary_complete"
            and bool(run.get("primary_gate_passed"))
        )
    return runs


@app.get("/health")
def health() -> dict[str, Any]:
    db = "ok"
    migration = None
    try:
        migration = fetch_one("select filename,applied_at from schema_migrations order by applied_at desc limit 1")
    except Exception as exc:  # health must expose database readiness honestly
        db = f"error:{type(exc).__name__}"
    return {
        "status": "ok" if db == "ok" else "degraded",
        "version": APP_VERSION,
        "role": "research_only_no_trading",
        "database": db,
        "latest_migration": migration,
        "protocol_hash": protocol_hash(),
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    valid_user = hmac.compare_digest(username, settings.app_username)
    valid_password = hmac.compare_digest(password, settings.app_password.get_secret_value())
    if not (valid_user and valid_password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Incorrect username or password."}, status_code=401
        )
    request.session["user"] = settings.app_username
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not _authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "runs": _run_context(),
            "version": APP_VERSION,
            "threshold": PROTOCOL["signal"]["threshold_pct"],
            "protocol_hash": protocol_hash(),
            "protocol": PROTOCOL,
            "notice": request.query_params.get("created"),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/api/status")
def api_status(request: Request):
    _require(request)
    return JSONResponse({"version": APP_VERSION, "protocol_hash": protocol_hash(), "runs": _run_context()})


@app.post("/runs/create/{run_kind}")
def create(request: Request, run_kind: str):
    _require(request)
    try:
        run_id = create_run(run_kind)
        start_run(run_id)
    except Exception as exc:
        logger.exception("Run creation failed")
        return RedirectResponse(f"/?error={type(exc).__name__}", status_code=303)
    return RedirectResponse(f"/?created={run_id}", status_code=303)


@app.post("/runs/{run_id}/resume")
def resume(request: Request, run_id: str):
    _require(request)
    start_run(run_id)
    return RedirectResponse("/", status_code=303)


@app.post("/runs/{run_id}/cancel")
def cancel(request: Request, run_id: str):
    _require(request)
    cancel_run(run_id)
    return RedirectResponse("/", status_code=303)


@app.post("/runs/{run_id}/unlock-confirmation")
def unlock(request: Request, run_id: str):
    _require(request)
    unlock_confirmation(run_id)
    return RedirectResponse("/", status_code=303)


@app.get("/runs/{run_id}/reports/{phase}/download")
def report_download(request: Request, run_id: str, phase: str):
    _require(request)
    report = fetch_one(
        "select report_object_path from phase_reports where run_id=%s and phase=%s and status='completed'",
        (run_id, phase),
    )
    if not report or not report.get("report_object_path"):
        raise HTTPException(status_code=404, detail="Report not ready")
    return RedirectResponse(StorageClient().signed_url(report["report_object_path"]), status_code=303)
