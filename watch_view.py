"""watch_view.py - a dashboard: small views tied to the keys of a run (Tessa design rule 7). A view names keys and nothing else; the engine knows nothing of views. The views come from the panel's spec ("views"), else from the pipeline's own data ("views"), so a pipeline carries the dashboard its author meant and a face may show another.
View types, each {"type", "title", ...}:
- "progress": {"step"}: the items of a for-each pipeline step (in the run, or in any run under it) done, working and failed, of all
- "count": {"key", "label"}: how many: the length of a list key (or 1 for any other value), over every run under this one that holds it
- "chat": {"key", "notes", "label"}: a transcript key ([{"who", "text", "round"}]) of one of the runs that hold it, picked, with the notes key's notes after their rounds
- "page": {"key", "label"}: a text key shown as a page (markdown) of one of the runs that hold it, picked; the newest version when several runs hold it under one label
- "text": {"key"}: a text key of the run itself, or of the newest run under it that holds it, as a page
A key is read from what each run kept and from what its steps have made so far (Run.live, named "<step id>:<key>"), so a transcript shows turn by turn. "label": a key of each run whose value names it in a picker (a person's name); without one, the run's own name."""
import re, json, time
from urllib.parse import quote

C = None   # corvid.py's live view, given to init
SEL: dict = {}   # (user, face, panel key) -> the run shown
PICK: dict = {}   # (user, face, panel key, view n) -> the run under it a view shows
POLL_S = 3

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_watch_run": [_h_run], "corvid_watch_pick": [_h_pick]})

# --- Runs and keys ---

def _tree(top) -> list:
    """The run and every run made under it (by its steps, to any depth), oldest first."""
    return sorted((r for r in C.AV.director.runs.values() if r.id == top.id or r.id.startswith(top.id + "~")), key=lambda r: r.meta.get("created", 0))

def _value(r, key: str):
    """A key's value in one run: what it kept, else what a step has made of it so far; None when it has neither."""
    if key in r.data: return r.data[key]
    return next((v for k, v in r.live.items() if k == key or k.endswith(":" + key)), None)

def _holding(top, key: str) -> list:
    """The runs under top (and top) that hold the key, newest first."""
    return [r for r in reversed(_tree(top)) if _value(r, key) is not None]

def _label(r, spec: dict) -> str:
    v = _value(r, spec["label"]) if spec.get("label") else None
    return str(v)[:60] if v not in (None, "") else r.id.split("~", 1)[-1]

# --- Views ---

def _progress(top, spec: dict) -> str:
    sid, done, going, failed, total = spec["step"], 0, 0, 0, 0
    for r in _tree(top):
        st = next((s for s in r.plan["steps"] if s["id"] == sid and (s.get("config") or {}).get("each")), None)
        if not st: continue
        total += len(r.data.get(st["config"]["each"]) or [])
        kids = [k for k in C.AV.director.runs.values() if re.fullmatch(rf"{re.escape(r.id)}~{re.escape(sid)}~\d+", k.id)]
        done, going, failed = done + sum(k.meta["state"] == "done" for k in kids), going + sum(k.meta["state"] in C.LIVE for k in kids), failed + sum(k.meta["state"] == "failed" for k in kids)
    if not total: return C._dim("not reached yet")
    return f"""<progress value="{done}" max="{total}" style="width:100%"></progress><div class="row"><b>{done} of {total}</b><span class="cv-dim">{f"{going} working" if going else ""}{f", {failed} failed" if failed else ""}</span></div>"""

def _count(top, spec: dict) -> str:
    n = sum(len(v) if isinstance(v, list) else 1 for v in (_value(r, spec["key"]) for r in _tree(top)) if v is not None)
    return f"""<div class="row"><b style="font-size:1.6rem">{n}</b><span class="cv-dim">{C._esc(spec.get("label") or spec["key"])}</span></div>"""

def _picker(c, top, spec: dict, n: int) -> tuple:
    """The run under top a view shows (the one picked, else the newest still working, else the newest) and the select to pick another."""
    have, me = _holding(top, spec["key"]), (C._user(c.request), c.face["id"], c.key, n)
    if spec["type"] == "page": have = list({_label(r, spec): r for r in reversed(have)}.values())[::-1]   # one per label: a page developed further under a later run is that page's newest version
    if not have: return None, ""
    cur = next((r for r in have if r.id == PICK.get(me)), None) or next((r for r in have if r.meta["state"] in C.LIVE), have[0])
    if len(have) < 2: return cur, ""
    opts = "".join(f"""<option value="{C._esc(r.id)}"{" selected" if r is cur else ""}>{C._esc(_label(r, spec))}{" (working)" if r.meta["state"] in C.LIVE else ""}</option>""" for r in have)
    return cur, f"""<select class="module-select" name="pick" hx-post="/im/in" hx-vals='{json.dumps({"type": "corvid_watch_pick", "face": c.face["id"], "key": c.key, "n": n})}' hx-trigger="change" hx-swap="none">{opts}</select>"""

def _md(text) -> str: return f"""<div>{C.BI.md_plus_transpiler(str(text or ""))}</div>"""

