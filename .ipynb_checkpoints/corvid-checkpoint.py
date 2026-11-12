"""corvid.py - Corvid: the faces of the engine. A face is a manifest (library kind "face"): a name and a list of panels with their settings. This file draws any face from the panels below and holds no face of its own: a new face, or a changed one, is data.
The panels know the engine (tools/engine) and nothing under it: no machine, model or program is named here. What a panel shows comes from the library, the providers' own answers and the runs.
Panels: providers (places that do work), bindings (who fills which role, in one profile), library (any kinds of objects, as JSON), runs (start a pipeline, follow and steer its runs), conversation (a talk whose every turn is a run of the pipeline the face names)."""
import re, json, html, time
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

MODULE_META = {"label": "Corvid", "icon": "&#x1F426;", "description": "Faces of the engine: converse, hand off work, see and steer what runs", "persistence": "user"}
router = APIRouter(redirect_slashes=False)
ENV, IM, ENG, PROV, DATA, _P = {}, None, None, None, None, "/module/corvid"
LIVE, _STATE = ("running", "stopping"), {"done": "cv-ok", "running": "cv-mid", "stopping": "cv-mid", "interrupted": "cv-mid", "new": "", "stopped": "", "held": "cv-bad", "failed": "cv-bad", "unplaced": "cv-bad"}

# --- Parts ---

def _esc(s) -> str: return html.escape("" if s is None else str(s), quote=True)
def _attr(name: str, v: str) -> str: return f""" {name}="{_esc(v)}" """.rstrip() if v else ""
def _act(t: str, confirm: str = None, include: str = None, **kw) -> str: return f"""hx-post="/im/in" hx-swap="none" hx-vals="{_esc(json.dumps({"type": "corvid_" + t, "branch": IM.branch_id, "lvl": 1, **kw}))}"{_attr("hx-include", include)}{_attr("hx-confirm", confirm)}"""
def _btn(label: str, t: str, cls: str = "ui-btn", **kw) -> str: return f"""<button type="button" class="{cls}" {_act(t, **kw)}>{label}</button>"""
def _dim(text: str) -> str: return f"""<div class="cv-dim">{text}</div>""" if text else ""
def _note(text: str, bad: bool = False) -> str: return f"""<div class="{"cv-err" if bad else "cv-note"}">{_esc(text)}</div>"""
def _option(v, selected: bool = False, label: str = None) -> str: return f"""<option value="{_esc(v)}" {"selected" if selected else ""}>{_esc(v if label is None else label)}</option>"""
def _shown(v) -> str: return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
def _value(raw: str):
    try: return json.loads(raw)
    except ValueError: return raw
def _slug(s: str) -> str: return re.sub(r"[^\w.-]", "", s.lower().replace(" ", "-"))
def _when(t) -> str: return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""
def _user(request) -> str: return request.state.user.username
def _admin(request) -> bool: return getattr(request.state.user, "role", "") == "admin"
def _sec(title: str, body: str, tools: str = "") -> str: return f"""<div class="cv-sec"><div class="row"><b>{_esc(title)}</b><span class="grow"></span>{tools}</div>{body}</div>"""

async def _offers(capability: str) -> list:
    """[(provider, [asset names])] for one capability, from every provider that answers; one that does not is left out here and shown as unreachable where providers are listed."""
    out = []
    for p in ENG.lib.list("provider"):
        try: out.append((p, sorted(a["name"] for a in await PROV.assets(p, capability))))
        except PROV.ProviderError: continue
    return out

def _roles() -> dict:
    """Every role any pipeline in the library names: {role: its need}."""
    return {r: need for pl in ENG.lib.list("pipeline") for r, need in (pl.get("roles") or {}).items()}

async def _role_select(field: str, need: dict, cur: dict, empty: str) -> str:
    def group(p, names): return "".join(_option(p["id"] + "|" + n, cur.get("asset") == n and cur.get("provider", p["id"]) == p["id"], n) for n in names)
    opts = "".join(f"""<optgroup label="{_esc(p.get("name") or p["id"])}">{group(p, names)}</optgroup>""" for p, names in await _offers((need.get("needs") or [""])[0]))
    return f"""<select name="{_esc(field)}" class="module-select grow mono">{_option("", not cur.get("asset"), empty)}{opts}</select>"""

