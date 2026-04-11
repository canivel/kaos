"""KAOS Web UI Server — Starlette backend for the agent observability dashboard.

Reads any kaos.db file directly via sqlite3 (read-only).
Multi-project: every endpoint accepts ?db=<path> query param.
Projects list persisted in ~/.kaos/ui_projects.json.

Launch via: kaos ui [--db PATH] [--port 8765]
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import AsyncGenerator

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

PROJECTS_FILE = Path.home() / ".kaos" / "ui_projects.json"
STATIC_DIR = Path(__file__).parent / "static"

# ── Helpers ────────────────────────────────────────────────────────────────

def _db_path(request: Request) -> str:
    return request.query_params.get("db", "./kaos.db")


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, uri=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _rows(db_path: str, sql: str, params=()) -> list[dict]:
    try:
        with _conn(db_path) as conn:
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        raise RuntimeError(f"DB error ({db_path}): {e}") from e


def _one(db_path: str, sql: str, params=()) -> dict | None:
    rows = _rows(db_path, sql, params)
    return rows[0] if rows else None


def _json(data, status=200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def _err(msg: str, status=400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def _load_projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        try:
            return json.loads(PROJECTS_FILE.read_text())
        except Exception:
            pass
    return []


def _save_projects(projects: list[dict]) -> None:
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))


# ── API Handlers ───────────────────────────────────────────────────────────

async def api_stats(request: Request) -> JSONResponse:
    """GET /api/stats?db=PATH — aggregate dashboard stats."""
    db = _db_path(request)
    try:
        agents = _rows(db, """
            SELECT status, COUNT(*) as count
            FROM agents
            GROUP BY status
        """)
        status_counts = {r["status"]: r["count"] for r in agents}

        totals = _one(db, """
            SELECT
                COUNT(*) as total_agents,
                COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END), 0) as running,
                COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) as completed,
                COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) as failed,
                COALESCE(SUM(CASE WHEN status='paused' THEN 1 ELSE 0 END), 0) as paused,
                COALESCE(SUM(CASE WHEN status='killed' THEN 1 ELSE 0 END), 0) as killed,
                COALESCE(SUM(CASE WHEN status='initialized' THEN 1 ELSE 0 END), 0) as initialized
            FROM agents
        """) or {}

        event_count = _one(db, "SELECT COUNT(*) as n FROM events") or {}
        tool_count = _one(db, "SELECT COUNT(*) as n FROM tool_calls") or {}
        token_sum = _one(db, "SELECT COALESCE(SUM(token_count),0) as n FROM tool_calls") or {}

        return _json({
            "agents": totals,
            "events": event_count.get("n", 0),
            "tool_calls": tool_count.get("n", 0),
            "tokens": token_sum.get("n", 0),
        })
    except Exception as e:
        return _err(str(e), 500)


async def api_agents(request: Request) -> JSONResponse:
    """GET /api/agents?db=PATH — all agents with stats for graph."""
    db = _db_path(request)
    try:
        rows = _rows(db, """
            SELECT
                a.agent_id,
                a.name,
                a.parent_id,
                a.status,
                a.config,
                a.metadata,
                a.created_at,
                a.last_heartbeat,
                COALESCE(fc.cnt, 0) AS file_count,
                COALESCE(tc.cnt, 0) AS tool_call_count,
                COALESCE(tc.tokens, 0) AS token_count,
                COALESCE(ec.cnt, 0) AS event_count,
                strftime('%Y-%m-%dT%H:%M', a.created_at) AS batch_minute
            FROM agents a
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt
                FROM files WHERE deleted=0
                GROUP BY agent_id
            ) fc ON fc.agent_id = a.agent_id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt, COALESCE(SUM(token_count),0) as tokens
                FROM tool_calls
                GROUP BY agent_id
            ) tc ON tc.agent_id = a.agent_id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt
                FROM events
                GROUP BY agent_id
            ) ec ON ec.agent_id = a.agent_id
            ORDER BY a.created_at DESC
        """)
        # Parse JSON fields
        for r in rows:
            for field in ("config", "metadata"):
                if r.get(field):
                    try:
                        r[field] = json.loads(r[field])
                    except Exception:
                        r[field] = {}

        # Compute batch_id: group agents by same-minute creation into batches of size >= 2
        from collections import Counter
        minute_counts = Counter(r["batch_minute"] for r in rows if r.get("batch_minute"))
        batch_minutes = {m for m, n in minute_counts.items() if n >= 2}
        for r in rows:
            m = r.get("batch_minute")
            r["batch_id"] = m if m in batch_minutes else None

        return _json(rows)
    except Exception as e:
        return _err(str(e), 500)


async def api_agent_detail(request: Request) -> JSONResponse:
    """GET /api/agents/{id}?db=PATH — single agent detail."""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        row = _one(db, """
            SELECT
                a.agent_id, a.name, a.parent_id, a.status,
                a.config, a.metadata, a.created_at, a.last_heartbeat, a.pid,
                COALESCE(fc.cnt, 0) AS file_count,
                COALESCE(tc.cnt, 0) AS tool_call_count,
                COALESCE(tc.tokens, 0) AS token_count,
                COALESCE(ec.cnt, 0) AS event_count
            FROM agents a
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt FROM files WHERE deleted=0 GROUP BY agent_id
            ) fc ON fc.agent_id = a.agent_id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt, COALESCE(SUM(token_count),0) as tokens
                FROM tool_calls GROUP BY agent_id
            ) tc ON tc.agent_id = a.agent_id
            LEFT JOIN (
                SELECT agent_id, COUNT(*) as cnt FROM events GROUP BY agent_id
            ) ec ON ec.agent_id = a.agent_id
            WHERE a.agent_id = ?
        """, (agent_id,))
        if not row:
            return _err("Agent not found", 404)
        for field in ("config", "metadata"):
            if row.get(field):
                try:
                    row[field] = json.loads(row[field])
                except Exception:
                    row[field] = {}
        return _json(row)
    except Exception as e:
        return _err(str(e), 500)


async def api_agent_events(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/events?db=PATH&limit=100&since=EVENT_ID"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    limit = int(request.query_params.get("limit", 200))
    since = request.query_params.get("since")
    try:
        if since:
            rows = _rows(db, """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE agent_id=? AND event_id > ?
                ORDER BY event_id ASC LIMIT ?
            """, (agent_id, int(since), limit))
        else:
            rows = _rows(db, """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE agent_id=?
                ORDER BY event_id DESC LIMIT ?
            """, (agent_id, limit))
            rows.reverse()
        for r in rows:
            if r.get("payload"):
                try:
                    r["payload"] = json.loads(r["payload"])
                except Exception:
                    pass
        return _json(rows)
    except Exception as e:
        return _err(str(e), 500)


async def api_agent_tool_calls(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/tool_calls?db=PATH — nested tool call tree."""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        rows = _rows(db, """
            SELECT call_id, agent_id, tool_name, input, output, status,
                   started_at, completed_at, duration_ms, token_count,
                   parent_call_id, error_message
            FROM tool_calls WHERE agent_id=?
            ORDER BY started_at ASC
        """, (agent_id,))
        for r in rows:
            for field in ("input", "output"):
                if r.get(field):
                    try:
                        r[field] = json.loads(r[field])
                    except Exception:
                        pass
        # Build nested tree
        by_id = {r["call_id"]: {**r, "children": []} for r in rows}
        roots = []
        for r in by_id.values():
            pid = r.get("parent_call_id")
            if pid and pid in by_id:
                by_id[pid]["children"].append(r)
            else:
                roots.append(r)
        return _json(roots)
    except Exception as e:
        return _err(str(e), 500)


