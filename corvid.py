"""corvid.py - Corvid: the faces of Aviary. A face is a manifest (library kind "face"): a name and the panels it puts in the page's three regions - "main" (the workspace), "left" and "right" (the side toolbars). This file draws any face from the panels below and holds no face of its own: a new face, or a changed one, is data.
Built from the portal's own parts: faces are tabs (TabManager) in the top toolbar, a conversation is the portal's chat interface (ChatManager), every form is settings fields (SettingField / SettingsGroup). What is specific to Corvid is only how those are fed from the engine.
The panels know Aviary (tools/aviary) and nothing under it: no machine, model or program is named here. What a panel shows comes from the library, the providers' own answers and the runs.
A face may have "views" (each with its own three regions) when one screen is not enough for a focused tool. A face that lists others under "embeds" can show any of their views in its own workspace, beside its own toolbars. A face with "under": <host> is a project of that host: it has no tab of its own, it is shown in the host's row of faces with its own three regions, and it always has a Design view (its pipelines as the designer: list, picture, picked step) after its own views.
How much a face shows of a pipeline's inputs is data: "show": {input: "shown" | "advanced" | "fixed", "*": the rest, "roles": the role choices}, on a conversation panel or a runs panel ("show_for": {pipeline: {...}} for one pipeline); "inputs" gives the values that hold where nothing is shown.
Panels: params (the inputs of the conversation's pipeline at their levels: pipeline default, the face's, this conversation's), assets / records (what a provider lets a manager make there, and what such a thing holds), conversation / conversations / roles (a talk whose every turn is a run of the pipeline the face names, with the inputs the face gives it; the talks kept; who fills that pipeline's roles in this talk), runs (start a pipeline, follow and steer its runs), review (what work proposed to change in a space, to accept or reject), providers / bindings / limits / guide / library (where work is done, who fills which role by default, what the owner allows runs beyond the default, what is still missing, the stored objects as they are)."""
import re, json, html, time, uuid, asyncio, traceback, importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, quote
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

MODULE_META = {"label": "Corvid", "icon": "&#x1F426;", "description": "Faces of Aviary: converse, hand off work, see and steer what runs", "persistence": "user"}
router = APIRouter(redirect_slashes=False)
ENV, UI, BI, WS, IM, TM, CM, AV, PROV, ROLES, SEEN, STEPS, DATA, _P = {}, None, None, None, None, None, None, None, None, None, None, None, None, "/module/corvid"
LIVE, _STATE = ("running", "stopping"), {"done": "cv-ok", "running": "cv-mid", "stopping": "cv-mid", "interrupted": "cv-mid", "next": "cv-mid", "held": "cv-bad", "failed": "cv-bad", "unplaced": "cv-bad"}
REGIONS = {"main": "cv-workspace", "left": "cv-left", "right": "cv-right"}
CM_OPTS, CMS = {}, {}   # the chat interface's settings in Corvid, and one chat interface per face setting that differs from them
class _Live:
    """A live view of this module's globals for the helper files beside it: what they read is what is here now."""
    def __getattr__(self, k): return globals()[k]