def _picked(payload: dict, prefix: str) -> dict: return {k[len(prefix):]: dict(zip(("provider", "asset"), v.split("|", 1))) for k, v in payload.items() if k.startswith(prefix) and v}

# --- Panel: providers ---

async def p_providers(face: dict, spec: dict, request, n: int) -> str:
    rows = "".join(f"""<div class="list-row"><div class="row"><b>{_esc(p.get("name") or p["id"])}</b><span class="cv-dim grow mono">{_esc(p["url"])}</span>{_btn("What it offers", "provider_check", face=face["id"], id=p["id"])}{_btn("Remove", "provider_del", "ui-btn cv-danger", face=face["id"], id=p["id"], confirm="Remove this provider from the library? It is kept as a version.")}</div><div id="cv-prov-{_esc(p["id"])}"></div></div>""" for p in ENG.lib.list("provider"))
    form = f"""<form class="row" id="cv-prov-new" onsubmit="return false"><input name="name" class="module-select" placeholder="name"><input name="url" class="module-select grow mono" placeholder="http://host:port"><input name="key" class="module-select mono" placeholder="key (work scope is enough)" type="password">{_btn("Add", "provider_add", face=face["id"], include="#cv-prov-new")}</form>"""
    return _dim("A provider is a place that does work and answers for itself what it offers. Nothing about it is kept here but where it is.") + (rows or _dim("none yet")) + form

async def _h_provider_check(request, payload, imr):
    p = ENG.lib.get("provider", payload["id"])
    try: d, assets = await PROV.ask(p, "describe"), await PROV.assets(p)
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), f"""cv-prov-{payload["id"]}""")
    caps = sorted({c for a in assets for c in a.get("capabilities", [])})
    rows = "".join(f"""<div class="row cv-dim"><span class="cv-key">{_esc(c)}</span><span class="mono">{_esc(", ".join(a["name"] for a in assets if c in a.get("capabilities", [])))}</span></div>""" for c in caps)
    said = " | ".join(k + ": " + _shown(v)[:60] for k, v in d.items() if isinstance(v, (str, int, float)))
    return imr.oob(f"""<div class="cv-form">{_dim(_esc(said))}{rows or _dim("offers nothing yet")}</div>""", f"""cv-prov-{payload["id"]}""")