async def api_agent_checkpoints(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/checkpoints?db=PATH"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    try:
        rows = _rows(db, """
            SELECT checkpoint_id, agent_id, label, created_at, event_id, metadata
            FROM checkpoints WHERE agent_id=?
            ORDER BY created_at ASC
        """, (agent_id,))
        for r in rows:
            if r.get("metadata"):
                try:
                    r["metadata"] = json.loads(r["metadata"])
                except Exception:
                    r["metadata"] = {}
        return _json(rows)
    except Exception as e:
        return _err(str(e), 500)


async def api_agent_files(request: Request) -> JSONResponse:
    """GET /api/agents/{id}/files?db=PATH&path=/"""
    db = _db_path(request)
    agent_id = request.path_params["id"]
    path = request.query_params.get("path", "/")
    # Normalize path
    if not path.startswith("/"):
        path = "/" + path
    try:
        # List direct children of path
        if path == "/":
            prefix = "/"
            rows = _rows(db, """
                SELECT file_id, path, is_dir, size, modified_at, version, content_hash
                FROM files
                WHERE agent_id=? AND deleted=0
                  AND (
                    path = '/' OR
                    (path LIKE '/_%' AND INSTR(SUBSTR(path, 2), '/') = 0)
                  )
                ORDER BY is_dir DESC, path ASC
            """, (agent_id,))
        else:
            # Children under path/
            prefix = path.rstrip("/") + "/"
            plen = len(prefix)
            rows = _rows(db, """
                SELECT file_id, path, is_dir, size, modified_at, version, content_hash
                FROM files
                WHERE agent_id=? AND deleted=0
                  AND path LIKE ? ESCAPE '\\'
                ORDER BY is_dir DESC, path ASC
            """, (agent_id, prefix.replace("%", "\\%").replace("_", "\\_") + "%"))
            # Filter to direct children only (no deeper nesting)
            def is_direct(p):
                rel = p[plen:]
                return rel and "/" not in rel
            rows = [r for r in rows if is_direct(r["path"])]

        return _json({
            "path": path,
            "entries": rows,
        })
    except Exception as e:
        return _err(str(e), 500)


async def api_projects_get(request: Request) -> JSONResponse:
    """GET /api/projects — list known projects."""
    projects = _load_projects()
    # Enrich with existence check
    for p in projects:
        p["exists"] = Path(p["path"]).exists()
    return _json(projects)


async def api_projects_post(request: Request) -> JSONResponse:
    """POST /api/projects — add a project. Body: {path: str, name?: str}"""
    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")
    db_path = body.get("path", "").strip()
    if not db_path:
        return _err("path is required")
    db_path = str(Path(db_path).resolve())
    projects = _load_projects()
    # Deduplicate
    if any(p["path"] == db_path for p in projects):
        return _json({"ok": True, "projects": projects})
    name = body.get("name") or Path(db_path).parent.name or db_path
    projects.insert(0, {"path": db_path, "name": name, "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    _save_projects(projects)
    return _json({"ok": True, "projects": projects})


# ── SSE Stream ────────────────────────────────────────────────────────────

async def _event_generator(db: str) -> AsyncGenerator[bytes, None]:
    """Poll DB every 2s, emit new events and agent status changes."""
    last_event_id = 0
    last_agent_snapshot: dict[str, str] = {}

    # Get current max event_id
    try:
        row = _one(db, "SELECT COALESCE(MAX(event_id),0) as m FROM events")
        last_event_id = row["m"] if row else 0
    except Exception:
        pass

    while True:
        try:
            # New events
            new_events = _rows(db, """
                SELECT event_id, agent_id, event_type, payload, timestamp
                FROM events WHERE event_id > ?
                ORDER BY event_id ASC LIMIT 50
            """, (last_event_id,))

            for ev in new_events:
                last_event_id = ev["event_id"]
                if ev.get("payload"):
                    try:
                        ev["payload"] = json.loads(ev["payload"])
                    except Exception:
                        pass
                data = json.dumps({"type": "new_event", "event": ev})
                yield f"data: {data}\n\n".encode()

            # Agent status changes
            agents = _rows(db, "SELECT agent_id, status, name, last_heartbeat FROM agents")
            for a in agents:
                aid = a["agent_id"]
                if last_agent_snapshot.get(aid) != a["status"]:
                    last_agent_snapshot[aid] = a["status"]
                    data = json.dumps({"type": "agent_update", "agent": a})
                    yield f"data: {data}\n\n".encode()

        except Exception as e:
            data = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {data}\n\n".encode()

        await asyncio.sleep(2)


async def api_events_stream(request: Request) -> StreamingResponse:
    """GET /api/events/stream?db=PATH — SSE stream."""
    db = _db_path(request)

    async def generator():
        # Send initial ping
        yield b"data: {\"type\": \"connected\"}\n\n"
        async for chunk in _event_generator(db):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── App ────────────────────────────────────────────────────────────────────

def create_app() -> Starlette:
    routes = [
        Route("/api/stats", api_stats),
        Route("/api/agents", api_agents),
        Route("/api/agents/{id}", api_agent_detail),
        Route("/api/agents/{id}/events", api_agent_events),
        Route("/api/agents/{id}/tool_calls", api_agent_tool_calls),
        Route("/api/agents/{id}/checkpoints", api_agent_checkpoints),
        Route("/api/agents/{id}/files", api_agent_files),
        Route("/api/events/stream", api_events_stream),
        Route("/api/projects", api_projects_get, methods=["GET"]),
        Route("/api/projects", api_projects_post, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True)),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()


def run(host: str = "127.0.0.1", port: int = 8765, db: str = "./kaos.db") -> None:
    """Launch the UI server. Called from CLI."""
    import uvicorn

    # Auto-register the project
    db_abs = str(Path(db).resolve())
    projects = _load_projects()
    if not any(p["path"] == db_abs for p in projects):
        name = Path(db_abs).parent.name or db_abs
        projects.insert(0, {
            "path": db_abs,
            "name": name,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_projects(projects)

    print(f"  KAOS UI  →  http://{host}:{port}/?db={db_abs}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
