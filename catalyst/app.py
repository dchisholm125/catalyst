"""Local-first alpha: public reading, invited humans, scoped agent credentials."""
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
import difflib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import domain, workshop
from .db import canonical, connect, digest, initialize, uid
from .models import (BudgetInput, ContributionInput, DraftInput, FeedbackInput, IdeaInput,
                     ReactionInput, ReasonInput, ResultInput, ReviewInput, TaskInput, ClaimInput)

ROOT = Path(__file__).parent


@dataclass(frozen=True)
class Settings:
    database: str = "data/catalyst.db"
    secure_cookies: bool = False
    cadence_seconds: int = 60
    mutation_limit: int = 120
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")

    @classmethod
    def environment(cls):
        return cls(database=os.getenv("CATALYST_DB", "data/catalyst.db"),
                   secure_cookies=os.getenv("CATALYST_SECURE_COOKIES", "0") == "1",
                   cadence_seconds=max(0, int(os.getenv("CATALYST_CADENCE_SECONDS", "60"))),
                   allowed_hosts=tuple(os.getenv("CATALYST_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")))


def create_app(settings: Settings | None = None):
    settings = settings or Settings.environment()

    @asynccontextmanager
    async def lifespan(app):
        initialize(settings.database)
        yield

    app = FastAPI(title="Catalyst", version="0.4.0", lifespan=lifespan,
                  description="Human-directed living ideas. Consumer subscription integrations are not connected.")
    app.state.settings = settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")
    templates.env.filters["pretty"] = lambda value: json.dumps(value, indent=2, ensure_ascii=False)
    templates.env.filters["when"] = lambda timestamp: time.strftime("%b %d, %Y · %H:%M UTC", time.gmtime(timestamp)) if timestamp else "Not published"
    templates.env.globals.update(roles=workshop.ROLES, origins=workshop.ORIGINS)
    rates = OrderedDict()

    @app.middleware("http")
    async def guardrails(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # A single-process guard for a local alpha, not a distributed abuse service.
            key = (request.client.host if request.client else "unknown", request.url.path == "/login")
            now = time.monotonic()
            bucket = [t for t in rates.pop(key, []) if now - t < 60]
            limit = 10 if key[1] else settings.mutation_limit
            if len(bucket) >= limit:
                rates[key] = bucket
                return JSONResponse({"detail": "Too many requests; retry after one minute"}, 429, headers={"Retry-After": "60"})
            rates[key] = bucket + [now]
            if len(rates) > 2048:
                rates.popitem(last=False)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({"detail": "Request exceeds 64 KiB"}, 413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        # Swagger uses its own CDN assets; application pages load only same-origin assets.
        if request.url.path not in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Native form POSTs use Origin: null under no-referrer, which our
        # login origin check correctly rejects. Preserve same-origin metadata
        # while still withholding referrers from external sites.
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    def maybe_actor(request: Request):
        authorization = request.headers.get("Authorization", "")
        bearer = authorization.startswith("Bearer ")
        token = authorization[7:] if bearer else request.cookies.get("catalyst_session", "")
        if not token or len(token) > 100:
            return None
        with connect(settings.database) as con:
            row = con.execute("SELECT a.*,c.kind AS credential_kind,c.csrf FROM credentials c "
                              "JOIN actors a ON a.id=c.actor_id WHERE c.digest=? AND c.expires>? AND a.active=1",
                              (digest(token), time.time())).fetchone()
            if not row:
                return None
            actor = dict(row)
            actor['_credential_digest'] = digest(token)
            if bearer and actor["credential_kind"] != "agent":
                return None
            if not bearer and actor["credential_kind"] != "session":
                return None
            if actor["kind"] == "agent":
                owner = con.execute("SELECT active FROM actors WHERE id=?", (actor["owner_id"],)).fetchone()
                if not owner or not owner["active"]:
                    return None
        return actor

    def authenticated(request: Request):
        actor = maybe_actor(request)
        if actor is None:
            raise HTTPException(401, "Sign in with an invitation or use a scoped Catalyst agent token")
        if actor["credential_kind"] == "session" and request.method not in ("GET", "HEAD"):
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), actor["csrf"]):
                raise HTTPException(403, "Missing or invalid CSRF token")
        return actor

    def human(actor=Depends(authenticated)):
        if actor["kind"] != "human" or actor["credential_kind"] != "session":
            raise HTTPException(403, "This action belongs to signed-in human accounts")
        return actor

    def reviewer(actor=Depends(human)):
        if not actor["reviewer"]:
            raise HTTPException(403, "Human reviewer permission required")
        return actor

    def agent(actor=Depends(authenticated)):
        if actor["kind"] != "agent":
            raise HTTPException(403, "Scoped agent credential required")
        return actor

    def page(request, name, **values):
        return templates.TemplateResponse(request=request, name=name,
                                          context={"actor": maybe_actor(request), **values})

    @app.get("/healthz")
    def health():
        with connect(settings.database) as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": "0.3.0", "provider_connected": False}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = "", kind: str = "", origin: str = "", sort: str = "newest"):
        q = q[:160]
        if kind not in ("", "reflection", "catalyst", "claim") or origin not in ("", *workshop.ORIGINS):
            raise HTTPException(422, "Unknown idea type or origin")
        if sort not in ("newest", "oldest"):
            raise HTTPException(422, "Unknown sort order")
        order = "DESC" if sort == "newest" else "ASC"
        with connect(settings.database) as con:
            rows = con.execute("SELECT i.*,COALESCE(o.origin_kind,'unspecified') AS origin_kind FROM ideas i "
                "LEFT JOIN idea_origins o ON o.idea_id=i.id WHERE i.title LIKE ? AND (?='' OR i.kind=?) "
                "AND (?='' OR COALESCE(o.origin_kind,'unspecified')=?) ORDER BY i.created " + order + ",i.id LIMIT 50",
                (f"%{q}%", kind, kind, origin, origin)).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["synthesis"] = json.loads(con.execute("SELECT body FROM revisions WHERE id=?", (item["head_id"],)).fetchone()[0])
                item["metrics"] = domain.metrics(domain.context(con, item["id"]))
                items.append(item)
        return page(request, "index.html", ideas=items, q=q, kind=kind, origin=origin, sort=sort)

    @app.get("/ideas/{idea_id}", response_class=HTMLResponse)
    def idea_page(request: Request, idea_id: str, view: str = "synthesis"):
        if view not in ("synthesis", "dissent", "discussion", "development", "investigations"):
            raise HTTPException(422, "Unknown idea section")
        with connect(settings.database) as con:
            item = domain.idea(con, idea_id)
            current = dict(con.execute("SELECT * FROM revisions WHERE id=?", (item["head_id"],)).fetchone())
            ctx = domain.context(con, idea_id)
            history = [dict(r) for r in con.execute("SELECT r.*,a.name AS author FROM revisions r JOIN actors a ON a.id=r.author_id "
                                                   "WHERE r.idea_id=? ORDER BY r.created DESC", (idea_id,))]
            tasks = workshop.tasks_for_idea(con, idea_id)
            label = con.execute("SELECT origin_kind FROM idea_origins WHERE idea_id=?", (idea_id,)).fetchone()
            item["origin_kind"] = label[0] if label else "unspecified"
            agenda_link = con.execute("SELECT signal_id FROM signal_links WHERE idea_id=?", (idea_id,)).fetchone()
            return page(request, "idea.html", idea=item, current=current, synthesis=json.loads(current["body"]),
                        ctx=ctx, metrics=domain.metrics(ctx), history=history, tasks=tasks,
                        draft_template=domain.draft_template(con, idea_id), cadence=settings.cadence_seconds, view=view,
                        agenda_signal=agenda_link[0] if agenda_link else None)

    @app.get("/revisions/{revision_id}", response_class=HTMLResponse)
    def revision_page(request: Request, revision_id: str):
        with connect(settings.database) as con:
            rev = domain.require(con.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone())
            item = domain.idea(con, rev["idea_id"])
            old = con.execute("SELECT body FROM revisions WHERE id=?", (rev["base_id"],)).fetchone()
            before = json.dumps(json.loads(old[0]), indent=2, ensure_ascii=False) if old else "{}"
            after = json.dumps(json.loads(rev["body"]), indent=2, ensure_ascii=False)
            diff = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile="Previous synthesis", tofile="Proposed synthesis", lineterm=""))
            return page(request, "revision.html", rev=rev, idea=item, diff=diff,
                        body=json.loads(rev["body"]), snapshot=json.loads(rev["context"]))

    @app.get("/contribute", response_class=HTMLResponse)
    def contribute_page(request: Request):
        actor = maybe_actor(request)
        budget = None
        if actor and actor["kind"] == "human":
            with connect(settings.database) as con:
                budget = domain.budget_status(con, actor["id"])
        return page(request, "contribute.html", budget=budget)

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        return page(request, "about.html")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return page(request, "login.html")

    @app.post("/login")
    async def login(request: Request):
        # Reject cross-origin login as well as cross-origin authenticated mutations.
        origin = request.headers.get("Origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin sign-in rejected")
        if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            raise HTTPException(415, "Use the sign-in form")
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
        token = form.get("token", [""])[0]
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with connect(settings.database, True) as con:
            invitation = con.execute("SELECT c.actor_id FROM credentials c JOIN actors a ON a.id=c.actor_id "
                                     "WHERE c.digest=? AND c.kind='invite' AND c.expires>? AND a.kind='human' AND a.active=1",
                                     (digest(token), time.time())).fetchone()
            if not invitation:
                raise HTTPException(401, "Invalid, expired, or already used invitation")
            con.execute("DELETE FROM credentials WHERE digest=?", (digest(token),))
            con.execute("INSERT INTO credentials VALUES (?,?,'session',?,?)",
                        (digest(session), invitation["actor_id"], time.time() + 8 * 3600, csrf))
        response = RedirectResponse("/", 303)
        response.set_cookie("catalyst_session", session, httponly=True, samesite="strict",
                            secure=settings.secure_cookies, max_age=8 * 3600)
        return response

    @app.post("/api/logout")
    def logout(request: Request, actor=Depends(human)):
        with connect(settings.database, True) as con:
            con.execute("DELETE FROM credentials WHERE digest=?", (digest(request.cookies.get("catalyst_session", "")),))
        response = JSONResponse({"ok": True})
        response.delete_cookie("catalyst_session")
        return response

    @app.get("/api/me")
    def me(actor=Depends(authenticated)):
        return {k: actor[k] for k in ("id", "name", "kind", "reviewer", "owner_id", "csrf")}

    @app.get("/api/ideas")
    def list_ideas(offset: int = 0, limit: int = 25):
        with connect(settings.database) as con:
            return [dict(r) for r in con.execute("SELECT * FROM ideas ORDER BY created,id LIMIT ? OFFSET ?",
                                                (max(1, min(limit, 100)), max(0, offset)))]

    @app.post("/api/ideas", status_code=201)
    def new_idea(data: IdeaInput, actor=Depends(reviewer)):
        with connect(settings.database, True) as con:
            return {"id": domain.create_idea(con, data, actor["id"])}

    @app.get("/api/ideas/{idea_id}")
    def read_idea(idea_id: str):
        with connect(settings.database) as con:
            item = domain.idea(con, idea_id)
            rev = dict(con.execute("SELECT * FROM revisions WHERE id=?", (item["head_id"],)).fetchone())
            ctx = domain.context(con, idea_id)
            return {**item, "synthesis": json.loads(rev["body"]), "context": ctx,
                    "metrics": domain.metrics(ctx), "draft_template": domain.draft_template(con, idea_id)}

    @app.post("/api/ideas/{idea_id}/contributions", status_code=201)
    def contribute(idea_id: str, data: ContributionInput, actor=Depends(authenticated)):
        with connect(settings.database, True) as con:
            from .agent_management import require_work
            require_work(con, actor)
            return {"id": domain.add_contribution(con, idea_id, data, actor["id"])}

    @app.put("/api/ideas/{idea_id}/reaction")
    def react(idea_id: str, data: ReactionInput, actor=Depends(human)):
        with connect(settings.database, True) as con:
            current = domain.idea(con, idea_id)
            if data.revision_id != current["head_id"]:
                raise HTTPException(409, "You are viewing an old revision. Read HEAD before reacting.")
            con.execute("INSERT INTO reactions VALUES (?,?,?,?,?) ON CONFLICT(actor_id,revision_id) "
                        "DO UPDATE SET worth=excluded.worth,stance=excluded.stance,explore=excluded.explore",
                        (actor["id"], data.revision_id, data.worth, data.stance, int(data.explore)))
            return domain.metrics(domain.context(con, idea_id))

    @app.post("/api/ideas/{idea_id}/drafts", status_code=201)
    def draft(idea_id: str, data: DraftInput, actor=Depends(authenticated)):
        with connect(settings.database, True) as con:
            from .agent_management import require_work
            require_work(con, actor)
            return {"id": domain.create_draft(con, idea_id, data, actor["id"])}

    @app.post("/api/revisions/{revision_id}/review")
    def review(revision_id: str, data: ReviewInput, actor=Depends(reviewer)):
        with connect(settings.database, True) as con:
            domain.review_draft(con, revision_id, data, actor["id"], settings.cadence_seconds)
            return {"status": "published" if data.decision == "publish" else "rejected"}

    @app.post("/api/contributions/{reply_id}/recognize")
    def recognize(reply_id: str, data: ReasonInput, actor=Depends(reviewer)):
        with connect(settings.database, True) as con:
            domain.recognize_exchange(con, reply_id, actor["id"], data.reason)
            return {"recognized": True}

    @app.get("/api/me/budget")
    def budget(actor=Depends(human)):
        with connect(settings.database) as con:
            return domain.budget_status(con, actor["id"])

    @app.put("/api/me/budget")
    def save_budget(data: BudgetInput, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return domain.set_budget(con, actor["id"], data)

    @app.post("/api/ideas/{idea_id}/tasks", status_code=201)
    def task(idea_id: str, data: TaskInput, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return {"id": workshop.queue_task(con, idea_id, data, actor)}

    @app.post("/api/tasks/claim")
    def claim(data: ClaimInput | None = None, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return domain.claim_task(con, actor, data.roles if data else None)

    @app.post("/api/tasks/{task_id}/complete")
    def complete(task_id: str, data: ResultInput, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return domain.complete_task(con, task_id, data, actor)

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel(task_id: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            row = domain.require(con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            if not actor["reviewer"] and row["creator_id"] != actor["id"]:
                raise HTTPException(403, "Only the task requester or a reviewer can cancel it")
            if row["status"] == "completed":
                raise HTTPException(409, "Completed work cannot be retroactively canceled")
            con.execute("UPDATE tasks SET status='cancelled',lease_digest=NULL WHERE id=?", (task_id,))
            return {"status": "cancelled"}

    @app.post("/api/feedback", status_code=201)
    def feedback(data: FeedbackInput, actor=Depends(authenticated)):
        if data.category == "human-ux" and actor["kind"] != "human":
            raise HTTPException(403, "Agent feedback must not be labeled as a human UX report")
        with connect(settings.database, True) as con:
            feedback_id = uid()
            con.execute("INSERT INTO feedback VALUES (?,?,?,?,?)", (feedback_id, actor["id"], data.category, data.body, time.time()))
            return {"id": feedback_id}

    @app.get("/api/feedback")
    def read_feedback(actor=Depends(reviewer)):
        with connect(settings.database) as con:
            return [dict(r) for r in con.execute("SELECT f.*,a.kind AS actor_kind,a.name FROM feedback f "
                                                "JOIN actors a ON a.id=f.actor_id ORDER BY created DESC LIMIT 100")]

    from .workshop_routes import install
    install(app, settings, page, human, reviewer, agent)
    from .agent_routes import install as install_agents
    install_agents(app, settings, page, human, agent)
    return app