async def _h_provider_add(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes providers.", True), "cv-msg")
    if not (payload.get("name") and payload.get("url")): return imr.oob(_note("A provider needs a name and where it is.", True), "cv-msg")
    ENG.lib.save("provider", {"id": _slug(payload["name"]), "name": payload["name"], "url": payload["url"].rstrip("/"), "key": payload.get("key", "")}, by=_user(request))
    return await _refresh(request, imr, payload["face"], _note(f"""Added {payload["name"]}."""))

async def _h_provider_del(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes providers.", True), "cv-msg")
    ENG.lib.remove("provider", payload["id"])
    return await _refresh(request, imr, payload["face"], _note("Removed."))

# --- Panel: bindings (one profile: who fills each role the library's pipelines name) ---

async def p_bindings(face: dict, spec: dict, request, n: int) -> str:
    prof = ENG.lib.get("bindings", spec["profile"]) if ENG.lib.has("bindings", spec["profile"]) else {"roles": {}}
    rows = "".join([f"""<div class="row"><b class="cv-key">{_esc(r)}</b>{await _role_select("r_" + r, need, prof["roles"].get(r) or {}, "(not bound)")}<span class="cv-dim">{_esc(", ".join(need.get("needs") or []))} - {_esc(need.get("about", ""))}</span></div>""" for r, need in _roles().items()])
    about = _dim(f"""Profile {_esc(spec["profile"])}: what each role is filled with wherever nothing more specific says otherwise. Changing a model, or the machine it runs on, is a change here; no pipeline changes.""")
    return f"""{about}<form id="cv-bind-{n}" onsubmit="return false">{rows or _dim("no pipeline names a role yet")}<div class="row"><span class="grow"></span>{_btn("Save", "bindings_save", face=face["id"], profile=spec["profile"], include="#cv-bind-" + str(n))}</div></form>"""

async def _h_bindings_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes this profile.", True), "cv-msg")
    old = ENG.lib.get("bindings", payload["profile"]) if ENG.lib.has("bindings", payload["profile"]) else {"id": payload["profile"], "roles": {}}
    picked = _picked(payload, "r_")
    ENG.lib.save("bindings", {**old, "roles": {r: {**(old["roles"].get(r) or {}), **picked[r]} for r in picked}}, by=_user(request))
    return await _refresh(request, imr, payload["face"], _note("Saved. Runs started from now on use it; the earlier version is kept."))

# --- Panel: library (any kinds, as the JSON they are) ---

async def p_library(face: dict, spec: dict, request, n: int) -> str:
    def info(kind, o): return " | ".join(x for x in (o["id"], f"""{len(ENG.lib.versions(kind, o["id"]))} earlier versions""" if ENG.lib.versions(kind, o["id"]) else "", str(o.get("objective") or o.get("about") or "")[:120]) if x)
    def rows(kind): return "".join(f"""<div class="list-row row"><b>{_esc(o.get("name") or o["id"])}</b><span class="chip">{ENG.lib.origin(kind, o["id"])}</span><span class="cv-dim grow">{_esc(info(kind, o))}</span>{_btn("Open", "lib_open", face=face["id"], kind=kind, id=o["id"], n=n)}</div>""" for o in ENG.lib.list(kind))
    kinds = "".join(f"""<div class="row"><b class="cv-dim">{_esc(k)}</b><span class="grow"></span>{_btn("New", "lib_open", face=face["id"], kind=k, id="", n=n)}</div>{rows(k) or _dim("none")}""" for k in spec["kinds"])
    return f"""{_dim("Shipped objects come with the software and are never changed; saving one makes it yours, and removing yours brings the shipped one back. Every save keeps the version before it.")}{kinds}<div id="cv-lib-{n}"></div>"""

async def _h_lib_open(request, payload, imr):
    kind, oid, n = payload["kind"], payload["id"], payload["n"]
    if payload.get("close"): return imr.oob("", f"cv-lib-{n}")
    obj = {k: v for k, v in ENG.lib.get(kind, oid).items() if k not in ("modified", "by")} if oid else {"id": "", "name": ""}
    back = _btn("Back to shipped", "lib_remove", face=payload["face"], kind=kind, id=oid, confirm="Remove your version? It is kept as an earlier version.") if oid and ENG.lib.origin(kind, oid) == "mine" else ""
    return imr.oob(f"""<form class="cv-form" id="cv-lib-f{n}" onsubmit="return false"><div class="row"><b>{_esc(kind)}</b><span class="mono grow">{_esc(oid or "new")}</span>{_btn("Save as mine", "lib_save", face=payload["face"], kind=kind, include="#cv-lib-f" + str(n))}{back}{_btn("Close", "lib_open", face=payload["face"], kind=kind, id=oid, n=n, close="1")}</div><textarea name="json" class="module-select mono cv-json" spellcheck="false">{_esc(json.dumps(obj, indent=1, ensure_ascii=False))}</textarea></form>""", f"cv-lib-{n}")

async def _h_lib_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes the library.", True), "cv-msg")
    try: obj = json.loads(payload["json"])
    except ValueError as e: return imr.oob(_note(f"Not saved, the text is not JSON: {e}", True), "cv-msg")
    if not _slug(str(obj.get("id", ""))): return imr.oob(_note("Not saved: it needs an id.", True), "cv-msg")
    ENG.lib.save(payload["kind"], {**obj, "id": _slug(obj["id"])}, by=_user(request))
    return await _refresh(request, imr, payload["face"], _note(f"""Saved {payload["kind"]} {obj["id"]}."""))

async def _h_lib_remove(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes the library.", True), "cv-msg")
    ENG.lib.remove(payload["kind"], payload["id"])
    return await _refresh(request, imr, payload["face"], _note("Removed yours."))

# --- Panel: runs (start a pipeline, follow and steer what runs) ---

def _mine(request, face: dict, spec: dict) -> list:
    """The runs this person may see here, newest first: their own (an admin: everyone's), of the groups the panel shows."""
    runs = [r for r in ENG.director.runs.values() if (_admin(request) or r.meta.get("owner") == _user(request)) and (not spec.get("groups") or r.plan.get("group") in spec["groups"])]
    return sorted(runs, key=lambda r: r.meta["created"], reverse=True)[:30]

def _run_row(face_id: str, r) -> str:
    v, st = r.view(), r.meta["state"]
    acts = _btn("Open", "run_view", id=r.id) + (_btn("Stop", "run_stop", face=face_id, id=r.id) if st in LIVE else _btn("Go on", "run_go", face=face_id, id=r.id) if st != "done" else "")
    info = " | ".join(x for x in (f"""{len(v["done"])} of {len(r.plan["steps"])} steps""", ", ".join(v["busy"]), _esc(r.meta.get("error", ""))[:200], _when(r.meta["created"]), _esc(r.meta.get("owner", ""))) if x)
    return f"""<div class="list-row row"><b>{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(st, "")}">{_esc(st)}</span><span class="cv-dim grow">{info}</span>{acts}</div>"""

def _run_list(request, face: dict, n: int) -> str:
    """Polls itself while a run shown is under way."""
    runs = _mine(request, face, face["panels"][n])
    poll = f"""hx-get="{_P}/runs?face={_esc(face["id"])}&amp;n={n}" hx-trigger="every 2s" hx-swap="outerHTML" """ if any(r.meta["state"] in LIVE for r in runs) else ""
    return f"""<div id="cv-runs-{n}" {poll}>{"".join(_run_row(face["id"], r) for r in runs) or _dim("nothing has run here yet")}</div>"""

async def p_runs(face: dict, spec: dict, request, n: int) -> str:
    plans = "".join(f"""<div class="list-row row"><b>{_esc(pl.get("name") or pl["id"])}</b><span class="cv-dim grow">{_esc(pl.get("objective", ""))[:170]}</span>{_btn("Set up", "run_form", face=face["id"], id=pl["id"], n=n)}</div>""" for pl in ENG.lib.list("pipeline") if not spec.get("groups") or pl.get("group") in spec["groups"])
    return f"""{_dim("A pipeline says what is to be done; the engine decides how, with what is free. A run goes on when this page is closed.")}{plans or _dim("no pipelines for this panel")}<div id="cv-runf-{n}"></div>{_run_list(request, face, n)}"""

async def _h_run_form(request, payload, imr):
    n, face = payload["n"], ENG.lib.get("face", payload["face"])
    if payload.get("close"): return imr.oob("", f"cv-runf-{n}")
    pl, from_profile = ENG.lib.get("pipeline", payload["id"]), "(as the profile says)" if face.get("profiles") else "(not bound)"
    fields = "".join(f"""<div class="row"><b class="cv-key">{_esc(p.get("label") or k)}</b><input name="p_{_esc(k)}" class="module-select grow mono" value="{_esc(_shown(p.get("default")))}"></div>""" for k, p in (pl.get("params") or {}).items())
    roles = "".join([f"""<div class="row"><b class="cv-key">{_esc(r)}</b>{await _role_select("r_" + r, need, {}, from_profile)}<span class="cv-dim">{_esc(need.get("about", ""))}</span></div>""" for r, need in (pl.get("roles") or {}).items()])
    return imr.oob(f"""<form class="cv-form" id="cv-runf-f{n}" onsubmit="return false"><div class="row"><b class="grow">{_esc(pl.get("name") or pl["id"])}</b>{_btn("Start", "run_start", face=face["id"], id=pl["id"], include="#cv-runf-f" + str(n))}{_btn("Close", "run_form", face=face["id"], id=pl["id"], n=n, close="1")}</div>{_dim(_esc(pl.get("objective", "")))}{fields}{roles}</form>""", f"cv-runf-{n}")

async def _h_run_start(request, payload, imr):
    face = ENG.lib.get("face", payload["face"])
    try: rid = await ENG.start(payload["id"], {k[2:]: _value(v) for k, v in payload.items() if k.startswith("p_") and str(v).strip()}, owner=_user(request), profiles=face.get("profiles", []), pins=_picked(payload, "r_"))
    except ValueError as e: return imr.oob(_note(f"Not started: {e}", True), "cv-msg")
    return await _refresh(request, imr, face["id"], _note(f"Started as {rid}."))

def _run(request, rid: str):
    """The run, for its owner or an admin; PermissionError otherwise (the intent fails and says so in the portal's log)."""
    r = ENG.director.runs[rid]
    if not (_admin(request) or r.meta.get("owner") == _user(request)): raise PermissionError(f"run {rid} belongs to someone else")
    return r

async def _h_run_go(request, payload, imr):
    await ENG.go(_run(request, payload["id"]).id)
    return await _refresh(request, imr, payload["face"])

async def _h_run_stop(request, payload, imr):
    ENG.director.stop(_run(request, payload["id"]).id, now=True)
    return await _refresh(request, imr, payload["face"], _note("Stopping: what was running is dropped, what was kept stays, and Go on picks it up from there."))

def _run_view(r) -> str:
    """One run, whatever its pipeline: who fills its roles, each step and where it stands, what exists of its results, the last of its journal."""
    v, have = r.view(), set(r.data)
    nxt, kept = set(v["course"][0]) if v["course"] else set(), {unquote(f.stem) for f in (r.dir / "kept").glob("*.json")}
    def where(s): return "done" if "@" + s["id"] in have else "running" if s["id"] in v["busy"] else "unreached" if s["id"] in v["unreached"] else "next" if s["id"] in nxt else "waiting"
    bound = "".join(f"""<div class="row cv-dim"><span class="cv-key">{_esc(role)}</span><span class="mono">{_esc(b.get("asset"))} on {_esc(b.get("provider"))}</span><span>{_esc(b.get("will", ""))}</span></div>""" for role, b in (r.meta.get("bound") or {}).items())
    steps = "".join(f"""<tr><td class="mono">{_esc(s["id"])}</td><td>{_esc(s["type"])}</td><td class="{_STATE.get(where(s), "")}">{where(s)}</td><td>{"kept" if "@" + s["id"] in kept else ""}</td><td>{_esc(_shown(s.get("item"))[:120])}</td></tr>""" for s in r.plan["steps"])
    start = set(r.plan.get("params") or {}) | set(r.plan.get("data") or {})
    keys = "".join(f"""<tr><td class="mono">{_esc(k)}</td><td>{_esc(_shown(val)[:400])}</td></tr>""" for k, val in r.data.items() if not k.startswith("@") and k not in start)
    journal = (r.dir / "journal.jsonl").read_text().splitlines()[-12:]
    again = _btn("It may run again", "run_decide", id=r.id, step=r.meta.get("held_at", "")) if r.meta["state"] == "held" else ""
    return f"""<div class="cv-form"><div class="row"><b>{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(r.meta["state"], "")}">{_esc(r.meta["state"])}</span><span class="cv-dim grow mono">{_esc(r.id)} | {_esc(r.meta.get("owner", ""))}</span>{again}{_btn("Refresh", "run_view", id=r.id)}{_btn("Close", "run_view", id=r.id, close="1")}</div>{_note(r.meta["error"], True) if r.meta.get("error") else ""}{_dim(_esc(r.plan.get("objective", "")))}<b>Roles</b>{bound or _dim("none placed yet")}<b>Steps</b><table class="cv-tbl"><tr><th>step</th><th>type</th><th>state</th><th></th><th>item</th></tr>{steps}</table><b>What exists of its results</b><table class="cv-tbl">{keys}</table><b>Journal</b><div class="quote-block mono cv-log">{_esc(chr(10).join(journal))}</div></div>"""

async def _h_run_view(request, payload, imr): return imr.oob("" if payload.get("close") else _run_view(_run(request, payload["id"])), "cv-run-view")

async def _h_run_decide(request, payload, imr):
    r = _run(request, payload["id"])
    ENG.director.decide(r.id, payload["step"], again=True)
    await ENG.go(r.id)
    return imr.oob(_run_view(r), "cv-run-view")

# --- Panel: conversation (every turn is a run of the pipeline the face names) ---

def _talk_file(request, face: dict) -> Path: return DATA / "conversations" / _user(request) / f"""{face["id"]}.json"""
def _talk(request, face: dict) -> dict: return json.loads(_talk_file(request, face).read_text()) if _talk_file(request, face).exists() else {"messages": [], "pending": ""}
def _talk_save(request, face: dict, t: dict):
    _talk_file(request, face).parent.mkdir(parents=True, exist_ok=True)
    _talk_file(request, face).write_text(json.dumps(t, indent=1, ensure_ascii=False))

def _talk_html(request, face: dict, n: int) -> str:
    """The talk so far. A turn that is under way is looked up in its run; when the run has ended its answer joins the talk."""
    t, spec, waiting = _talk(request, face), face["panels"][n], ""
    if t["pending"]:
        r = ENG.director.runs[t["pending"]]
        if r.meta["state"] == "done": t["messages"].append({"role": "assistant", "content": _shown(r.data.get(spec.get("answer", "text"))), "run": r.id})
        elif r.meta["state"] in LIVE: waiting = """<div class="cv-msg-a cv-dim">...</div>"""
        else: t["messages"].append({"role": "note", "content": f"""No answer: the run is {r.meta["state"]}. {r.meta.get("error", "")}""", "run": r.id})
        if not waiting:
            t["pending"] = ""
            _talk_save(request, face, t)
    msgs = "".join(f"""<div class="{"cv-msg-u" if m["role"] == "user" else "cv-msg-a"}"><div class="cv-pre">{_esc(m["content"])}</div>{_btn("The run behind this", "run_view", "ui-btn cv-small", id=m["run"]) if m.get("run") else ""}</div>""" for m in t["messages"])
    poll = f"""hx-get="{_P}/talk?face={_esc(face["id"])}&amp;n={n}" hx-trigger="every 1s" hx-swap="outerHTML" """ if waiting else ""
    return f"""<div id="cv-talk-{n}" {poll}>{msgs or _dim("nothing said yet")}{waiting}</div>"""

async def p_conversation(face: dict, spec: dict, request, n: int) -> str:
    form = f"""<form class="row" id="cv-say-{n}" onsubmit="return false"><textarea name="text" class="module-select grow" rows="2" placeholder="say something"></textarea>{_btn("Send", "say", face=face["id"], n=n, include="#cv-say-" + str(n))}{_btn("Start over", "say_clear", face=face["id"], confirm="Clear this conversation? Its runs stay.")}</form>"""
    about = _dim(f"""Each turn runs the pipeline {_esc(spec["pipeline"])}; the role it names is filled by this face's profile.""")
    return f"""{about}{_talk_html(request, face, n)}{form}"""

async def _h_say(request, payload, imr):
    face, n = ENG.lib.get("face", payload["face"]), int(payload["n"])
    t = _talk(request, face)
    if t["pending"] or not (payload.get("text") or "").strip(): return imr
    t["messages"].append({"role": "user", "content": payload["text"].strip()})
    t["pending"] = await ENG.start(face["panels"][n]["pipeline"], {"messages": [{"role": m["role"], "content": m["content"]} for m in t["messages"] if m["role"] in ("user", "assistant")]}, owner=_user(request), profiles=face.get("profiles", []))
    _talk_save(request, face, t)
    return await _refresh(request, imr, face["id"])

async def _h_say_clear(request, payload, imr):
    _talk_file(request, ENG.lib.get("face", payload["face"])).unlink(missing_ok=True)
    return await _refresh(request, imr, payload["face"])

PANELS = {"providers": p_providers, "bindings": p_bindings, "library": p_library, "runs": p_runs, "conversation": p_conversation}

# --- The face shell ---

async def page(request, face_id: str = "", msg: str = "") -> str:
    """The inside of #cv-page: the faces to choose from, then the chosen face's panels in its manifest's order."""
    faces = sorted(ENG.lib.list("face"), key=lambda f: f.get("order", 50))
    face = next((f for f in faces if f["id"] == face_id), faces[0])
    pick = "".join(f"""<button type="button" class="chip{" cv-on" if f["id"] == face["id"] else ""}" {_act("open", face=f["id"])}>{_esc(f.get("name") or f["id"])}</button>""" for f in faces)
    panels = "".join([_sec(spec.get("title") or spec["panel"], await PANELS[spec["panel"]](face, spec, request, n)) for n, spec in enumerate(face["panels"])])
    return f"""<div class="row"><b>Corvid</b>{pick}</div>{_dim(_esc(face.get("about", "")))}<div id="cv-msg">{msg}</div>{panels}<div id="cv-run-view"></div>"""

async def _refresh(request, imr, face_id: str, msg: str = ""): return imr.oob(await page(request, face_id, msg), "cv-page")
async def _h_open(request, payload, imr): return await _refresh(request, imr, payload.get("face", ""))

# --- Routes and init ---

@router.get("")
@router.get("/")
async def root(request: Request):
    return ENV["templates"].TemplateResponse(name="base.html", request=request, context={"request": request, "user": request.state.user, "nesting_level": 1, "shell_id": IM.branch_id, "content": f"""<div class="scroll-pane cv" id="cv-page">{await page(request)}</div>""", "extra_css": CSS, "extra_script": "", "toolbars": {}})

@router.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, face: str, n: int): return HTMLResponse(_run_list(request, ENG.lib.get("face", face), n))

@router.get("/talk", response_class=HTMLResponse)
async def talk(request: Request, face: str, n: int): return HTMLResponse(_talk_html(request, ENG.lib.get("face", face), n))

def init_module(env: dict):
    global IM, ENG, PROV, DATA
    ENV.update(env)
    ENG, PROV, DATA = env["tools"]["engine"].ENGINE, env["tools"]["engine"].providers, Path(env["data_dir"])
    ENG.lib.shipped.append(Path(__file__).parent / "library")
    IM = env["InterfaceManager"](nesting_level=1, db_path=f"""{env["data_dir"]}/im_registry.db""")
    IM.scripts.update({f"corvid_{k}": [fn] for k, fn in {"open": _h_open, "provider_check": _h_provider_check, "provider_add": _h_provider_add, "provider_del": _h_provider_del, "bindings_save": _h_bindings_save, "lib_open": _h_lib_open, "lib_save": _h_lib_save, "lib_remove": _h_lib_remove, "run_form": _h_run_form, "run_start": _h_run_start, "run_go": _h_run_go, "run_stop": _h_run_stop, "run_view": _h_run_view, "run_decide": _h_run_decide, "say": _h_say, "say_clear": _h_say_clear}.items()})
    print(f"""[corvid] ready | faces: {[f["id"] for f in ENG.lib.list("face")]}""")

CSS = """
.cv{font-size:.8rem}.cv-sec{border:var(--border-thick) solid var(--border);border-radius:var(--radius);padding:.4rem .55rem;margin:.4rem 0;background:var(--surface)}
.cv-dim{font-size:.72rem;color:var(--text_muted)}.cv-key{min-width:7rem}.cv-on{border-color:var(--accent);background:var(--accent_dim)}.cv-small{font-size:.65rem}
.cv-ok{color:#00ffa2}.cv-mid{color:#ffcc00}.cv-bad{color:#ff6b6b}.cv-danger{color:#ff6b6b}
.cv-form{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-log{max-height:14rem;font-size:.7rem}.cv-json{width:100%;min-height:18rem;font-size:.72rem}
.cv-note{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-err{border-left:3px solid #ff6b6b;padding:.3rem .5rem;margin:.3rem 0}
.cv-tbl{border-collapse:collapse;font-size:.72rem;margin:.2rem 0 .5rem}.cv-tbl td,.cv-tbl th{border:var(--border-thick) solid var(--border);padding:.12rem .4rem;text-align:left;vertical-align:top}
.cv-msg-u,.cv-msg-a{border-radius:var(--radius);padding:.3rem .5rem;margin:.25rem 0;max-width:80%}.cv-msg-u{background:var(--accent_dim);margin-left:auto}.cv-msg-a{border:var(--border-thick) solid var(--border)}.cv-pre{white-space:pre-wrap}
"""