def _beside(name: str):
    """A helper file beside this one, loaded by path the way the portal loads this module. Each holds panels of one subject, reads this file's parts through a live view (C, given to its init) and registers its own intents there."""
    spec = importlib.util.spec_from_file_location(f"modules.corvid_{name}", Path(__file__).parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
BESIDE = {name: _beside(name) for name in ("media", "assets", "machines", "figures", "shelf", "resources_view", "needs_view", "prompts_view", "loading_view", "status_view", "flow_view", "report_view", "watch_view", "members_view")}   # media: gallery and voice; assets: what providers hold (assets, records, graph); machines: each provider's programs, services, locations and own code; figures: what runs measured (chart, usage); shelf: providers, bindings, guide, limits and the library; watch_view: dashboards of views tied to a run's keys
MEDIA, ASSETS, MACHINES, FIGURES, SHELF = BESIDE["media"], BESIDE["assets"], BESIDE["machines"], BESIDE["figures"], BESIDE["shelf"]

# --- Parts ---

def _esc(s) -> str: return html.escape("" if s is None else str(s), quote=True)
def _attr(name: str, v: str) -> str: return f""" {name}="{_esc(v)}" """.rstrip() if v else ""
def _act(t: str, confirm: str = None, include: str = None, **kw) -> str: return f"""hx-post="/im/in" hx-swap="none" hx-vals="{_esc(json.dumps({"type": "corvid_" + t, "branch": IM.branch_id, "lvl": 1, **kw}))}"{_attr("hx-include", include)}{_attr("hx-confirm", confirm)}"""
def _btn(label: str, t: str, cls: str = "ui-btn", title: str = "", **kw) -> str: return f"""<button type="button" class="{cls}"{_attr("title", title)} {_act(t, **kw)}>{label}</button>"""
def _dim(text: str) -> str: return f"""<div class="cv-dim">{text}</div>""" if text else ""
def _note_oob(text: str, bad: bool = True) -> str: return f"""<div id="cv-msg" hx-swap-oob="innerHTML">{_note(text, bad)}</div>"""   # a note pushed to the page while nothing asked for it
def _note(text: str, bad: bool = False) -> str: return f"""<div class="{"cv-err" if bad else "cv-note"}">{_esc(text)}</div>"""
def _shown(v) -> str: return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
def _elid(s: str) -> str: return re.sub(r"[^\w-]", "_", s)   # a name made fit for an element id
def _slug(s: str, case: bool = False) -> str: return re.sub(r"[^\w.-]", "", re.sub(r"[\s-]+", "-", s.strip() if case else s.strip().lower()))   # case: capitals kept (a kind that says "keep_case")
def _when(t) -> str: return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""
def _user(request) -> str: return request.state.user.username
def _admin(request) -> bool: return getattr(request.state.user, "role", "") == "admin"
def _sec(title: str, body: str) -> str: return f"""<div class="cv-sec"><b>{_esc(title)}</b>{body}</div>"""
def _tab_row(bar_id: str, host_id: str, items: list) -> str:
    """A row of the portal's own tabs (UI.tab_bar / UI.tab) that switch something shown inside a face: items [(label, active, values for the face's open intent)]."""
    return UI.tab_bar("".join(UI.tab(_esc(label), active=on, focus_attrs=_act("open_tab", id=host_id, **kw)) for label, on, kw in items), id=bar_id, nesting_level=2)

def _faces() -> list: return sorted(AV.lib.list("face"), key=lambda f: f.get("order", 50))
DESIGN = {"id": "design", "name": "Design", "left": [{"panel": "flow", "part": "list", "title": "Pipelines"}], "main": [{"panel": "flow", "part": "picture"}], "right": [{"panel": "flow", "part": "step", "title": "Step"}]}   # the view every project has: tools left, the picture as the workspace, the picked step right

def _views(face: dict) -> list: return [*face.get("views", []), *([DESIGN] if face.get("under") and not any(v["id"] == "design" for v in face.get("views", [])) else [])]
def _embeds(host: dict) -> list: return [f for f in _faces() if f["id"] in host.get("embeds", []) or f.get("under") == host["id"]]   # the faces a host shows in its row: those it names, and its projects
def _layout(face: dict, tab: dict) -> dict:
    """The panels of the face's three regions as they are now: the face's own, or those of the view its tab shows when the face has views (a focused tool with more than one screen)."""
    vs = _views(face)
    return next((v for v in vs if v["id"] == tab.get("view")), vs[0]) if vs else face
def _spec(face: dict, key: str) -> dict: return _layout(face, {"view": key.split(":")[0]})[key.split(":")[1].split(".")[0]][int(key.split(".")[1])]   # key: "<view id>:<region>.<n>"
def _conv_spec(face: dict) -> dict: return next(sp for lay in (face.get("views") or [face]) for sp in lay.get("main", []) if sp["panel"] == "conversation")
def _modes(conv: dict, face_id: str) -> list: return [m for m in AV.lib.list("mode") if AV.lib.has("pipeline", m.get("pipeline", "")) and (conv.get("modes") == "*" or face_id in (m.get("faces") or []))]   # the saved ways of answering (library kind "mode": a pipeline with its inputs and who fills its roles) offered in a face: every one where the face says so ("modes": "*"), else those that name the face
def _mode(conv: dict, t: dict) -> dict: return next((m for m in _modes(conv, t["face"]) if m["id"] == t.get("mode")), {})   # the mode a conversation is in, when the face still offers it
def _base(conv: dict, t: dict) -> dict: return {**conv.get("inputs", {}), **(_mode(conv, t).get("inputs") or {})}   # the inputs that hold where the conversation set none of its own: the face's, then its mode's
def _pins(conv: dict, t: dict) -> dict: return {**(_mode(conv, t).get("pins") or {}), **t["pins"]}
def _pipe(spec: dict, t: dict) -> str: return m["pipeline"] if (m := _mode(spec, t)) else t.get("pipeline") if t.get("pipeline") in spec.get("pipelines", []) else spec["pipeline"]   # the conversation's mode decides, else its own choice among those the face allows, else the face's
def _cm(face_id: str):
    """The portal's chat interface as the face sets it: the face's "chat" {ChatManager option: value} over Corvid's defaults; one per distinct setting."""
    o, key = (AV.lib.get("face", face_id).get("chat") or {}) if AV.lib.has("face", face_id) else {}, ""
    if not o: return CM
    if (key := json.dumps(o, sort_keys=True)) not in CMS: CMS[key] = BI.ChatManager(**{**CM_OPTS, **o})
    return CMS[key]
def _guest(host: dict, tab: dict) -> tuple:
    """(guest face, its view id) when the host shows another face's view in its workspace, else (None, "")."""
    fid, _, vid = (tab.get("embed") or "").partition(":")
    return (AV.lib.get("face", fid), vid) if fid in [f["id"] for f in _embeds(host)] else (None, "")

def _cands(role: str, profiles: list) -> list: return ROLES.candidates(AV.lib, role, [x for x in profiles if AV.lib.has("bindings", x)])

def _group(fields: list):
    """Settings fields used as a form: rendered and parsed here, stored by the caller. Drawn in the portal's compact form (.settings-compact: label and control on one line, the hint under them)."""
    g = BI.SettingsGroup("form", "", fields, "")
    g.render = lambda values, fm=None, name_prefix="", draw=g.render: f"""<div class="settings-compact">{draw(values, fm=fm, name_prefix=name_prefix)}</div>"""
    return g

# --- What providers offer (asked for at most every few seconds, all at once) ---

OFFER_S = 30.0   # what a machine offers is asked again in the background once its last answer is this old (Aviary's seen); nothing waits for it

async def _offers() -> list: return _offers_now()

def _offers_now() -> list:
    """[{"p": provider, "assets": what it last said it offers, "error": why the last ask failed, "down": it was not reached, "pending": never answered yet, "age": how old the answer is, "asking"}] for every provider in the library, from what each last answered (Aviary's seen, kept across restarts). Nothing here waits on a machine: one asked again shows its last answer meanwhile."""
    ours = {re.sub(r"[^A-Za-z0-9_-]", "_", q["id"])[:40] for q in AV.lib.list("provider")}   # the names a node gives the routes this portal makes to its other machines (assets._from_elsewhere)
    def row(p):   # what a machine only passes on from another machine of this portal is shown where it is kept, once; a run placed on the passing machine still finds it there (placement asks the machine itself)
        r = AV.seen.get(f"""{p["id"]}:assets""", lambda: PROV.assets(p, timeout=8.0), OFFER_S)
        return {"p": p, "assets": [a for a in r["value"] or [] if a.get("source") not in ours], "error": r["error"], "down": r["away"], "pending": not r["t"] and not r["error"], "age": SEEN.age(r), "asking": r["asking"], "health": SEEN.health(r)}
    return [row(p) for p in AV.lib.list("provider")]

def _recheck(pid: str = ""): AV.seen.forget(f"{pid}:" if pid else "")   # after a change on a machine (an install, a copy, a new connection): asked again on the next look

def _mine(request, offers: list) -> list: return [{**o, "assets": [a for a in o["assets"] if AV.access.allowed(AV.lib, _user(request), o["p"]["id"], a["name"])]} for o in offers]   # what providers offer, less what a pool keeps from this person
def _usable(request, pid: str, asset: str) -> bool: return AV.access.allowed(AV.lib, _user(request), pid, asset)
_POOL = "~pool"   # a choice that is a pool, not one asset: "~pool|<pool id>"

def _choices(offers: list, need: dict, empty: str, pools: bool = True) -> list:
    """Select options for one role: every asset a provider offers for all the role needs, as "<provider id>|<asset>", then every pool with a member among them."""
    fits = lambda a: all(c in a.get("capabilities", []) for c in need.get("needs") or [])
    have = [(o["p"], a["name"], a.get("standby", ""), a.get("fits", "yes")) for o in offers for a in o["assets"] if fits(a)]   # fits: what the machine knows of the asset's fit for this capability (yes / owner / unknown / no)
    sets = ([(_POOL + "|*", "anything that fits now (any machine, any model that can)")] if have else []) + [(_POOL + "|" + p["id"], f"""any of the pool {p.get("name") or p["id"]}""") for p in AV.lib.list("pool") if any(AV.access.holds(p, q["id"], n) for q, n, *_ in have)] if pools else []
    empty += "" if have else f"""  -  no machine offers {" + ".join(need.get("needs") or ["it"])} now (its program off or not installed, or no model files where it looks)"""
    return [("", empty)] + [(p["id"] + "|" + n, n + "  -  " + (p.get("name") or p["id"]) + (f"  (its program {off} is off: turned on when used)" if off else "") + ({"owner": "  (offered by the owner's choice)", "unknown": "  (fit not known)", "no": "  (does not fit by its header)"}.get(ok, ""))) for p, n, off, ok in have] + sets

def _role_fields(roles: dict, offers: list, empty: str) -> list:
    """One choice per role; a role that takes several assets at once (its "many") has a tick list of further ones under it."""
    said = lambda need: " | ".join(x for x in (need.get("about", ""), "needs: " + ", ".join(need.get("needs") or [])) if x)
    return [f for r, need in roles.items() for f in (BI.SettingField(r, r, "select", options=_choices(offers, need, empty), hint=said(need)), *([BI.SettingField(r + ".also", f"{r}: together with", "checklist", options=_choices(offers, need, "", pools=False)[1:], hint="Ticked ones are used together with the choice above.")] if need.get("many") else []))]

def _cand(v: str) -> dict: return {"pool": v.split("|", 1)[1]} if v.startswith(_POOL + "|") else dict(zip(("provider", "asset"), v.split("|", 1)))   # a role choice as a candidate
def _cand_v(b: dict) -> str: return _POOL + "|" + b["pool"] if b.get("pool") and not b.get("pinned") and "asset" not in b else (b.get("provider", "") + "|" + b["asset"]) if b.get("asset") else ""
def _role_values(bound: dict) -> dict: return {k: v for r, b in bound.items() for k, v in ((r, _cand_v(b)), (r + ".also", [_cand_v(a) for a in b.get("also", [])]))}

def _picked(form: dict, roles: dict, prefix: str = "") -> dict:
    """The role choices of a form as pins: {role: {"provider", "asset"} or {"pool"}, with "also": [...] for a role that takes several}."""
    also = lambda r: [_cand(v) for v in BI.SettingField(r + ".also", "", "checklist").checklist_value(form, prefix) if v and v != form[prefix + r]]
    return {r: {**_cand(form[prefix + r]), **({"also": more} if need.get("many") and (more := also(r)) else {})} for r, need in roles.items() if form.get(prefix + r)}

def older(e: Exception, what: str) -> str:
    """A provider's error in words. A route the machine does not know (404 without a reason of its own) means its Magpie is older than what this portal asks of it: said so, with what to do."""
    if " 401" in str(e) or "with 401" in str(e): return f"""{e} - the machine does not know the key stored here for it. Change the provider (Settings, Work), paste the machine's key into "API key" again and Save; a browser may have filled that field with your portal password."""
    return f"""{e} - this machine's Magpie has no way to {what} yet: it is older than this portal's Corvid. Bring Magpie on it up to date (copy the Magpie files to it and restart the node), then try again.""" if '"detail":"Not Found"' in str(e) else str(e)

def _unreached(offers: list) -> str:
    """Machines not answering now (asleep, off, away) in one quiet line: what they offer is left out, nothing else is held up. Any other answer from a machine (a fault) stays a warning."""
    down, asked = [o["p"].get("name") or o["p"]["id"] for o in offers if o.get("down")], [o["p"].get("name") or o["p"]["id"] for o in offers if o.get("pending")]
    return (_dim(f"""Still being asked (shown when this opens again): {_esc(", ".join(asked))}""") if asked else "") + (_dim(f"""Not answering now, so left out until they do (tried again after a while, longer while they stay silent): {_esc(", ".join(down))}""") if down else "") + "".join(_note(o["error"], True) for o in offers if o["error"] and not o.get("down"))
def _all_roles() -> dict:
    """Every role any pipeline in the library names, with what they say of it together: the capabilities any of them needs, every fact any of them works out for its cases, what each says it is for."""
    out = {}
    for pl in AV.lib.list("pipeline"):
        for r, need in (pl.get("roles") or {}).items():
            o = out.setdefault(r, {"needs": [], "facts": {}, "abouts": []})
            o["needs"] += [c for c in need.get("needs") or [] if c not in o["needs"]]
            o["facts"].update(need.get("facts") or {})
            if need.get("about") and need["about"] not in o["abouts"]: o["abouts"].append(need["about"])
    return {r: {**o, "about": " / ".join(o["abouts"])} for r, o in out.items()}
def _profile(pid: str) -> dict: return AV.lib.get("bindings", pid) if AV.lib.has("bindings", pid) else {"id": pid, "roles": {}}
def _no_pipelines() -> str: return _note(f"""The library holds no pipelines, so there are no roles to fill and nothing to run. The shipped ones belong in {AV.lib.shipped[0] / "pipeline"} (chat_turn.json, measure_text.json); that folder is empty or missing on this portal.""", True)

# --- Kept choices used across panels ---

def _option(v, label, on) -> str: return f"""<option value="{_esc(v)}" {"selected" if v == on else ""}>{_esc(label)}</option>"""
def _options(pairs, on) -> str: return "".join(_option(v, l, on) for v, l in pairs)
_LIMITS = {"python": ("Who may run Python code of their own choosing", "Code given when the work starts, or read from a file that can change. It runs as the portal itself: it can read, change and delete anything the portal can, and reach the network."),
           "python_fixed": ("Who may run pipelines with Python code written into them", "The code is part of the pipeline and shown before it starts; only those who may change pipelines can change it (an approved tool used from Athena, for example). It still runs as the portal itself.")}   # each is the owner's decision alone; Aviary only asks what is set here

# --- Panel: runs (start a pipeline, follow and steer what runs) ---

_FIELD = {"boolean": "checkbox", "integer": "number", "number": "number", "list": "json", "object": "json", "code": "textarea", "long": "textarea", "items": "items"}
def _levels(show: dict, keys) -> dict:
    """How much a face shows of each input: "shown", "advanced" (under More) or "fixed" (not shown: the face's value holds). show: {input: level, "*": the level of every input it does not name}."""
    return {k: show.get(k, show.get("*", "shown")) for k in keys}

def _exposed(fields: list, levels: dict, values: dict, prefix: str, form_id: str, fm=None) -> str:
    """Settings fields at their levels, drawn by the portal's settings group: the shown ones, the advanced ones in its Advanced section, a fixed one not at all. Also tells the form which fields it holds, so an unticked box is told from one that was not there. fm: the file manager an items field picks from."""
    values = {k: v for k, v in values.items() if v is not None}   # an input with no value yet shows its field's own empty state
    level = lambda f: levels.get(f.name, levels.get(f.name.split(".")[0], "shown"))   # a field that is one part of a parameter ("<parameter>.<option>") has its parameter's level
    held = [f for f in fields if level(f) != "fixed"]
    for f in held: f.advanced = level(f) == "advanced"
    return f"""{_group(held).render(values, fm=fm, name_prefix=prefix) if held else ""}<input type="hidden" name="{prefix}_held" value="{_esc(",".join(f.name for f in held))}">"""

def _held(payload: dict, prefix: str) -> set: return set(filter(None, payload.get(prefix + "_held", "").split(",")))

def _may(request) -> list: return [what for what in _LIMITS if AV.allows(what, _user(request), _admin(request))]   # what the owner's policy allows this person's runs beyond the default
def _free_code(plan: dict) -> list: return [st for st in _code_steps(plan) if not (st.get("config") or {}).get("script")]   # code steps whose code is not written into the pipeline
def _code_steps(plan: dict) -> list:
    """Every step of a plan that runs code, also inside groups and inside plans written into a step."""
    out = []
    for st in plan.get("steps", []): out += ([st] if st.get("type") == "python" else []) + _code_steps(st) + _code_steps((st.get("config") or {}).get("plan") or {})
    return out
def _param_fields(pl: dict, assets: dict = None) -> list:
    """A pipeline's parameters as form fields. "pick_from": [[value, label]] a fixed choice; "pick": <library kind> makes one a choice among that kind's objects (a space, a prompt, ...), with "many": true a tick list of them. "pick_assets": <capability> a tick list of what the machines offer under that capability (LoRAs: "lora"), by name. "type": "options" with "of": <role> stands for the options the asset filling that role lists for its own program: one field each (_option_fields). assets: {role: that asset, as its provider lists it} (_role_assets)."""
    picks = lambda p: [(o["id"], o.get("name") or o["id"]) for o in AV.lib.list(p["pick"])]
    def one(k, p):
        if p.get("pick_from"): return [BI.SettingField(k, p.get("label") or k, "select", default=p.get("default"), options=[tuple(o) for o in p["pick_from"]], hint=p.get("hint", ""))]   # a fixed choice: [[value, label], ...]
        if p.get("type") == "mask": return []   # drawn over its picture by _masks, not a field of its own
        if p.get("pick_assets") and p.get("strengths") and (offered := sorted({x["name"] for o in _offers_now() for x in o["assets"] if p["pick_assets"] in (x.get("capabilities") or [])})): return [BI.SettingField(f"{k}.{n}", n, "number", default=(p.get("default") or {}).get(n), step=0.05, hint=p.get("hint", "") if i == 0 else "", section=p.get("label") or k) for i, n in enumerate(offered)]   # "strengths": true - a number beside each offered file instead of a tick ("<parameter>.<file>"); gathered into {file: strength} (_gathered)
        if p.get("pick_assets"): return [BI.SettingField(k, p.get("label") or k, "checklist", default=p.get("default") or [], options=sorted({(x["name"], x["name"], "on " + ", ".join(sorted(o["p"].get("name") or o["p"]["id"] for o in _offers_now() for y in o["assets"] if y["name"] == x["name"]))) for o in _offers_now() for x in o["assets"] if p["pick_assets"] in (x.get("capabilities") or [])}), hint=p.get("hint", "") or f"""What the machines that answer offer as {p["pick_assets"]}.""")]   # files a machine offers by name (LoRAs, voices ...), ticked instead of typed
        if p.get("pick") and p.get("many"): return [BI.SettingField(k, p.get("label") or k, "checklist", default=p.get("default") or [], options=[(o["id"], o.get("name") or o["id"], o.get("about", "")) for o in AV.lib.list(p["pick"])], hint=p.get("hint", ""))]   # several of a kind, ticked
        return [BI.SettingField(k, p.get("label") or k, "select" if p.get("pick") else _FIELD.get(p.get("type"), "text"), default=p.get("default"), options=([("", "(none)")] if p.get("default") == "" else []) + picks(p) if p.get("pick") else None, hint=p.get("hint", ""), step=1 if p.get("type") == "integer" else None)]   # a pick whose default is empty may be left unchosen
    return [f for k, p in (pl.get("params") or {}).items() for f in (_option_fields(k, (assets or {}).get(p.get("of")) or {}) if p.get("type") == "options" else one(k, p))]

_OWN = "(its own default)"
def _option_fields(key: str, asset: dict) -> list:
    """One form field per option an asset lists for its own program ("options": {name: {"type", "label", "hint", "default", "choices"}}), named "<parameter>.<option>". Every one can be left empty: it is then not sent, and the program's own default holds."""
    def one(n, o):
        kind, opts = ("select", [("", _OWN), *((str(c), str(c)) for c in o["choices"])]) if o.get("choices") else ("select", [("", _OWN), ("true", "yes"), ("false", "no")]) if o.get("type") == "boolean" else (_FIELD.get(o.get("type"), "text"), None)
        return BI.SettingField(f"{key}.{n}", o.get("label") or n, kind, options=opts, hint=" ".join(x for x in (o.get("hint", ""), f"""Its own default: {_shown(o["default"])}.""" if o.get("default") is not None else "", f"""An option of {asset["name"]}.""") if x), step=1 if o.get("type") == "integer" else None)
    return [one(n, o) for n, o in (asset.get("options") or {}).items()]

def _role_assets(pl: dict, offers: list, profiles: list, pins: dict = None) -> dict:
    """{role: the asset that fills it as things stand (the pin, else the profiles' first candidate), as its provider lists it}: what a form can show of an asset before anything runs. A role nothing fills yet is left out."""
    out = {}
    for r in pl.get("roles") or {}:
        c = (pins or {}).get(r) or next(iter(_cands(r, profiles)), None)
        if c and (a := next((a for o in offers for a in o["assets"] if a["name"] == c.get("asset") and c.get("provider") in (None, "", o["p"]["id"])), None)): out[r] = a
    return out

def _spread(values: dict, params: dict) -> dict:
    """Values as the form's fields take them: an options parameter's object spread over its "<parameter>.<option>" fields."""
    return {**values, **{f"{k}.{n}": json.dumps(v) if isinstance(v, bool) else v for k, p in params.items() if p.get("type") == "options" for n, v in (values.get(k) or {}).items()}}

def _gathered(vals: dict, params: dict, assets: dict) -> dict:
    """The form's values with each options parameter gathered back into one object: an option left empty is left out, a yes/no option becomes true or false. A "strengths" parameter likewise: {file: strength} of the ones given a strength. A parameter none of whose fields were in the form is left out, so the value that holds without the form stays."""
    part = lambda k: "." in k and (params.get(k.split(".")[0], {}).get("type") == "options" or params.get(k.split(".")[0], {}).get("strengths"))   # a field that is one part of a parameter
    out = {k: v for k, v in vals.items() if not part(k)}
    for k, p in params.items():
        if p.get("strengths") and any(n.startswith(k + ".") for n in vals): out[k] = {n[len(k) + 1:]: v for n, v in vals.items() if n.startswith(k + ".") and v not in ("", None, 0, "0")}
        kinds = {n: o.get("type") for n, o in ((assets.get(p.get("of")) or {}).get("options") or {}).items()} if p.get("type") == "options" else {}
        if any(f"{k}.{n}" in vals for n in kinds): out[k] = {n: (vals[f"{k}.{n}"] == "true") if kinds[n] == "boolean" else vals[f"{k}.{n}"] for n in kinds if vals.get(f"{k}.{n}") not in ("", None)}
    return out

def _run(request, rid: str):
    """The run, for its owner or an admin."""
    r = AV.director.runs[rid]
    if not (_admin(request) or r.meta.get("owner") == _user(request)): raise PermissionError(f"run {rid} belongs to someone else")
    return r

def _about(r) -> str:
    """What a run was asked to do, in a few words: the inputs its pipeline names under "about" (else its first parameters), as given."""
    keys = r.plan.get("about") or [k for k, p in (r.plan.get("params") or {}).items() if p.get("type") not in ("code", "boolean", "integer", "number") and not p.get("pick")][:2]
    short = lambda v: (", ".join(map(str, v[:3])) + (f" and {len(v) - 3} more" if len(v) > 3 else "")) if isinstance(v, list) else _shown(v)
    return " | ".join(short(r.data[k])[:90] for k in keys if r.data.get(k) not in (None, "", []))

def _run_row(face_id: str, r) -> str:
    v, st = r.view(), r.meta["state"]
    acts = _btn("Open", "run_view", id=r.id) + (_btn("Stop", "run_stop", face=face_id, id=r.id, title="No further steps start; those working finish") + _btn("Stop now", "run_stop", "ui-btn cv-danger", face=face_id, id=r.id, now="1", title="Steps working are cut off too; what they had not kept is done again if it goes on") if st in LIVE else (_btn("Go on", "run_go", face=face_id, id=r.id) if st != "done" else "") + _btn("Again", "run_again", face=face_id, id=r.id, title="A new run with the same inputs: syncs the same files again, asks the same again") + _btn("Change, then again", "run_edit", face=face_id, id=r.id, title="Its form, filled with what it was given: change what you want, then Start") + _btn("&#x2715;", "run_remove", "ui-btn cv-small", face=face_id, id=r.id, confirm="Remove this run and its records?"))
    info = " | ".join(x for x in (f"""{len(r.plan["steps"])} steps""" if st == "done" else f"""{len(v["done"])} of {len(r.plan["steps"])} steps""", ", ".join(v["busy"]), _when(r.meta["created"]), _esc(r.meta.get("owner", ""))) if x)
    err = f"""<div class="cv-bad" style="white-space:pre-wrap;overflow-wrap:anywhere">{_esc(r.meta["error"])}</div>""" if r.meta.get("error") else ""   # in full: what stands in the way is the part worth reading
    return f"""<div class="list-row"><div class="row" style="flex-wrap:wrap"><b class="grow">{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(st, "")}">{_esc(st)}</span>{acts}</div><div class="pre-wrap" style="overflow-wrap:anywhere">{_esc(_about(r)[:300])}</div>{_dim(info)}{err}</div>"""   # what the run is about under its name: a side toolbar keeps its width for the text, and a long input (a picture's data) is cut

def _run_list(request, face: dict, key: str) -> str:
    """The runs this person may see here (their own; an admin: everyone's), of the groups the panel shows, newest first. Polls itself while one is under way."""
    spec = _spec(face, key)
    runs = sorted((r for r in AV.director.runs.values() if not r.meta.get("parent") and (_admin(request) or r.meta.get("owner") == _user(request)) and (not spec.get("groups") or r.plan.get("group") in spec["groups"])), key=lambda r: r.meta["created"], reverse=True)[:30]   # a run made by another run's step is shown inside that run
    poll = f"""hx-get="{_P}/runs?face={_esc(face["id"])}&amp;key={key}" hx-trigger="every 2s" hx-swap="outerHTML" """ if any(r.meta["state"] in LIVE for r in runs) else ""
    ended = [r.id for r in runs if r.meta["state"] not in LIVE]
    clear = f"""<div class="row"><span class="grow"></span>{_btn(f"Remove the {len(ended)} that ended", "run_remove", "ui-btn cv-small", face=face["id"], ids=",".join(ended), confirm="Remove every run here that is not under way, with its records?")}</div>""" if len(ended) > 1 else ""
    return f"""<div id="cv-runs" {poll}>{clear}{"".join(_run_row(face["id"], r) for r in runs) or _dim("nothing has run here yet")}</div>"""

async def p_runs(c) -> str:
    plans = "".join(f"""<div class="list-row"><div class="row"><b class="grow">{_esc(pl.get("name") or pl["id"])}</b>{_btn("Set up", "run_form", face=c.face["id"], id=pl["id"], key=c.key)}</div><div class="cv-dim">{_esc(pl.get("objective", ""))[:170]}</div></div>""" for pl in AV.lib.list("pipeline") if (not c.spec.get("groups") or pl.get("group") in c.spec["groups"]) and (not c.spec.get("pipelines") or pl["id"] in c.spec["pipelines"]))   # a runs panel offers the pipelines of its groups, or those it names
    return f"""{_dim("A pipeline says what is to be done; Aviary decides how, with what is free. A run goes on when this page is closed.")}{plans or _no_pipelines()}<div id="cv-run-form"></div>{_run_list(c.request, c.face, c.key)}"""

def _run_spec(payload: dict) -> dict: return _spec(AV.lib.get("face", payload["face"]), payload["key"]) if payload.get("key") else {}

def _setups(pid: str) -> list: return [s for s in AV.lib.list("setup") if s.get("pipeline") == pid]

def _setup_row(face_id: str, pl: dict, key: str, cur: str = "") -> str:
    """The saved set-ups of a pipeline (library kind "setup": {"id", "name", "pipeline", "inputs", "pins", "owner"}): a named set of its inputs and role choices, loaded into the run form or saved from it. The same for every pipeline: a selection of files to sync again, a measurement's settings, a question with its options."""
    kw, have = {"face": face_id, "id": pl["id"], "key": key, "include": "#cv-run-f"}, _setups(pl["id"])
    opts = _options([("", "(saved set-ups)" if have else "(no saved set-ups yet)")] + [(s["id"], " - ".join(x for x in (s.get("name") or s["id"], s.get("owner", "")) if x)) for s in have], cur)
    return f"""<div class="row" style="flex-wrap:wrap"><select name="setup" class="module-select">{opts}</select>{_btn("Load", "run_setup", do="load", **kw)}{_btn("Remove", "run_setup", "ui-btn cv-danger", do="remove", confirm="Remove the chosen set-up? It is kept as an earlier version in the library.", **kw)}<span class="grow"></span><input name="setup_name" class="module-select" style="width:11rem" placeholder="name (optional)" title="Left empty: the chosen set-up is saved over (its earlier version is kept), or a new one is named after the pipeline and the time.">{_btn("Save this set-up", "run_setup", title="Keeps these inputs and role choices under a name in the portal's library, where everyone who can open this sees them", do="save", **kw)}</div>"""

async def _run_form_html(request, face_id: str, pid: str, key: str, picked: dict = None, pins: dict = None, setup: str = "") -> str:
    """The form that sets up one pipeline's run. picked: values to show instead of the defaults (the files just uploaded, ticked; a saved set-up's inputs). pins: who fills which role, shown chosen (a saved set-up's). setup: the saved set-up shown as chosen."""
    pl, offers, spec = AV.lib.get("pipeline", pid), _mine(request, await _offers()), _run_spec({"face": face_id, "key": key})
    show = {**spec.get("show", {}), **spec.get("show_for", {}).get(pl["id"], {})}   # the panel's levels for every pipeline it lists, then those it gives for this one
    params, assets = pl.get("params") or {}, _role_assets(pl, offers, AV.lib.get("face", face_id).get("profiles", []), pins)
    draft, dpins = DRAFTS.get((_user(request), face_id, pid), ({}, {}))   # what this person last filled in on this form, on any tab, until a run starts from it
    values, pins = {**{k: spec.get("inputs", {}).get(k, p.get("default")) for k, p in params.items()}, **draft, **(picked or {})}, pins if pins is not None else dpins or None
    items = next((k for k, p in params.items() if p.get("type") == "items"), None)
    fm = AV.space(values[params[items]["space_from"]])[0] if items else None
    role_level = show.get("roles", show.get("*", "shown"))
    levels = {r: show.get(f"role.{r}", role_level) for r in pl.get("roles") or {}}   # "role.<name>": one role's own level (a role the face fills from elsewhere is "fixed")
    roles = "" if all(v == "fixed" for v in levels.values()) else _exposed(_role_fields(pl.get("roles") or {}, offers, "(placed when it starts)"), levels, _role_values(pins or {}), "r_", "cv-run-f")
    code, sure = _code_steps(pl), ""
    if code and not {"python" if _free_code(pl) else "python_fixed"} <= set(_may(request)): sure = _note("This pipeline runs " + ("Python code of your own choosing" if _free_code(pl) else "the Python code written into it") + ", and you are not among those who may on this portal. The owner decides who may: Settings, Limits.", True)
    elif code and not _free_code(pl): sure = _dim("Runs the Python code written into this pipeline: " + ", ".join(st["id"] for st in code) + ".") + "".join(f"""<details><summary class="cv-dim">step {_esc(st["id"])}: the code</summary><div class="quote-block mono cv-log">{_esc(st["config"]["script"])}</div></details>""" for st in code)
    elif code:
        shown = "".join(f"""<details><summary class="cv-dim">step {_esc(st["id"])}: the code</summary><div class="quote-block mono cv-log">{_esc((st.get("config") or {}).get("script") or "given when it runs (a parameter or a file)")}</div></details>""" for st in code)
        sure = f"""<div class="cv-err">This pipeline runs Python code as the portal itself: it can read, change and delete anything the portal can, and reach the network. Nothing limits it once started.{shown}<label><input type="checkbox" name="sure" value="1"> I have looked at what it runs and want it to run</label></div>"""
    upload = f"""<form class="cv-form" hx-post="{_P}/upload" hx-encoding="multipart/form-data" hx-target="#cv-run-form" hx-swap="innerHTML"><b>Bring files into {_esc(AV.lib.get("space", values[params[items]["space_from"]]).get("name") or values[params[items]["space_from"]])}</b>{_dim("From this computer, into a folder of the space; they are then ticked above.")}<input type="hidden" name="face" value="{_esc(face_id)}"><input type="hidden" name="pid" value="{_esc(pid)}"><input type="hidden" name="key" value="{_esc(key)}"><input type="hidden" name="space" value="{_esc(values[params[items]["space_from"]])}"><input type="hidden" name="field" value="{_esc(items)}">{_dim("Into the folder ticked here (the space itself when none is):")}{fm.folder_picker_html()}<div class="row"><input name="new_folder" class="module-select grow" placeholder="a new folder inside it (optional)"></div><div class="row"><input type="file" name="files" multiple class="module-select grow"><button type="submit" class="ui-btn">Upload</button></div></form>""" if items else ""
    return f"""<form class="cv-form" id="cv-run-f" onsubmit="return false" {_act("run_draft", face=face_id, id=pid, key=key)} hx-trigger="change delay:400ms" hx-disinherit="*"><div class="row"><b class="grow">{_esc(pl.get("name") or pl["id"])}</b><label class="cv-dim" title="Started with priority: a machine whose memory is held by other work stops giving that work new requests, so this starts as soon as what it is doing now has ended (without it, the machine waits up to its longest wait first - Asio, Loading)"><input type="checkbox" name="first" value="1"> go first</label>{_btn("Start", "run_start", face=face_id, id=pl["id"], key=key, include="#cv-run-f")}{_btn("Close", "run_form", face=face_id, close="1")}</div>{_dim(_esc(pl.get("objective", "")))}{_setup_row(face_id, pl, key, setup)}{_exposed(_thumbed(_param_fields(pl, assets), values[params[items]["space_from"]] if items else ""), _levels(show, params), _spread(values, params), "p_", "cv-run-f", fm)}{_masks(params, values, show)}{_unreached(offers) if pl.get("roles") else ""}{roles}{sure}</form>{upload}"""

def _thumbed(fields: list, space: str) -> list:
    """Picture files in a field's tree of a space shown as small pictures (built_ins items picker, thumb_url); loaded only when their folder is open."""
    for f in fields:
        if f.type == "items" and space: f.thumb_url = lambda rel, s=space: f"{_P}/thumb/{quote(s)}/{quote(rel)}"
    return fields

def _masks(params: dict, values: dict, show: dict) -> str:
    """Each "mask" parameter as a drawing over the picture its "over" parameter picked: white is painted again, the rest is kept. The drawing travels as a PNG data URI in a hidden field, so the form gathers it like any other value."""
    out = ""
    for k, p in params.items():
        if p.get("type") != "mask" or show.get(k) == "fixed": continue
        cid, space = f"cv-mask-{k}", values.get(params[p["over"]].get("space_from", ""), "media")
        out += f"""<div class="cv-form"><b>{_esc(p.get("label") or k)}</b>{_dim(_esc(p.get("hint", "Paint over what should change. White is painted again; the rest of the picture is kept.")))}
               <div class="row"><label class="cv-dim">brush <input type="range" min="4" max="160" value="40" id="{cid}-size"></label><button type="button" class="ui-btn cv-small" onclick="cvMask.clear('{cid}')">Clear</button><button type="button" class="ui-btn cv-small" onclick="cvMask.erase('{cid}', this)">Erase</button></div>
               <div style="position:relative;display:inline-block;max-width:100%"><img id="{cid}-img" style="max-width:100%;display:block" alt=""><canvas id="{cid}" style="position:absolute;left:0;top:0;width:100%;height:100%;opacity:.55;cursor:crosshair;touch-action:none"></canvas></div>
               <input type="hidden" name="p_{k}" id="{cid}-v"><span class="cv-dim" id="{cid}-none">Pick the picture above first.</span>
               <script>cvMask.init("{cid}", "p_{p["over"]}", "{_P}/media/{quote(space)}/")</script></div>"""
    return (_MASK_JS + out) if out else ""

_MASK_JS = """<script>window.cvMask = window.cvMask || {
  init(id, over, base) {
    const cv = document.getElementById(id), img = document.getElementById(id + "-img"), val = document.getElementById(id + "-v"), none = document.getElementById(id + "-none"), form = cv.closest("form");
    const pick = () => { const c = form.querySelector('[name="' + over + '"]:checked') || form.querySelector('[name="' + over + '"]'), v = c ? c.value : ""; if (!v.startsWith("[")) return v; try { return JSON.parse(v).find(x => /\\.(png|jpe?g|webp|gif|bmp)$/i.test(x)) || ""; } catch (e) { return ""; } };
    const load = () => { const p = pick(); if (!p) return; none.style.display = "none"; img.onload = () => { cv.width = img.naturalWidth; cv.height = img.naturalHeight; const x = cv.getContext("2d"); x.fillStyle = "#000"; x.fillRect(0, 0, cv.width, cv.height); val.value = ""; }; img.src = base + p.split("/").map(encodeURIComponent).join("/"); };
    let last = pick();
    form.addEventListener("change", e => { if (e.target.name === over) { last = pick(); load(); } });
    const watch = setInterval(() => { if (!document.body.contains(cv)) return clearInterval(watch); const p = pick(); if (p !== last) { last = p; load(); } }, 700);   // a tree picker writes its hidden value without a change event
    let down = false;
    const at = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
    const dot = e => { if (!down || !cv.width) return; const x = cv.getContext("2d"), [px, py] = at(e), s = document.getElementById(id + "-size").value * cv.width / cv.getBoundingClientRect().width; x.fillStyle = cv.dataset.erase ? "#000" : "#fff"; x.beginPath(); x.arc(px, py, s / 2, 0, 7); x.fill(); };
    cv.addEventListener("pointerdown", e => { down = true; cv.setPointerCapture(e.pointerId); dot(e); });
    cv.addEventListener("pointermove", dot);
    cv.addEventListener("pointerup", () => { down = false; val.value = cv.toDataURL("image/png"); });
    load();
  },
  clear(id) { const cv = document.getElementById(id), x = cv.getContext("2d"); x.fillStyle = "#000"; x.fillRect(0, 0, cv.width, cv.height); document.getElementById(id + "-v").value = ""; },
  erase(id, b) { const cv = document.getElementById(id); cv.dataset.erase = cv.dataset.erase ? "" : "1"; b.textContent = cv.dataset.erase ? "Paint" : "Erase"; }
};</script>"""

async def _h_run_form(request, payload, imr):
    if payload.get("close"): return imr.oob("", "cv-run-form")
    return imr.oob(await _run_form_html(request, payload["face"], payload["id"], payload.get("key", "")), "cv-run-form")

CHOSEN: dict = {}   # name -> fn(request) -> value: what a person has chosen on a panel (prompts_view: "prompt"), for a run form whose spec says "inputs_from": {input: name}

async def _run_given(request, payload: dict, pl: dict, face: dict) -> tuple:
    """(inputs, pins) as a submitted run form holds them: what the form did not hold is the panel's own value, else the pipeline's default."""
    spec, held, params, pins = _run_spec(payload), _held(payload, "p_"), pl.get("params") or {}, _picked(payload, pl.get("roles") or {}, "r_")
    assets = _role_assets(pl, _mine(request, await _offers()), face.get("profiles", []), pins)
    form = {**_gathered({k: v for k, v in _group(_param_fields(pl, assets)).parse(payload, "p_").items() if k in held}, params, assets), **{k: payload.get(f"p_{k}", "") for k, p in params.items() if p.get("type") == "mask"}}   # a drawn mask is its own hidden field (_masks), not one of the form's fields
    given, chosen_pins = _spec_given(request, spec, pl)
    out = {**given, **{k: v for k, v in form.items() if v not in ("", None, {}, [])}}
    for k, why in (spec.get("requires") or {}).items():   # what a panel says must be there before its run starts (Sunbird: the chosen prompt's encoding - painting there never encodes)
        if out.get(k) in ("", None, [], {}): raise ValueError(why)
    return out, {**chosen_pins, **pins}   # who fills a role: the form's choice, else the panel's

def _spec_given(request, spec: dict, pl: dict) -> tuple:
    """(inputs, pins) a panel's spec gives a run of pl: its fixed "inputs", then what is chosen elsewhere on the face ("inputs_from", "pins_from": the prompt chosen on the left, its own encoder), as it stands at this moment."""
    params, roles_ = pl.get("params") or {}, pl.get("roles") or {}
    return {**{k: v for k, v in spec.get("inputs", {}).items() if k in params}, **{k: CHOSEN[src](request) for k, src in spec.get("inputs_from", {}).items() if k in params}}, {r: v for r, src in spec.get("pins_from", {}).items() if r in roles_ and (v := CHOSEN[src](request))}

async def _h_run_setup(request, payload, imr):
    """A saved set-up loaded into the run form, the form saved as one, or one removed. Saving over or removing someone else's is an admin's to do; the library keeps the version before every save and removal."""
    face, pl, do, user, chosen = AV.lib.get("face", payload["face"]), AV.lib.get("pipeline", payload["id"]), payload["do"], _user(request), payload.get("setup", "")
    again = lambda picked=None, pins=None, cur="": _run_form_html(request, face["id"], pl["id"], payload.get("key", ""), picked, pins, cur)
    sid = chosen if do != "save" else _slug(payload.get("setup_name", "")) or chosen or _slug(f"""{pl["id"]}-{time.strftime("%Y-%m-%d-%H%M")}""")
    old = AV.lib.get("setup", sid) if sid and AV.lib.has("setup", sid) else None
    if do != "save" and not old: return imr.oob(_note("Choose a saved set-up first.", True), "cv-msg")
    if do == "load": return imr.oob(await again(old.get("inputs"), old.get("pins"), sid), "cv-run-form")
    if old and old.get("owner") != user and not _admin(request): return imr.oob(_note(f"""{old.get("name") or sid} was saved by {old.get("owner") or "someone else"}: save yours under another name.""", True), "cv-msg")
    if do == "remove":
        AV.lib.remove("setup", sid)
        return imr.oob(await again(), "cv-run-form").oob(_note(f"""Removed the set-up {old.get("name") or sid}; the library keeps it as an earlier version."""), "cv-msg")
    try: given, pins = await _run_given(request, payload, pl, face)
    except BI.SettingsError as e: return imr.oob(_note(f"Not saved: {e}", True), "cv-msg")
    AV.lib.save("setup", {"id": sid, "name": payload.get("setup_name", "").strip() or (old or {}).get("name") or sid, "pipeline": pl["id"], "inputs": given, "pins": pins, "owner": (old or {}).get("owner") or user}, by=user)
    return imr.oob(await again(given, pins, sid), "cv-run-form").oob(_note(f"Saved the set-up {sid}. Load brings it back into this form; Start runs what the form shows."), "cv-msg")

async def _h_run_start(request, payload, imr):
    face, pl = AV.lib.get("face", payload["face"]), AV.lib.get("pipeline", payload["id"])
    if _code_steps(pl) and ("python" if _free_code(pl) else "python_fixed") not in _may(request): return _refused(imr, ("Not started: it runs Python code, and you are not among those who may start that here (Settings, Limits)."))
    if _free_code(pl) and not payload.get("sure"): return _refused(imr, ("Not started: it runs Python code, and the box saying you have looked at it is not ticked."))
    try:
        given, pins = await _run_given(request, payload, pl, face)
        rid = await AV.start(pl, given, owner=_user(request), profiles=face.get("profiles", []), pins=pins, priority=1 if payload.get("first") else 0, may=_may(request))
    except ValueError as e: return _refused(imr, (f"Not started: {e}"))
    DRAFTS.pop((_user(request), face["id"], pl["id"]), None)   # started: the form opens with its defaults again
    return await _refresh(request, imr, face["id"], _note(f"Started as {rid}."))

DRAFTS: dict = {}   # (user, face, pipeline) -> (form values, role picks): a run form as last filled in, kept in memory while the portal runs

async def _h_run_draft(request, payload, imr):
    """Keeps what a run form holds as it is filled in, so leaving the tab and coming back (or opening the same form elsewhere on the face) finds it as it was. A drawn mask is not kept."""
    pl = AV.lib.get("pipeline", payload["id"])
    held, params, pins = _held(payload, "p_"), pl.get("params") or {}, _picked(payload, pl.get("roles") or {}, "r_")
    assets = _role_assets(pl, _mine(request, await _offers()), AV.lib.get("face", payload["face"]).get("profiles", []), pins)
    try: DRAFTS[(_user(request), payload["face"], pl["id"])] = (_gathered({k: v for k, v in _group(_param_fields(pl, assets)).parse(payload, "p_").items() if k in held and params.get(k, {}).get("type") != "mask"}, params, assets), pins)
    except BI.SettingsError: pass   # a field still being typed (half-written JSON): the last draft that read stays; Start reports the field
    return imr

def _refused(imr, text: str):
    """Why a run did not start, at the top of the workspace and in an open "Change, then again" window (which would otherwise hide it)."""
    return imr.oob(_note(text, True), "cv-msg").oob(_note(text, True), "cv-edit-msg")

async def _h_run_edit(request, payload, imr):
    """The form of an ended run's pipeline in a window, filled with what that run was given and who filled its roles: changed there, then started as a new run."""
    old = _run(request, payload["id"])
    pid = old.plan["id"] if old.plan.get("id") and AV.lib.has("pipeline", old.plan["id"]) else ""
    if not pid: return imr.oob(_note("Its pipeline is no longer in the library, so there is no form for it: Again runs it as it was.", True), "cv-msg")
    given = {k: old.data[k] for k in (AV.lib.get("pipeline", pid).get("params") or {}) if k in old.data}
    form = await _run_form_html(request, payload["face"], pid, payload.get("key", ""), given, old.meta.get("pins", {}))
    return imr.oob(UI.modal("cv-edit", "Change, then run again", f"""<div id="cv-edit-msg"></div>{_dim("What the run was given, filled in. Start makes a new run; the old one stays as it was.")}<div id="cv-run-form">{form}</div>""", width="95%", max_width="60rem"), "cv-modal")

async def _h_run_again(request, payload, imr):
    """A new run of the same pipeline (as the library holds it now) with the same inputs, profiles and pins: a sync done again, a question asked again."""
    old = _run(request, payload["id"])
    pl = AV.lib.get("pipeline", old.plan["id"]) if old.plan.get("id") and AV.lib.has("pipeline", old.plan["id"]) else old.plan
    if _free_code(pl) and "python" not in _may(request): return imr.oob(_note("Not started: it runs Python code of its starter's choosing, and you are not among those who may (Settings, Limits).", True), "cv-msg")
    try: rid = await AV.start(pl, {k: old.data[k] for k in (pl.get("params") or {}) if k in old.data}, owner=_user(request), profiles=old.meta.get("profiles", []), pins=old.meta.get("pins", {}), may=_may(request), case=old.meta.get("case"))
    except ValueError as e: return imr.oob(_note(f"Not started: {e}", True), "cv-msg")
    return await _refresh(request, imr, payload["face"], _note(f"Started again as {rid}."))

async def _h_run_go(request, payload, imr):
    await AV.go(_run(request, payload["id"]).id)
    return await _refresh(request, imr, payload["face"])

async def _h_run_stop(request, payload, imr):
    AV.director.stop(_run(request, payload["id"]).id, now=bool(payload.get("now")))
    return await _refresh(request, imr, payload["face"], _note("Stopping now: what was running is cut off, what was kept stays, and Go on picks it up from there." if payload.get("now") else "Stopping: nothing further starts; what is working finishes and is kept."))

async def _h_run_remove(request, payload, imr):
    for rid in (payload.get("ids") or payload["id"]).split(","):
        try: AV.director.remove(_run(request, rid).id)
        except (ValueError, KeyError) as e: return imr.oob(_note(str(e), True), "cv-msg")
    return await _refresh(request, imr, payload["face"])

def _step_states(r) -> dict:
    """{step id: "done" | "running" | "unreached" | "next" | "waiting"}: where each step of a run stands. A finished run read back from disk has only what its plan kept: its other steps were done all the same."""
    v, have = r.view(), set(r.data)
    nxt = set(v["course"][0]) if v["course"] else set()
    return {s["id"]: "done" if "@" + s["id"] in have or (r.meta["state"] == "done" and s["id"] not in v["unreached"]) else "running" if s["id"] in v["busy"] else "unreached" if s["id"] in v["unreached"] else "next" if s["id"] in nxt else "waiting" for s in r.plan["steps"]}

def _run_view(r, request=None) -> str:
    """One run, whatever its pipeline: who fills its roles, its picture, each step and where it stands, what exists of its results, the last of its journal."""
    states = _step_states(r)
    kept = {unquote(f.stem) for f in (r.dir / "kept").glob("*.json")}
    where = lambda s: states[s["id"]]
    bound = "".join(f"""<div class="cv-dim"><b>{_esc(role)}</b>: <span class="mono">{_esc(b.get("asset"))}</span> on {_esc(b.get("provider"))}. {_esc(b.get("will", ""))}</div>""" for role, b in (r.meta.get("bound") or {}).items() if b)
    steps = "".join(f"""<tr><td class="mono">{_esc(s["id"])}</td><td>{_esc(s["type"])}</td><td class="{_STATE.get(where(s), "")}">{where(s)}</td><td>{"kept" if "@" + s["id"] in kept else ""}</td></tr>""" for s in r.plan["steps"])
    start = set(r.plan.get("params") or {}) | set(r.plan.get("data") or {})
    keys = "".join(f"""<tr><td class="mono">{_esc(k)}</td><td>{_esc(_shown(val)[:400])}</td></tr>""" for k, val in r.data.items() if not k.startswith("@") and k not in start)
    again = _btn("It may run again", "run_decide", id=r.id, step=r.meta.get("held_at", "")) if r.meta["state"] == "held" else ""
    subs = "".join(f"""<div class="row cv-dim"><span class="mono grow">{_esc(c.id.split("~", 1)[1])}</span><span class="chip {_STATE.get(c.meta["state"], "")}">{_esc(c.meta["state"])}</span>{_btn("Open", "run_view", "ui-btn cv-small", id=c.id)}</div>""" for c in sorted(AV.director.runs.values(), key=lambda c: c.meta["created"]) if c.meta.get("parent") == r.id)
    up = _btn("Up", "run_view", id=r.meta["parent"]) if r.meta.get("parent") else ""
    return f"""<div class="cv-sec"><div class="row"><b class="grow">{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(r.meta["state"], "")}">{_esc(r.meta["state"])}</span></div><div class="row">{again}{up}{_btn("Refresh", "run_view", id=r.id)}{_btn("Close", "run_view", id=r.id, close="1")}</div>{_dim(_esc(r.id) + " | " + _esc(r.meta.get("owner", "")))}{_note(r.meta["error"], True) if r.meta.get("error") else ""}<b>Roles</b>{bound or _dim("none placed yet")}{BESIDE["flow_view"].run_picture(request, r) if request else ""}<b>Steps</b><table class="cv-tbl"><tr><th>step</th><th>type</th><th>state</th><th></th></tr>{steps}</table>{"<b>Runs its steps made</b>" if subs else ""}{subs}<b>What exists of its results</b><table class="cv-tbl">{keys}</table><b>Journal</b><div class="quote-block mono cv-log">{_esc(chr(10).join((r.dir / "journal.jsonl").read_text().splitlines()[-12:]))}</div></div>"""

async def _h_run_view(request, payload, imr): return imr.oob("" if payload.get("close") else _run_view(_run(request, payload["id"]), request), "cv-run-view")

async def _h_run_decide(request, payload, imr):
    r = _run(request, payload["id"])
    AV.director.decide(r.id, payload["step"], again=True)
    await AV.go(r.id)
    return imr.oob(_run_view(r, request), "cv-run-view")

# --- Panel: review (what work proposed to change in a space; nothing there changes until it is accepted) ---

async def p_review(c) -> str:
    out = ""
    for sp in AV.lib.list("space"):
        if c.spec.get("spaces") and sp["id"] not in c.spec["spaces"]: continue
        if not Path(sp["root"]).is_dir():
            out += _dim(f"""{_esc(sp.get("name") or sp["id"])}: its folder {_esc(sp["root"])} does not exist on this portal""")
            continue
        out += f"""<div class="cv-dim"><b>{_esc(sp.get("name") or sp["id"])}</b> <span class="mono">{_esc(sp["root"])}</span></div>{BI.shadow_review_html(AV.space(sp["id"])[1], "corvid_review", {"space": sp["id"], "face": c.face["id"], "branch": IM.branch_id, "lvl": 1})}"""
    return out or _dim("no spaces in the library")

async def _h_review(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin accepts or rejects changes for now.", True), "cv-msg")
    shadow = AV.space(payload["space"])[1]
    if payload["action"] == "diff": return imr.oob(_esc(shadow.diff(payload["path"])), payload["diff_target"])
    shadow.accept(payload["path"], force=bool(payload.get("force"))) if payload["action"] == "accept" else shadow.reject(payload["path"])
    return await _refresh(request, imr, payload["face"], _note(f"""{payload["path"]}: {payload["action"]}ed."""))

# --- Panels: conversation, conversations, roles (the portal's chat interface over runs) ---
# A conversation is a file: <data>/conversations/<user>/<id>.json {"id", "face", "title", "messages", "pins": {role: binding}, "pending": run id}. Each turn starts a run of the pipeline the face's conversation panel names; what the run's steps report while they work is shown as it comes.

def _talk_dir(user: str) -> Path: return DATA / "conversations" / user
def _talk(user: str, cid: str) -> dict: return json.loads((_talk_dir(user) / f"{cid}.json").read_text())
def _talk_save(user: str, t: dict): BI.write_json_atomic(_talk_dir(user) / f"""{t["id"]}.json""", t)
def _talks(user: str, face_id: str) -> list: return sorted((t for t in (json.loads(f.read_text()) for f in _talk_dir(user).glob("*.json")) if t["face"] == face_id), key=lambda t: t["changed"], reverse=True)
def _talk_new(user: str, face_id: str) -> dict:
    t = {"id": uuid.uuid4().hex[:10], "face": face_id, "title": "New conversation", "messages": [], "pins": {}, "pending": "", "changed": time.time()}
    _talk_dir(user).mkdir(parents=True, exist_ok=True)
    _talk_save(user, t)
    return t

def _current(request, face: dict, tab: dict) -> dict:
    """The conversation this face's tab shows: the one it names, else the latest, else a new one."""
    user, all_ = _user(request), _talks(_user(request), face["id"])
    return next((t for t in all_ if t["id"] == tab.get("cid")), None) or (all_[0] if all_ else _talk_new(user, face["id"]))

def _working(t: dict) -> bool: return bool(t["pending"]) and t["pending"] in AV.director.runs and AV.director.runs[t["pending"]].meta["state"] in LIVE
def _stop_vals(cid: str) -> dict: return {"type": "corvid_stop", "cid": cid, "lvl": 1, "branch": IM.branch_id}

async def p_conversation(c) -> str:
    t = _current(c.request, c.face, c.tab)
    head = f"""<b>{_esc(t["title"])}</b> {BESIDE["status_view"].prepare(c.face["id"], t["id"])}"""
    return f"""<div class="cv-chat">{_cm(c.face["id"]).shell(t["id"], t["messages"], user=c.request.state.user, header_html=head, is_working=_working(t), stop_intent=_stop_vals(t["id"]), extra_footer=MEDIA.attach_html(t["id"]) if _conv_spec(c.face).get("attach", True) else "")}</div>"""   # "attach": false in the conversation panel's spec leaves the attach button out

async def p_conversations(c) -> str:
    cur = _current(c.request, c.face, c.tab)["id"]
    rows = "".join(f"""<div class="list-row row{" cv-on" if t["id"] == cur else ""}"><span class="grow cv-link" {_act("open_tab", id=c.face["id"], cid=t["id"])}><span id="cv-talk-title-{t["id"]}">{_esc(t["title"])}</span>{_dim(_when(t["changed"]))}</span>{_btn("&#x2715;", "talk_del", "ui-btn cv-small", face=c.face["id"], cid=t["id"], confirm="Delete this conversation? Its runs stay.")}</div>""" for t in _talks(_user(c.request), c.face["id"]))
    return f"""<div class="row">{_btn("New conversation", "talk_new", face=c.face["id"])}</div>{rows}"""

async def p_roles(c) -> str:
    """Who fills the roles of this face's conversation pipeline in the conversation shown: what the profile's candidates give, unless one is pinned here."""
    conv, t = _conv_spec(c.face), _current(c.request, c.face, c.tab)
    pl, offers = AV.lib.get("pipeline", _pipe(conv, t)) if AV.lib.has("pipeline", _pipe(conv, t)) else None, _mine(c.request, await _offers())
    if not pl: return _no_pipelines()
    NV = BESIDE["needs_view"]
    got = {r: await NV.now(pl["id"], r, need, _user(c.request), c.face.get("profiles", [])) for r, need in (pl.get("roles") or {}).items()}
    def usual(r):
        g = got[r]
        return "placed when it starts (being placed now ...)" if g.get("pending") else "placed when it starts: nothing can do it now" if g.get("error") else f"""placed when it starts (now: {g["asset"]} on {(AV.lib.get("provider", g["provider"]) if AV.lib.has("provider", g["provider"]) else {}).get("name") or g["provider"]})"""
    fields = _role_fields(pl.get("roles") or {}, offers, "")
    for f in fields: f.options, f.hx_intent, f.hx_target = [("", usual(f.name)), *f.options[1:]] if f.type == "select" else f.options, "corvid_pin", "none"
    return f"""{_unreached(offers)}<form onsubmit="return false"><input type="hidden" name="cid" value="{_esc(t["id"])}"><input type="hidden" name="pipeline" value="{_esc(pl["id"])}">{_group(fields).render(_role_values(_pins(conv, t)), name_prefix="r_")}</form>{_dim("A choice here is a pin: it holds for this conversation and nothing switches it.")}"""

async def p_params(c) -> str:
    """The inputs of the face's conversation pipeline as they hold for the conversation shown: its own value where one was set here, else the face's, else the pipeline's default. How much is shown is the conversation panel's "show" (see _levels)."""
    conv, t = _conv_spec(c.face), _current(c.request, c.face, c.tab)
    if not AV.lib.has("pipeline", _pipe(conv, t)): return _no_pipelines()
    pl, pick = AV.lib.get("pipeline", _pipe(conv, t)), _pipe_pick(c.face, conv, t)
    own, params = t.get("inputs", {}), {k: v for k, v in (pl.get("params") or {}).items() if k != "messages" and not v.get("internal")}
    assets = _role_assets(pl, _mine(c.request, await _offers()), c.face.get("profiles", []), _pins(conv, t))
    levels = _levels(conv.get("show", {}), params)
    if all(v == "fixed" for v in levels.values()): return pick + _dim("This face keeps its own values for everything.")
    pick += f"""<form class="row" id="cv-mode-f" onsubmit="return false"><input name="mode_name" class="module-select grow" placeholder="name for a new mode" title="A mode keeps what answers here, the values below and who fills the roles, under a name. Every face that offers modes can then use it.">{_btn("Save as a mode", "mode_save", face=c.face["id"], cid=t["id"], include="#cv-mode-f", title="As this conversation is set now")}</form>""" if _admin(c.request) and conv.get("modes") == "*" else ""
    here = "Set in this conversation: " + ", ".join(params[k].get("label") or k for k in own if k in params) if own else "Nothing is set in this conversation: these are the face's values."
    back = _btn("Back to the face's", "param_save", face=c.face["id"], cid=t["id"], clear="1") if own else ""
    to_face = _btn("Make these the face's", "param_save", face=c.face["id"], cid=t["id"], to_face="1", include="#cv-param-f", confirm="Use these values for every conversation of this face that sets none of its own?") if _admin(c.request) else ""
    values = {k: own.get(k, _base(conv, t).get(k, v.get("default"))) for k, v in params.items()}
    return f"""{pick}<form id="cv-param-f" onsubmit="return false">{_exposed(_param_fields({"params": params}, assets), levels, _spread(values, params), "p_", "cv-param-f")}</form>{_dim(_esc(here))}<div class="row">{_btn("Use in this conversation", "param_save", face=c.face["id"], cid=t["id"], include="#cv-param-f")}{back}{to_face}</div>"""

async def _h_param_save(request, payload, imr):
    user, face = _user(request), AV.lib.get("face", payload["face"])
    t, conv = _talk(user, payload["cid"]), _conv_spec(face)
    pl = AV.lib.get("pipeline", _pipe(conv, t))
    params, assets = {k: v for k, v in (pl.get("params") or {}).items() if k != "messages" and not v.get("internal")}, _role_assets(pl, _mine(request, await _offers()), face.get("profiles", []), _pins(conv, t))
    vals = _gathered({k: v for k, v in _group(_param_fields({"params": params}, assets)).parse(payload, "p_").items() if k in _held(payload, "p_")}, params, assets)   # only what the form held: a fixed or hidden input keeps the face's value
    if payload.get("to_face"):
        if not _admin(request): return imr.oob(_note("Only a portal admin changes a face.", True), "cv-msg")
        conv["inputs"] = {**conv.get("inputs", {}), **vals}   # conv is the panel's own entry inside face, so the face now carries the values
        AV.lib.save("face", {k: v for k, v in face.items() if k not in ("modified", "by")}, by=user)
    _talk_save(user, {**t, "inputs": {} if payload.get("clear") or payload.get("to_face") else {k: v for k, v in vals.items() if v != _base(conv, t).get(k, params[k].get("default"))}})
    state = _tabs(await TM._load(request))
    return imr.oob(await _region(request, state, "right"), "cv-right")

def _pipe_pick(face: dict, conv: dict, t: dict) -> str:
    """For the conversation shown: its mode among those the face offers (a saved way of answering: what answers, with which values and roles), and the choice among the pipelines the face allows. Nothing where the face offers neither."""
    ids, modes = [conv["pipeline"]] + [i for i in conv.get("pipelines", []) if i != conv["pipeline"] and AV.lib.has("pipeline", i)], _modes(conv, face["id"])
    fm = [BI.SettingField("mode", "Mode", "select", options=[("", "(none: as set below)")] + [(m["id"], m.get("name") or m["id"]) for m in modes], hint=_mode(conv, t).get("about") or "A saved way of answering: what answers, its values and who fills its roles. What is set in this conversation stands above it.", hx_intent="corvid_talk_mode", hx_target="none")] if modes else []
    fp = [BI.SettingField("pipeline", "What answers", "select", options=[(i, AV.lib.get("pipeline", i).get("name") or i) for i in ids], hint="For this conversation; its roles and options follow it.", hx_intent="corvid_talk_pipe", hx_target="none")] if len(ids) > 1 and not _mode(conv, t) else []
    return f"""<form onsubmit="return false"><input type="hidden" name="cid" value="{_esc(t["id"])}"><input type="hidden" name="face" value="{_esc(face["id"])}">{_group([*fm, *fp]).render({"pipeline": _pipe(conv, t), "mode": _mode(conv, t).get("id", "")})}</form>""" if fm or fp else ""

async def _h_talk_mode(request, payload, imr):
    """The conversation put into a mode the face offers (or out of one): it starts from the mode, so what was set here before is dropped."""
    user = _user(request)
    t, conv = _talk(user, payload["cid"]), _conv_spec(AV.lib.get("face", payload["face"]))
    if not payload.get("mode") or payload["mode"] in [m["id"] for m in _modes(conv, payload["face"])]: _talk_save(user, {**t, "mode": payload.get("mode", ""), "pipeline": "", "inputs": {}, "pins": {}})
    return imr.oob(await _region(request, _tabs(await TM._load(request)), "right"), "cv-right")

async def _h_mode_save(request, payload, imr):
    """The conversation as it is set now, kept as a mode: its pipeline, the values that differ from the pipeline's own, and who fills its roles."""
    if not _admin(request): return imr.raw(_chat_note(payload["cid"], "Only a portal admin saves a mode: it is offered to everyone a face shows it to."))
    user, face = _user(request), AV.lib.get("face", payload["face"])
    t, conv, name = _talk(user, payload["cid"]), _conv_spec(face), payload.get("mode_name", "").strip()
    if not _slug(name): return imr.raw(_chat_note(t["id"], "Give the mode a name first."))
    AV.lib.save("mode", {"id": _slug(name), "name": name, "pipeline": _pipe(conv, t), "inputs": {**(_mode(conv, t).get("inputs") or {}), **t.get("inputs", {})}, "pins": _pins(conv, t), "faces": []}, by=user)   # the face's own values (its standing instructions) are not part of a mode: each face that offers it keeps its own
    _talk_save(user, {**t, "mode": _slug(name), "pipeline": "", "inputs": {}, "pins": {}})
    return imr.oob(await _region(request, _tabs(await TM._load(request)), "right"), "cv-right").raw(_chat_note(t["id"], _esc(f"Saved the mode {name}. It is offered here already. To offer it in a curated face such as Athena, tick that face in the mode itself: Settings, Library, Modes.")))

async def _h_talk_pipe(request, payload, imr):
    user = _user(request)
    t, conv = _talk(user, payload["cid"]), _conv_spec(AV.lib.get("face", payload["face"]))
    if payload.get("pipeline") in [conv["pipeline"], *conv.get("pipelines", [])]: _talk_save(user, {**t, "pipeline": payload["pipeline"], "inputs": {}, "pins": {}})   # inputs and pins belong to a pipeline: a new one starts from the face's
    return imr.oob(await _region(request, _tabs(await TM._load(request)), "right"), "cv-right")

async def _h_pin(request, payload, imr):
    t = _talk(_user(request), payload["cid"])
    pl = AV.lib.get("pipeline", payload["pipeline"])
    t["pins"] = _picked(payload, pl.get("roles") or {}, "r_")
    _talk_save(_user(request), t)
    return imr.oob(await _region(request, _tabs(await TM._load(request)), "right"), "cv-right") if any(p.get("type") == "options" for p in (pl.get("params") or {}).values()) else imr   # the inputs shown follow who fills the role, where a pipeline takes an asset's own options

async def _show(request, imr, face_id: str, cid: str): return await IM.scripts["corvid_open_tab"][0](request, {"id": face_id, "cid": cid}, imr)   # the face's tab, showing that conversation
async def _h_talk_new(request, payload, imr): return await _show(request, imr, payload["face"], _talk_new(_user(request), payload["face"])["id"])

async def _h_talk_del(request, payload, imr):
    (_talk_dir(_user(request)) / f"""{payload["cid"]}.json""").unlink()
    return await _show(request, imr, payload["face"], "")

def _msg(role: str, text: str, **more) -> dict: return {"id": uuid.uuid4().hex[:8], "role": role, "content": text, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **more}
def _msgs_html(t: dict, user: str) -> str: return _cm(t["face"]).render_messages(t["messages"], viewer_name=user)
def _find(user: str, mid: str) -> tuple:
    """The conversation of this person that holds the message, and the message's place in it."""
    for t in (json.loads(f.read_text()) for f in _talk_dir(user).glob("*.json")):
        for i, m in enumerate(t["messages"]):
            if m["id"] == mid: return t, i
    raise KeyError(mid)

async def _h_say(request, payload, imr):
    """The chat form's send: the message joins the talk, the form answers at once (working indicator, emptied input) and the turn goes on by itself."""
    user, cid, content = _user(request), payload.get("cid", ""), (payload.get("content") or "").strip()
    t, files = _talk(user, cid), MEDIA.message_files(user, payload.get("cid", ""), payload.get("att"))
    if not (content or files) or _working(t): return imr
    imr.raw(_take(user, t, _msg("user", content, user_name=user, **({"files": files} if files else {}))))
    imr.oob("", f"cm-att-{cid}")   # the picked files went with the message
    cm = _cm(t["face"])
    imr.raw(f"""<textarea id="cm-in-{cid}" name="content" class="cm-input" placeholder="{_esc(cm.placeholder)}" hx-swap-oob="outerHTML"></textarea>""")
    asyncio.create_task(_turn(user, t, payload.get("think") in ("1", "true", True), _may(request)))
    return imr

def _take(user: str, t: dict, mine: dict) -> str:
    """A person's message joins the conversation (the first one names it); answers what shows it: the message, and that an answer is being worked on."""
    cid, cm = t["id"], _cm(t["face"])
    t["messages"].append(mine)
    if len(t["messages"]) == 1: t["title"] = mine["content"][:50]
    _talk_save(user, {**t, "changed": time.time()})
    shown = f"""<span id="cv-talk-title-{cid}" hx-swap-oob="innerHTML">{_esc(t["title"])}</span><div id="cm-msgs-{cid}" hx-swap-oob="innerHTML">{_msgs_html(t, user)}</div>""" if len(t["messages"]) == 1 else cm.append_message_html(cid, mine, viewer_name=user)   # the first message replaces the empty-talk line
    return shown + cm.working_html(cid, _stop_vals(cid))

def _chat_note(cid: str, html_: str) -> str: return f"""<div id="cm-msgs-{cid}" hx-swap-oob="beforeend"><div class="cv-note">{html_}</div></div>"""   # a line shown in a conversation and not kept with it

async def _shown_everywhere(t: dict, user: str):
    """The conversation's messages as they are now, sent to every page of this person that shows it (another tab, the phone), not only the one that asked."""
    await WS.send_personal_message(f"""<div id="cm-msgs-{t["id"]}" hx-swap-oob="innerHTML">{_msgs_html(t, user)}</div>""", user)

async def _again(request, imr, t: dict, i: int):
    """The talk cut back to message i (a person's) and answered again from there. What came after it is taken off every page showing the talk; it is not lost: it is kept in the conversation's file under "earlier"."""
    user, cid = _user(request), t["id"]
    if _working(t): return imr.raw(_chat_note(cid, "It is still answering: stop that first (the stop button), then ask again."))
    if t["messages"][i + 1:]: t.setdefault("earlier", []).append({"cut": time.time(), "messages": t["messages"][i + 1:]})
    t["messages"] = t["messages"][:i + 1]
    _talk_save(user, {**t, "changed": time.time()})
    await _shown_everywhere(t, user)
    imr.oob(_msgs_html(t, user), "cm-msgs-" + cid)
    imr.raw(_cm(t["face"]).working_html(cid, _stop_vals(cid)))
    asyncio.create_task(_turn(user, t, False, _may(request)))
    return imr

async def _h_msg_retry(request, payload, imr):
    t, i = _find(_user(request), payload["id"])
    while i >= 0 and t["messages"][i]["role"] != "user": i -= 1   # asked on an answer: the message it answered
    return await _again(request, imr, t, i) if i >= 0 else imr

async def _h_msg_edit_form(request, payload, imr):
    t, i = _find(_user(request), payload["id"])
    m = t["messages"][i]
    again = _btn("Save and send again", "msg_edit_save", id=m["id"], resend="1", include="#cv-edit-f") if m["role"] == "user" else ""
    return imr.oob(f"""<form class="cv-form cv-edit" id="cv-edit-f" onsubmit="return false"><textarea name="content" class="cm-input" rows="5">{_esc(m["content"])}</textarea><div class="row"><span class="grow"></span>{_btn("Save", "msg_edit_save", id=m["id"], include="#cv-edit-f")}{again}{_btn("Cancel", "msg_edit_save", id=m["id"], cancel="1")}</div></form>""", "cm-msg-" + m["id"])

async def _h_msg_edit_save(request, payload, imr):
    user = _user(request)
    t, i = _find(user, payload["id"])
    if not payload.get("cancel") and (payload.get("content") or "").strip():
        t["messages"][i].update(content=payload["content"].strip(), edited=True)
        _talk_save(user, t)
        if payload.get("resend"): return await _again(request, imr, t, i)
        await _shown_everywhere(t, user)
    return imr.oob(_msgs_html(t, user), "cm-msgs-" + t["id"])

def _turn_inputs(spec: dict, t: dict, user: str, think: bool = False) -> dict:
    """A turn's inputs: the face's and the conversation's values, the talk so far, and its session - a machine that keeps a model's state per piece of work keeps this conversation's apart from the others."""
    params, last = AV.lib.get("pipeline", _pipe(spec, t)).get("params") or {}, t["messages"][-1] if t["messages"] else {}
    unread = [f for f in last.get("files") or [] if f.get("image")] if not last.get("seen") else []   # pictures of the message being answered that nothing has read yet (once read, what was read is kept with the message)
    msgs = [{"role": m["role"], "content": MEDIA.for_model(user, t["id"], m) + ("\n\n[Pictures are attached, but this conversation's pipeline cannot read pictures: choose one that can, such as Chat turn.]" if m is last and unread and "pictures" not in params else "")} for m in t["messages"] if m["role"] in ("user", "assistant")]
    return {**_base(spec, t), **t.get("inputs", {}), "messages": msgs, **({"pictures": MEDIA.pictures(user, t["id"], last)} if unread and "pictures" in params else {}), **({"think": True} if think else {}), **({"session": f"""{user}-{t["id"]}"""} if "session" in params else {})}

async def _turn(user: str, t: dict, think: bool, may: list, spoken: bool = False):
    """One turn, for a talk whose last message is the person's: the face's pipeline runs with the talk so far and the inputs that hold for it (the face's, then the conversation's own), what its steps report is shown as it comes, and its answer (or why there is none) joins the talk with ways to open the run and to have it answered again."""
    face, cid, seen = AV.lib.get("face", t["face"]), t["id"], {"text": "", "thinking": "", "sent": 0.0}
    spec, cm = _conv_spec(face), _cm(t["face"])
    async def push(html_): await WS.send_personal_message(html_, user)
    sp = MEDIA.Speaker(user, t, face, spec, uuid.uuid4().hex[:8], may) if MEDIA.speaks(spec, t, spoken) else None   # the answer is said sentence by sentence while it is written
    def watch(step, ev):
        if ev.get("type") not in ("text", "thinking"): return
        seen[ev["type"]] += ev["text"]
        if sp and ev["type"] == "text": sp.feed(ev["text"])
        if time.time() - seen["sent"] > 0.12: seen["sent"] = time.time(); asyncio.ensure_future(push(cm.stream_content_html(cid, seen["text"], seen["thinking"][-2000:])))
    inputs = _turn_inputs(spec, t, user, think)
    try: rid = await AV.start(_pipe(spec, t), inputs, owner=user, profiles=face.get("profiles", []), pins=_pins(spec, t), watch=watch, may=may, case=face.get("case"))
    except (ValueError, KeyError) as e:
        if sp: sp.cancel()
        t["messages"].append(note := _msg("system", f"No answer: {e}"))
        _talk_save(user, {**t, "changed": time.time()})
        return await push(cm.append_message_html(cid, note, viewer_name=user) + cm.working_hide_html(cid))
    _talk_save(user, {**t, "pending": rid, "changed": time.time()})
    state, r, mid = await AV.director.wait(rid), AV.director.runs[rid], uuid.uuid4().hex[:8]
    acts = [{"icon": "&#x2699;", "title": "The run behind this", "vals": {"type": "corvid_run_view", "id": rid, "lvl": 1, "branch": IM.branch_id}}, {"icon": "&#x21BA;", "title": "Answer again", "vals": {"type": "corvid_msg_retry", "id": mid, "lvl": 1, "branch": IM.branch_id}}, *([{"icon": "&#x1F4C4;", "title": "Save as a Word file", "vals": {"type": "corvid_msg_docx", "id": mid, "lvl": 1, "branch": IM.branch_id}}] if _office() else [])]
    out = _msg("assistant", _shown(r.data.get(spec.get("answer", "text"))), persona_name=face.get("name") or face["id"], thinking=_shown(r.data.get(spec.get("thinking", ""))), model=(next(iter((r.meta.get("bound") or {}).values()), {}) or {}).get("asset", ""), actions=acts) if state == "done" else _msg("system", f"""No answer: the run is {state}. {r.meta.get("error", "")}""", actions=acts[:1])
    t = _talk(user, cid)
    if state == "done" and r.data.get("seen_text") and (asked := next((m for m in reversed(t["messages"]) if m["role"] == "user"), None)):
        asked["seen"] = r.data["seen_text"]   # what the eyes role read stays with the message: later turns and answers again read it, not the pictures
        await push(cm.render_message(asked, is_me=True, can_edit=True, can_delete=True).replace("<div ", """<div hx-swap-oob="outerHTML" """, 1))
    t["messages"].append({**out, "id": mid})
    _talk_save(user, {**t, "pending": "", "changed": time.time()})
    await push(cm.append_message_html(cid, t["messages"][-1], viewer_name=user) + cm.stream_clear_html(cid) + cm.working_hide_html(cid) + (f"""<div id="cv-run-view" hx-swap-oob="innerHTML">{_run_view(r)}</div>""" if state != "done" else ""))
    if sp and state == "done": asyncio.create_task(MEDIA.spoken(user, t, mid, sp, t["messages"][-1]["content"]))   # what is left is said; the joined recording stays on the answer, for its player
    elif sp: sp.cancel()

def _office(): return ENV["tools"].get("office_files") if hasattr(ENV["tools"].get("office_files"), "md_to_docx") else None   # the portal's Office Files tool, when it is installed and writes Word files

async def _h_msg_docx(request, payload, imr):
    """One message written as a Word file by the portal's Office Files tool, into the space the face's conversation panel names ("export": {"space", "into"}; else made media, folder answers). A new file each time, under a name not taken yet: nothing is replaced. Only a space that takes files directly receives it."""
    user = _user(request)
    t, i = _find(user, payload["id"])
    ex = _conv_spec(AV.lib.get("face", t["face"])).get("export") or {}
    space = ex.get("space", "media")
    if not AV.lib.get("space", space).get("direct"): return imr.raw(_chat_note(t["id"], _esc(f"""Not saved: the space {space} takes proposals only, and a made file needs one that takes files directly ("direct": true).""")))
    fm = AV.space(space)[0]
    rel = fm.free_name("/".join(x for x in (ex.get("into", "answers").strip("/"), f"""{_slug(t["title"])[:40] or "answer"}-{time.strftime("%Y-%m-%d")}.docx""") if x))
    fm.resolve(rel).parent.mkdir(parents=True, exist_ok=True)
    _office().md_to_docx(t["messages"][i]["content"], fm.resolve(rel))
    return imr.raw(_chat_note(t["id"], f"""Saved as <a href="{_P}/media/{_esc(space)}/{quote(rel)}" download>{_esc(rel)}</a> in {_esc(AV.lib.get("space", space).get("name") or space)}."""))

async def _h_stop(request, payload, imr):
    t = _talk(_user(request), payload["cid"])
    if _working(t): AV.director.stop(t["pending"], now=True)
    return imr

async def _h_msg_delete(request, payload, imr):
    user = _user(request)
    for t in (json.loads(f.read_text()) for f in _talk_dir(user).glob("*.json")):
        if any(m["id"] == payload["id"] for m in t["messages"]):
            _talk_save(user, t := {**t, "messages": [m for m in t["messages"] if m["id"] != payload["id"]]})
            await _shown_everywhere(t, user)
    return imr.oob("", f"""cm-msg-{payload["id"]}""", swap="delete")

PANELS = {"needs": BESIDE["needs_view"].p_needs, "status": BESIDE["status_view"].p_status, "loading": BESIDE["loading_view"].p_loading, "prompts": BESIDE["prompts_view"].p_prompts, "prompt": BESIDE["prompts_view"].p_prompt, "make": BESIDE["prompts_view"].p_make, "latest": BESIDE["prompts_view"].p_latest, "progress": BESIDE["prompts_view"].p_progress, "providers": SHELF.p_providers, "bindings": SHELF.p_bindings, "guide": SHELF.p_guide, "limits": SHELF.p_limits, "library": SHELF.p_library, "runs": p_runs, "review": p_review, "conversation": p_conversation, "conversations": p_conversations, "roles": p_roles, "params": p_params, "assets": ASSETS.p_assets, "records": ASSETS.p_records, "graph": ASSETS.p_graph, "gallery": MEDIA.p_gallery, "speech": MEDIA.p_speech, "models": BESIDE["resources_view"].p_models, "machines": MACHINES.p_machines, "chart": FIGURES.p_chart, "usage": FIGURES.p_usage, "fits": FIGURES.p_fits, "now": FIGURES.p_now, "resources": BESIDE["resources_view"].p_resources, "flow": BESIDE["flow_view"].p_flow, "report": BESIDE["report_view"].p_report, "watch": BESIDE["watch_view"].p_watch, "member": BESIDE["members_view"].p_member}

# --- The face shell: faces are tabs; the active one's panels fill the workspace and the two side toolbars ---

def _tabs(state: dict) -> dict:
    """The tab state brought in line with the faces that exist now: one tab per face, in the faces' order; what a tab remembers (the conversation it shows) is kept."""
    faces, old = [f for f in _faces() if not f.get("under")], state.get("tabs", {})   # a project has no tab: it is shown inside its host
    state["tabs"] = {f["id"]: {**old.get(f["id"], {}), "id": f["id"], "label": f.get("name") or f["id"], "icon": f.get("icon", ""), "order": n, "path": f["id"]} for n, f in enumerate(faces)}
    if state.get("active") not in state["tabs"]: state["active"] = faces[0]["id"]
    return state

SLOW_S = 0.5   # a panel slower than this is named in the server log
INLINE = {"conversation"}   # panels drawn with the page; every other panel is drawn after it, on its own, so nothing on a page waits for a slow one ("inline": true on a panel's spec draws it with the page too)

def _later(face_id: str, vid: str, region: str, n: int, host: str) -> str:
    """A panel's place, filled as soon as the page is shown: it asks for the panel by itself (GET /panel), so the page and every other panel are there first."""
    return f"""<div hx-get="{_P}/panel?face={quote(face_id)}&amp;view={quote(vid)}&amp;region={region}&amp;n={n}&amp;host={quote(host)}" hx-trigger="load" hx-swap="outerHTML"><span class="cv-dim">&#x23F3; being asked ...</span></div>"""

async def _panel(c) -> str:
    """One panel drawn. A panel that fails says so in its own place, with the error (the traceback goes to the server log), and the rest of the face is drawn: one failing panel does not take the page, and the way to another view, with it."""
    t0 = time.perf_counter()
    try:
        html = await PANELS[c.spec["panel"]](c)
        if (dt := time.perf_counter() - t0) > SLOW_S: print(f"""[corvid] panel {c.spec["panel"]} on {c.face["id"]} took {dt:.1f} s""")   # what makes a page slow, in the server log
        return html
    except Exception as e:
        traceback.print_exc()
        return _note(f"""The panel "{c.spec["panel"]}" failed: {type(e).__name__}: {e}. The server log has the traceback.""", True)

def _folded(host: dict, tab: dict, guest, face: dict, vid: str) -> str:
    """A host face's rows of faces and views, folded: one line naming what is shown, which unfolds them."""
    shown = " - ".join(x for x in ((guest or host).get("name") or (guest or host)["id"], next((v.get("name") or v["id"] for v in _views(face) if v["id"] == vid), "")) if x)
    return f"""<div class="row cv-rows"><span class="chip cv-link" title="Show the rows of faces and views" {_act("open_tab", id=host["id"], rows="shown")}>&#x25BE; {_esc(shown)}</span></div>"""

async def _region(request, state: dict, region: str, msg: str = "") -> str:
    host, tab = AV.lib.get("face", state["active"]), state["tabs"][state["active"]]
    guest, gview = _guest(host, tab)
    face = guest if guest and (region == "main" or guest.get("under")) else host   # a project brings its own toolbars; a face only embedded shows its workspace beside the host's
    lay = _layout(face, {"view": gview} if face is guest else tab)
    vid = lay["id"] if _views(face) else ""
    parts = [(spec, await _panel(SimpleNamespace(request=request, face=face, spec=spec, key=f"{vid}:{region}.{n}", tab=tab, host=host["id"])) if spec["panel"] in INLINE or spec.get("inline") else _later(face["id"], vid, region, n, host["id"])) for n, spec in enumerate(lay.get(region, []))]
    bar = ""
    if region == "main":
        hosted = [(host.get("name") or host["id"], not guest, {"embed": ""})] + [(f.get("name") or f["id"], bool(guest) and guest["id"] == f["id"], {"embed": f["id"] + ":"}) for f in _embeds(host)]
        views = [(v.get("name") or v["id"], v["id"] == vid, {"embed": f"""{guest["id"]}:{v["id"]}"""} if guest else {"view": v["id"]}) for v in _views(face)]
        bar = (_tab_row("cv-host-tabs", host["id"], hosted) if _embeds(host) else "") + (_tab_row("cv-view-tabs", host["id"], views) if views else "")
        if _embeds(host): bar = _folded(host, tab, guest, face, vid) if tab.get("rows") == "folded" else f"""<div class="row cv-rows"><div class="grow">{bar}</div><span class="chip cv-link" title="Fold these rows away; what is shown stays" {_act("open_tab", id=host["id"], rows="folded")}>&#x25B4;</span></div>"""
    if region == "main" and len(parts) == 1 and parts[0][0]["panel"] == "conversation": return bar + parts[0][1]   # a conversation alone fills the workspace
    body = "".join(_sec(spec.get("title", ""), html_) for spec, html_ in parts)
    top = f"""{_dim(_esc(face.get("about", "")))}<div id="cv-msg">{msg}</div><div id="cv-modal"></div>""" if region == "main" else ""   # cv-modal: a window opened over the workspace (UI.modal); redrawing the workspace closes it
    return f"""{bar}<div class="scroll-pane cv">{top}{body}{"<div id='cv-run-view'></div>" if region == "right" else ""}</div>"""

async def _tab_content(request, state: dict):
    state = _tabs(state)
    return state, await _region(request, state, "main")

def _with_sides(base_fn):
    """A tab intent, acting on the faces as they are now, that also redraws the side toolbars for the face then shown."""
    async def _h(request, payload, imr):
        state = _tabs(await TM._load(request))
        await TM._save(request, state)   # the stored tabs are the faces that exist now, before the intent acts on them
        tab = state["tabs"].get(payload.get("id"), {})
        imr = await base_fn(request, {**payload, "label": tab.get("label", "Tab"), "icon": tab.get("icon", "")}, imr)   # opening a tab that exists again keeps its name and icon
        state = _tabs(await TM._load(request))
        for region in ("left", "right"): imr.oob(await _region(request, state, region), REGIONS[region])
        return imr
    return _h

async def _refresh(request, imr, face_id: str, msg: str = "", regions: tuple = ()):
    """The face redrawn, with a message at the top of the workspace: everything, or only the regions named ("left", "right", "main") - a change beside a form (a prompt chosen on the left) leaves what is being filled in on the form as it is."""
    state = _tabs(await TM._load(request))
    if _guest(AV.lib.get("face", state["active"]), state["tabs"][state["active"]])[0] is None or state["tabs"][state["active"]]["embed"].split(":")[0] != face_id: state["active"] = (AV.lib.get("face", face_id).get("under") if AV.lib.has("face", face_id) else None) or face_id   # a face shown inside another stays inside it; a project is redrawn in its host
    for region, el in REGIONS.items():
        if not regions or region in regions: imr.oob(await _region(request, state, region, msg), el)
    if regions and "main" not in regions and msg: imr.oob(msg, "cv-msg")
    return imr

# --- Routes and init ---

@router.get("")
@router.get("/")
async def root(request: Request):
    state = _tabs(await TM._load(request))
    bars = {"top": UI.toolbar(side="top", content=await TM.tab_bar_fn(state, "cv-tab-bar", "corvid", 1, allow_new=False, closable=False), size="2.5rem", id="cv-top", nesting_level=1, start_open=True, resizable=False),
            "left": UI.toolbar(side="left", content=f"""<div id="cv-left">{await _region(request, state, "left")}</div>""", size="min(28rem, 90vw)", id="cv-leftbar", nesting_level=1, phone_closed=True, close_on_select=False, start_open=bool(_layout(AV.lib.get("face", state["active"]), state["tabs"][state["active"]]).get("left")), resizable=True),
            "right": UI.toolbar(side="right", content=f"""<div id="cv-right">{await _region(request, state, "right")}</div>""", size="19rem", id="cv-rightbar", nesting_level=1, phone_closed=True, start_open=True, resizable=True)}
    return ENV["templates"].TemplateResponse(name="base.html", request=request, context={"request": request, "user": request.state.user, "nesting_level": 1, "shell_id": IM.branch_id, "content": f"""<div id="cv-workspace">{await _region(request, state, "main")}</div>""", "extra_css": CSS + CM.CSS, "extra_script": CM.SCRIPT, "toolbars": bars})

@router.post("/upload", response_class=HTMLResponse)
async def upload(request: Request):
    """Files from the person's computer into a folder of a space, through the portal's file manager; answers the run form again with them ticked."""
    form = await request.form()
    field, fm, rel = str(form["field"]), AV.space(str(form["space"]))[0], "/".join(x for x in (str(form.get("parent") or ""), str(form.get("new_folder") or "").strip()) if x)
    folder = fm.safe_rel(rel) if rel else ""   # the picked folder, and a new one inside it if named, made safe the way the file manager makes every upload path safe
    saved = await fm.save_uploads(folder, form.getlist("files"))
    pl = AV.lib.get("pipeline", str(form["pid"]))
    return HTMLResponse(await _run_form_html(request, str(form["face"]), pl["id"], str(form["key"]), {field: saved, pl["params"][field]["space_from"]: str(form["space"])}))

@router.post("/attach", response_class=HTMLResponse)
async def attach(request: Request): return await MEDIA.attach(request)

@router.get("/talkfile/{cid}/{name}")
async def talk_file(request: Request, cid: str, name: str, small: int = 0): return await MEDIA.talk_file(request, cid, name, bool(small))

@router.get("/media/{space}/{path:path}")
async def media_file(request: Request, space: str, path: str): return await MEDIA.media_file(request, space, path)

@router.get("/thumb/{space}/{path:path}")
async def thumb_file(request: Request, space: str, path: str): return await MEDIA.thumb_file(request, space, path)

@router.get("/audio/{name}")
async def audio_file(request: Request, name: str): return await MEDIA.audio_file(request, name)

@router.get("/install", response_class=HTMLResponse)
async def install(pid: str, name: str): return HTMLResponse(MACHINES.install_view(pid, name))

@router.get("/now", response_class=HTMLResponse)
async def now(request: Request, face: str): return HTMLResponse(await FIGURES.now_html(request, face))

@router.get("/panel", response_class=HTMLResponse)
async def panel(request: Request, face: str, view: str, region: str, n: int, host: str):
    """One panel of a face's view, drawn on its own (see _later)."""
    f, state = AV.lib.get("face", face), _tabs(await TM._load(request))
    return HTMLResponse(await _panel(SimpleNamespace(request=request, face=f, spec=_layout(f, {"view": view})[region][n], key=f"{view}:{region}.{n}", tab=state["tabs"].get(host, {}), host=host)))

@router.get("/offer_status", response_class=HTMLResponse)
async def offer_status(request: Request, pid: str): return HTMLResponse(BESIDE["shelf"].offer_status(next(o for o in _offers_now() if o["p"]["id"] == pid)))   # one connection as last heard, asked for by itself while it is asked again

@router.get("/machines_grid", response_class=HTMLResponse)
async def machines_grid(request: Request, face: str):
    looks = [await MACHINES._look(o["p"]) for o in _offers_now() if not o["p"].get("speaks")]
    return HTMLResponse(MACHINES.grid_box(face, looks, MACHINES._source()))

@router.get("/machine_section", response_class=HTMLResponse)
async def machine_section(request: Request, face: str, pid: str, open: str = ""): return HTMLResponse(await MACHINES.section(face, _admin(request), await MACHINES._look(AV.lib.get("provider", pid)), MACHINES._source(), bool(open)))

@router.get("/machine_age", response_class=HTMLResponse)
async def machine_age(request: Request, face: str, pid: str, t: float): return HTMLResponse(MACHINES.age_chip(face, pid, {**(AV.seen.rows.get(f"{pid}:modules") or {"t": 0.0, "error": ""}), "t": t}))

@router.get("/loading", response_class=HTMLResponse)
async def loading_row(request: Request, pid: str): return HTMLResponse(await BESIDE["loading_view"].row(AV.lib.get("provider", pid)))

@router.get("/prompts", response_class=HTMLResponse)
async def prompts_list(request: Request, face: str): return HTMLResponse(await BESIDE["prompts_view"].p_prompts(SimpleNamespace(request=request, face=AV.lib.get("face", face), key="", spec={})))

@router.get("/report", response_class=HTMLResponse)
async def report(request: Request): return HTMLResponse(BESIDE["report_view"].report_html())

@router.get("/code_updates", response_class=HTMLResponse)
async def code_updates(request: Request): return HTMLResponse(MACHINES.updates_html())

@router.get("/res_tests", response_class=HTMLResponse)
async def res_tests(request: Request): return HTMLResponse(BESIDE["resources_view"].tests_html())

@router.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, face: str, key: str): return HTMLResponse(_run_list(request, AV.lib.get("face", face), key))

def init_module(env: dict):
    global UI, BI, WS, IM, TM, CM, AV, PROV, ROLES, SEEN, STEPS, DATA, AVP
    ENV.update(env)
    BI, WS, UI = env["tools"]["built_ins"], env["ws"], env["templates"].env.globals["UI"]
    AV, PROV, ROLES, SEEN, STEPS, DATA = env["tools"]["aviary"].AVIARY, env["tools"]["aviary"].providers, env["tools"]["aviary"].roles, env["tools"]["aviary"].seen, env["tools"]["aviary"].steps, Path(env["data_dir"])
    AVP = env["tools"]["aviary"].P   # the plan rules (which roles a step uses ...)
    AV.lib.shipped.append(Path(__file__).parent / "library")
    IM = env["InterfaceManager"](nesting_level=1, db_path=f"""{env["data_dir"]}/im_registry.db""")
    TM = BI.TabManager(namespace="corvid", tab_bar_id="cv-tab-bar", content_id="cv-workspace", render_content_fn=_tab_content, intent_prefix="corvid", IM=IM, scope="user", allow_new=False, closable=False)
    for intent in ("open", "focus"): IM.scripts[f"corvid_{intent}_tab"] = [_with_sides(getattr(TM, f"_{intent}"))]
    CM_OPTS.update(namespace="corvid", view_style="bubble", stream_toggle=False, think_toggle=True, stop_enabled=True, pin_enabled=True, allow_edit=True, allow_delete=True, allow_copy=True, show_info=True, show_model=True, markdown_mode="standard", action_intent_prefix="corvid", branch_id=IM.branch_id, nesting_level=1, IM=IM, intent_name="corvid_say", on_submit=_h_say, placeholder="Say something… (Ctrl+Enter to send)")
    CM = BI.ChatManager(**CM_OPTS)
    IM.scripts.update({f"corvid_{k}": [fn] for k, fn in {"run_form": _h_run_form, "run_edit": _h_run_edit, "run_draft": _h_run_draft, "run_setup": _h_run_setup, "run_start": _h_run_start, "run_go": _h_run_go, "run_stop": _h_run_stop, "run_view": _h_run_view, "run_decide": _h_run_decide, "review": _h_review, "pin": _h_pin, "talk_new": _h_talk_new, "talk_del": _h_talk_del, "stop": _h_stop, "msg_delete": _h_msg_delete, "msg_retry": _h_msg_retry, "msg_edit_form": _h_msg_edit_form, "msg_edit_save": _h_msg_edit_save, "msg_docx": _h_msg_docx, "param_save": _h_param_save, "talk_pipe": _h_talk_pipe, "talk_mode": _h_talk_mode, "mode_save": _h_mode_save, "run_remove": _h_run_remove, "run_again": _h_run_again}.items()})
    for mod in BESIDE.values(): mod.init(_Live())
    env["register_service"]("corvid", {"run_setup": run_setup})   # other tools start a saved set-up (Git Manager's sync after a pull: the code knowledge group brought up to date)
    print(f"""[corvid] ready | faces: {[f["id"] for f in _faces()]}""")

async def run_setup(setup: str) -> str:
    """Starts a saved set-up (library kind "setup": a pipeline with its inputs and role choices) as its owner, with what the portal allows that owner by default; answers the run id. For hooks and schedules, where no one is asking in a page."""
    s = AV.lib.get("setup", setup)
    pl = AV.lib.get("pipeline", s["pipeline"])
    rid = await AV.start(pl, {**{k: v.get("default") for k, v in (pl.get("params") or {}).items() if "default" in v}, **(s.get("inputs") or {})}, owner=s.get("owner", ""), pins=s.get("pins") or {}, may=[w for w in _LIMITS if AV.allows(w, s.get("owner", ""), False)])
    return f"""started {s.get("name") or setup} (run {rid})"""

CSS = """
.cv{font-size:.8rem;padding:.3rem .5rem}.cv-sec{border:var(--border-thick) solid var(--border);border-radius:var(--radius);padding:.4rem .55rem;margin:.4rem 0;background:var(--surface)}
.cv-dim{font-size:.72rem;color:var(--text_muted)}.cv-key{min-width:7rem}.cv-on{border-color:var(--accent);background:var(--accent_dim)}.cv-small{font-size:.65rem}.cv-link{cursor:pointer}
.cv-ok{color:#00ffa2}.cv-mid{color:#ffcc00}.cv-bad{color:#ff6b6b}.cv-danger{color:#ff6b6b}#cv-workspace{height:100%;min-height:0;display:flex;flex-direction:column}#cv-workspace>.cv{flex:1;min-height:0;overflow-y:auto}.cv-chat{flex:1;min-height:0;height:100%}#cv-workspace>.tabs-container{flex:none}.cv-role{margin:.35rem 0;padding:.25rem 0;border-top:var(--border-thick) solid var(--border)}.cv-edit{width:100%}.cv-machine{border:var(--border-thick) solid var(--border);border-radius:var(--radius);padding:.3rem .5rem;margin:.35rem 0}.cv-machine>summary{cursor:pointer}.cv-gallery{height:72vh}.cv-graph{height:68vh;min-height:20rem;border:var(--border-thick) solid var(--border);border-radius:var(--radius)}
.cv-form{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-log{max-height:14rem;font-size:.7rem}.cv-json{width:100%;min-height:18rem;font-size:.72rem}.cv-doc{max-height:60vh;overflow:auto;font-size:.75rem}.cv-lib-form textarea[name="o_text"]{min-height:20rem}
.cv-note{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-err{border-left:.2em solid #ff6b6b;padding:.3rem .5rem;margin:.3rem 0}
.cv-tbl{border-collapse:collapse;font-size:.72rem;margin:.2rem 0 .5rem}.cv-tbl td,.cv-tbl th{border:var(--border-thick) solid var(--border);padding:.12rem .4rem;text-align:left;vertical-align:top;word-break:normal;overflow-wrap:anywhere}.cv-tbl td:first-child{min-width:7em}
"""
