# Unified Activity Model — Stage 2 (MCP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Move the MCP off the deprecated `/workouts` shims and add the canonical `log_activity`/`list_activities` tools, per the unified-activity-model SOW (stage 2). Existing tool NAMES and argument contracts stay stable so `prog-strength-agent` needs zero changes.

**Architecture:** `workouts.py` keeps its two tools but the client re-points to the unified surface (`POST /activities` with `activity_type=strength_training`; `GET /activities?type=strength_training`). A new `activities.py` module adds the generic typed tools. `running.py` (already on `/activities`) and `planned_workouts.py` are untouched.

**Tech stack:** Python 3.12, FastMCP, httpx, respx+pytest (asyncio_mode=auto), ruff, uv.

**API ground truth:** the api repo branch `feat/unified-activity-model` (PR #79). Read `internal/activity/unified_handler.go` + `handler.go` for exact request/response shapes before coding; do not guess. A local API binary for live verification exists at the scratchpad (`boot/api-branch`, DEV_AUTH flow documented in step 6).

---

### Task 1: Branch + plan commit
- [ ] In prog-strength-mcp: `git checkout main && git pull --ff-only && git checkout -b feat/unified-activities`
- [ ] Commit this plan file: `docs: add stage-2 unified-activities plan`

### Task 2: APIClient methods (TDD — client-level respx tests first)

**Files:** `src/prog_strength_mcp/api_client.py`, `tests/test_activities_client.py` (new)

- [ ] Tests first (respx, follow `tests/test_running_tools.py` conventions): 
  - `list_activities(auth, type=None, limit=None)` → `GET /activities` with optional `type`/`limit` query params; unwraps the envelope; assert the wrapper shape the API actually returns (READ the Go handler: the list payload is `{"activities": [...], ...}` — verify field names, incl. cursor field) and surface the items list.
  - `create_activity(auth, payload)` → `POST /activities` forwarding the typed body verbatim; 422 unknown-type and 400 invalid-details surfaced as `APIError` with status+message.
  - `get_activity(auth, id)` → `GET /activities/{id}` (quote the id path segment like running.py does).
  - Re-pointed `list_workouts` → now `GET /activities?type=strength_training`; re-pointed `create_workout` → now `POST /activities` with body `{"activity_type":"strength_training","start_time":...,"name":...,"notes":...,"details":{"exercises":[...]}}` — map the old args (`performed_at`→`start_time`, `ended_at`→ compute nothing client-side: READ the unified create request shape in Go to see whether it takes `duration_seconds` or an end time, and map `ended_at` accordingly; omit-if-None preserved).
- [ ] Implement the client methods; keep `_raise_for_status` / envelope-unwrap conventions; docstrings match module style.
- [ ] `uv run pytest tests/test_activities_client.py -v` green. Commit.

### Task 3: Re-point `workouts.py` tools + add tests

**Files:** `src/prog_strength_mcp/workouts.py`, `tests/test_workouts_tools.py` (new — this module currently has NO tests)

- [ ] Tool signatures and names UNCHANGED (`list_workouts`, `create_workout`, same args). Update docstrings honestly: note they are strength-typed conveniences over the unified `/activities` surface and that returned objects are unified activity DTOs (id preserved, `activity_type`, `summary`, strength `details` on create response — verify actual shape from Go handler).
- [ ] Tests: tool-level auth-guard (`_ExplodingAPI` pattern) + happy path against respx asserting the NEW endpoints are hit. Commit.

### Task 4: New `activities.py` module — canonical tools

**Files:** `src/prog_strength_mcp/activities.py` (new), `tests/test_activities_tools.py` (new), `src/prog_strength_mcp/server.py` (one register line), `README.md` (tool table)

- [ ] `log_activity` tool: args `activity_type: str` (docstring lists current types and says the registry may grow: running, walking, cycling, other, strength_training), `start_time: str|None` (RFC3339, omit = now — verify API default), `duration_seconds: int|None`, `name: str|None`, `notes: str|None`, `details: dict|None` (type-specific payload forwarded verbatim; document the strength and endurance shapes briefly with a pointer that unknown types → 422 listing valid types). → `create_activity`.
- [ ] `list_activities` tool: args `timezone: str` (required — follow the nutrition/planned-workouts convention), optional `date` / `start_date`+`end_date`, optional `activity_type` filter. READ the Go handler's range-path query params (`internal/activity/handler.go`) and forward exactly what it accepts — the API resolves local-day boundaries; never build UTC bounds client-side (house rule). If the range path does NOT take timezone+local-date (verify!), match whatever it does take and note it.
- [ ] Both tools: standard `_auth_header_or_raise`, `APIError`→`RuntimeError` mapping, docstrings in module style (these are agent-facing contracts — make them as instructive as `create_workout`'s).
- [ ] Register in `server.py`; update README tool table (add the two new tools; annotate `list_workouts`/`create_workout` as strength conveniences).
- [ ] Tests: auth guard, param forwarding (timezone/date combos), 422 surfacing. Commit.

### Task 5: Full verification
- [ ] `uv run pytest` (whole suite) green; `uv run ruff check` clean.

### Task 6: Live integration smoke (optional but preferred)
- [ ] Boot the stage-1 API binary: `DATABASE_URL=<scratch>/mcp-smoke.db JWT_SIGNING_KEY=x DEV_AUTH=true <scratch>/boot/api-branch`; mint a token via `POST /auth/dev/token`; run the MCP server with `PROG_STRENGTH_API_BASE_URL=http://localhost:8080` and exercise `create_workout`, `log_activity` (type `other`), `list_activities`, `list_workouts` end-to-end (calling the client methods directly from a scratch script is fine — the point is real HTTP against the real branch API). Record outputs in the report. Kill processes after.

### Task 7: PR
- [ ] Push `feat/unified-activities`; `gh pr create` — title "feat: unified activities tools (stage 2)"; body: summary, tool-contract stability note, dependency note ("merge after api PR #79 is deployed; /workouts shims removed in stage 5"), the standard 🤖 footer.

**Conventions:** conventional commits + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer on every commit.