def _chat(c, top, spec: dict, n: int) -> tuple:
    r, pick = _picker(c, top, spec, n)
    if not r: return pick, C._dim("no conversation yet")
    log, notes = _value(r, spec["key"]) or [], {x.get("round"): x.get("text") for x in (_value(r, spec["notes"]) or [] if spec.get("notes") else [])}
    rows, last = [], None
    for e in log:
        if last is not None and e.get("round") != last and last in notes: rows.append(f"""<div class="quote-block cv-dim"><b>notes, round {last}</b>{_md(notes[last])}</div>""")
        last = e.get("round")
        rows.append(f"""<div class="cv-dim pre-wrap">{C._esc(e.get("text"))}</div>""" if e.get("who") == "Scene" else f"""<div class="list-row"><b>{C._esc(e.get("who"))}</b>{_md(e.get("text"))}</div>""")
    if last in notes: rows.append(f"""<div class="quote-block cv-dim"><b>notes, round {last}</b>{_md(notes[last])}</div>""")
    return pick, "".join(rows) + (C._dim("&#x23F3; going on ...") if r.meta["state"] in C.LIVE else "")

def _page(c, top, spec: dict, n: int) -> tuple:
    r, pick = _picker(c, top, spec, n)
    return pick, _md(_value(r, spec["key"])) if r else C._dim("no page yet")

def _text(top, spec: dict) -> str:
    v = next((_value(r, spec["key"]) for r in [top, *reversed(_tree(top))] if _value(r, spec["key"]) is not None), None)   # the run's own, else the newest under it: a synthesis folded item by item shows as it grows
    return _md(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1)) if v is not None else C._dim("not made yet")

def _view(c, top, spec: dict, n: int) -> str:
    t = spec["type"]
    pick, body = _chat(c, top, spec, n) if t == "chat" else _page(c, top, spec, n) if t == "page" else ("", _progress(top, spec) if t == "progress" else _count(top, spec) if t == "count" else _text(top, spec) if t == "text" else C._dim(f"no view type {t!r}"))
    tall = t in ("chat", "page", "text")
    return f"""<div class="list-row" style="{"grid-column:1/-1;" if spec.get("wide") else ""}"><div class="row" style="flex-wrap:wrap"><b>{C._esc(spec.get("title") or spec.get("key") or t)}</b><span class="grow"></span>{pick}</div><div{' class="scroll-pane" style="max-height:60vh"' if tall else ""}>{body}</div></div>"""

# --- Panel ---

def _runs(c, pid: str) -> list:
    """The runs of the pipeline this person may see (an admin: everyone's), newest first; not those made by another run's step."""
    return sorted((r for r in C.AV.director.runs.values() if not r.meta.get("parent") and r.plan.get("id") == pid and (C._admin(c.request) or r.meta.get("owner") == C._user(c.request))), key=lambda r: r.meta["created"], reverse=True)

def _run_option(r, chosen: bool) -> str: return f"""<option value="{C._esc(r.id)}"{" selected" if chosen else ""}>{C._esc(time.strftime("%m-%d %H:%M", time.localtime(r.meta["created"])))} {C._esc(C._about(r))[:80]} ({C._esc(r.meta["state"])})</option>"""

async def p_watch(c) -> str:
    """A dashboard over one run of a pipeline (spec "pipeline"): the views of the spec, else of the pipeline. Asks again every few seconds while the run is under way."""
    pid = c.spec["pipeline"]
    if not C.AV.lib.has("pipeline", pid): return C._dim(f"No pipeline {pid} in the library.")
    views, runs, me = c.spec.get("views") or C.AV.lib.get("pipeline", pid).get("views") or [], _runs(c, pid), (C._user(c.request), c.face["id"], c.key)
    if not runs: return C._dim("No run of this pipeline yet: set one up and start it, and it shows here as it goes.")
    top = next((r for r in runs if r.id == SEL.get(me)), runs[0])
    live = any(r.meta["state"] in C.LIVE for r in _tree(top))
    view, region, n = c.key.split(":")[0], c.key.split(":")[1].split(".")[0], c.key.split(".")[1]
    poll = f"""hx-get="{C._P}/panel?face={quote(c.face["id"])}&amp;view={quote(view)}&amp;region={region}&amp;n={n}&amp;host={quote(c.host)}" hx-trigger="every {POLL_S}s" hx-swap="outerHTML" """ if live else ""
    opts = "".join(_run_option(r, r is top) for r in runs)
    pick = f"""<select class="module-select grow" name="rid" hx-post="/im/in" hx-vals='{json.dumps({"type": "corvid_watch_run", "face": c.face["id"], "key": c.key})}' hx-trigger="change" hx-swap="none">{opts}</select>"""
    err = f"""<div class="cv-bad pre-wrap">{C._esc(top.meta["error"])}</div>""" if top.meta.get("error") else ""
    return f"""<div {poll}><div class="row">{pick}<span class="chip {C._STATE.get(top.meta["state"], "")}">{C._esc(top.meta["state"])}</span></div>{err}<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,22rem),1fr));gap:.6rem">{"".join(_view(c, top, v, i) for i, v in enumerate(views)) or C._dim("This pipeline names no views (its data's views list).")}</div></div>"""

# --- Handlers ---

async def _h_run(request, payload, imr):
    SEL[(C._user(request), payload["face"], payload["key"])] = payload.get("rid", "")
    return await C._refresh(request, imr, payload["face"])

async def _h_pick(request, payload, imr):
    PICK[(C._user(request), payload["face"], payload["key"], int(payload["n"]))] = payload.get("pick", "")
    return await C._refresh(request, imr, payload["face"])
