"""corvid.py - Corvid: the faces of Aviary. A face is a manifest (library kind "face"): a name and the panels it puts in the page's three regions - "main" (the workspace), "left" and "right" (the side toolbars). This file draws any face from the panels below and holds no face of its own: a new face, or a changed one, is data.
Built from the portal's own parts: faces are tabs (TabManager) in the top toolbar, a conversation is the portal's chat interface (ChatManager), every form is settings fields (SettingField / SettingsGroup). What is specific to Corvid is only how those are fed from the engine.
The panels know Aviary (tools/aviary) and nothing under it: no machine, model or program is named here. What a panel shows comes from the library, the providers' own answers and the runs.
A face may have "views" (each with its own three regions) when one screen is not enough for a focused tool. A face that lists others under "embeds" can show any of their views in its own workspace, beside its own toolbars (Tessa shows the focused tools this way).
How much a face shows of a pipeline's inputs is data: "show": {input: "shown" | "advanced" | "fixed", "*": the rest, "roles": the role choices}, on a conversation panel or a runs panel ("show_for": {pipeline: {...}} for one pipeline); "inputs" gives the values that hold where nothing is shown.
Panels: params (the inputs of the conversation's pipeline at their levels: pipeline default, the face's, this conversation's), assets / records (what a provider lets a manager make there, and what such a thing holds), conversation / conversations / roles (a talk whose every turn is a run of the pipeline the face names, with the inputs the face gives it; the talks kept; who fills that pipeline's roles in this talk), runs (start a pipeline, follow and steer its runs), review (what work proposed to change in a space, to accept or reject), providers / bindings / limits / guide / library (where work is done, who fills which role by default, what the owner allows runs beyond the default, what is still missing, the stored objects as they are)."""
import re, json, html, time, uuid, asyncio, importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, quote
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

MODULE_META = {"label": "Corvid", "icon": "&#x1F426;", "description": "Faces of Aviary: converse, hand off work, see and steer what runs", "persistence": "user"}
router = APIRouter(redirect_slashes=False)
ENV, UI, BI, WS, IM, TM, CM, AV, PROV, ROLES, DATA, _P = {}, None, None, None, None, None, None, None, None, None, None, "/module/corvid"
LIVE, _STATE = ("running", "stopping"), {"done": "cv-ok", "running": "cv-mid", "stopping": "cv-mid", "interrupted": "cv-mid", "next": "cv-mid", "held": "cv-bad", "failed": "cv-bad", "unplaced": "cv-bad"}
REGIONS = {"main": "cv-workspace", "left": "cv-left", "right": "cv-right"}
CM_OPTS, CMS = {}, {}
class _Live:
    """A live view of this module's globals for media.py beside it: what it reads is what is here now."""
    def __getattr__(self, k): return globals()[k]
_spec_media = importlib.util.spec_from_file_location("modules.corvid_media", Path(__file__).parent / "media.py")   # a helper file beside this one, loaded by path the way the portal loads this module
MEDIA = importlib.util.module_from_spec(_spec_media)
_spec_media.loader.exec_module(MEDIA)   # the chat interface's settings in Corvid, and one chat interface per face setting that differs from them

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
def _slug(s: str) -> str: return re.sub(r"[^\w.-]", "", re.sub(r"[\s-]+", "-", s.strip().lower()))
def _when(t) -> str: return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""
def _user(request) -> str: return request.state.user.username
def _admin(request) -> bool: return getattr(request.state.user, "role", "") == "admin"
def _sec(title: str, body: str) -> str: return f"""<div class="cv-sec"><b>{_esc(title)}</b>{body}</div>"""
def _tab_row(bar_id: str, host_id: str, items: list) -> str:
    """A row of the portal's own tabs (UI.tab_bar / UI.tab) that switch something shown inside a face: items [(label, active, values for the face's open intent)]."""
    return UI.tab_bar("".join(UI.tab(_esc(label), active=on, focus_attrs=_act("open_tab", id=host_id, **kw)) for label, on, kw in items), id=bar_id, nesting_level=2)

def _faces() -> list: return sorted(AV.lib.list("face"), key=lambda f: f.get("order", 50))
def _layout(face: dict, tab: dict) -> dict:
    """The panels of the face's three regions as they are now: the face's own, or those of the view its tab shows when the face has views (a focused tool with more than one screen)."""
    return next((v for v in face["views"] if v["id"] == tab.get("view")), face["views"][0]) if face.get("views") else face
def _spec(face: dict, key: str) -> dict: return _layout(face, {"view": key.split(":")[0]})[key.split(":")[1].split(".")[0]][int(key.split(".")[1])]   # key: "<view id>:<region>.<n>"
def _conv_spec(face: dict) -> dict: return next(sp for lay in (face.get("views") or [face]) for sp in lay.get("main", []) if sp["panel"] == "conversation")
def _pipe(spec: dict, t: dict) -> str: return t.get("pipeline") if t.get("pipeline") in spec.get("pipelines", []) else spec["pipeline"]   # the conversation's own choice among those the face allows, else the face's
def _cm(face_id: str):
    """The portal's chat interface as the face sets it: the face's "chat" {ChatManager option: value} over Corvid's defaults; one per distinct setting."""
    o, key = (AV.lib.get("face", face_id).get("chat") or {}) if AV.lib.has("face", face_id) else {}, ""
    if not o: return CM
    if (key := json.dumps(o, sort_keys=True)) not in CMS: CMS[key] = BI.ChatManager(**{**CM_OPTS, **o})
    return CMS[key]
def _guest(host: dict, tab: dict) -> tuple:
    """(guest face, its view id) when the host shows another face's view in its workspace, else (None, "")."""
    fid, _, vid = (tab.get("embed") or "").partition(":")
    return (AV.lib.get("face", fid), vid) if fid in host.get("embeds", []) and AV.lib.has("face", fid) else (None, "")

def _cands(role: str, profiles: list) -> list: return ROLES.candidates(AV.lib, role, [x for x in profiles if AV.lib.has("bindings", x)])

def _group(fields: list): return BI.SettingsGroup("form", "", fields, "")   # settings fields used as a form: rendered and parsed here, stored by the caller

# --- What providers offer (asked for at most every few seconds, all at once) ---

_OFFERS = {"t": 0.0, "rows": []}

async def _offers() -> list:
    """[{"p": provider, "assets": [its assets], "error": why it did not answer}] for every provider in the library."""
    async def one(p):
        try: return {"p": p, "assets": await PROV.assets(p, timeout=4.0), "error": ""}
        except PROV.ProviderError as e: return {"p": p, "assets": [], "error": str(e)}
    if time.time() - _OFFERS["t"] > 5: _OFFERS.update(t=time.time(), rows=list(await asyncio.gather(*(one(p) for p in AV.lib.list("provider")))))
    return _OFFERS["rows"]

def _choices(offers: list, need: dict, empty: str) -> list:
    """Select options for one role: every asset a provider offers for all the role needs, as "<provider id>|<asset>"."""
    fits = lambda a: all(c in a.get("capabilities", []) for c in need.get("needs") or [])
    return [("", empty)] + [(o["p"]["id"] + "|" + a["name"], a["name"] + "  -  " + (o["p"].get("name") or o["p"]["id"])) for o in offers for a in o["assets"] if fits(a)]

def _role_fields(roles: dict, offers: list, empty: str) -> list: return [BI.SettingField(r, r, "select", options=_choices(offers, need, empty), hint=" | ".join(x for x in (need.get("about", ""), "needs: " + ", ".join(need.get("needs") or [])) if x)) for r, need in roles.items()]
def _role_values(bound: dict) -> dict: return {r: (b.get("provider", "") + "|" + b["asset"]) if b.get("asset") else "" for r, b in bound.items()}
def _picked(form: dict, roles: dict, prefix: str = "") -> dict: return {r: dict(zip(("provider", "asset"), form[prefix + r].split("|", 1))) for r in roles if form.get(prefix + r)}
def _unreached(offers: list) -> str: return "".join(_note(o["error"], True) for o in offers if o["error"])
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

# --- Panels: providers, bindings, guide, library ---

def _provider_form(face_id: str, p: dict = None) -> str:
    key_hint = "A Magpie node: its own key, the admin key it showed when it was installed or another key made on that node. Another server: its API key, if it asks for one." + (" Leave empty to keep the stored one." if p else "")
    speaks = BI.SettingField("speaks", "What it speaks", "select", options=[("", "the node contract (a Magpie node)")] + [(t["id"], (t.get("name") or t["id"]) + " - through a translator") for t in AV.lib.list("translator")], hint="A server that is not a Magpie node (an Ollama server on a work machine, ...) is used through a translator: chat and embeddings as that server offers them, nothing of its memory or programs.")
    g = _group([BI.SettingField("name", "Name", "text", hint="What you call this machine."), BI.SettingField("url", "Address", "text", hint="host:port, for example 192.168.1.20:8790 (a Magpie node) or 192.168.1.30:11434 (an Ollama server)"), speaks, BI.SettingField("key", "API key", "password", hint=key_hint)])
    return f"""<form class="cv-form" id="cv-prov-f" onsubmit="return false"><b>{"Change " + _esc(p.get("name") or p["id"]) if p else "Add a provider"}</b>{g.render({"name": (p or {}).get("name", ""), "url": (p or {}).get("url", ""), "speaks": (p or {}).get("speaks", ""), "key": ""})}<div class="row"><span class="grow"></span>{_btn("Save", "provider_save", face=face_id, id=(p or {}).get("id", ""), include="#cv-prov-f")}{_btn("Cancel", "provider_form", face=face_id, close="1")}</div></form>"""

async def p_providers(c) -> str:
    def row(o):
        p, caps = o["p"], sorted({x for a in o["assets"] for x in a.get("capabilities", [])})
        status = """<span class="cv-bad">not reachable</span>""" if o["error"] else f"""<span class="cv-ok">answers</span> <span class="cv-dim">{len(o["assets"])} assets | {_esc(", ".join(caps))}</span>"""
        return f"""<div class="list-row"><div class="row"><b>{_esc(p.get("name") or p["id"])}</b><span class="cv-dim mono">{_esc(p["url"])}</span>{f'<span class="chip">speaks {_esc(p["speaks"])}</span>' if p.get("speaks") else ""}<span class="grow">{status}</span>{_btn("What it offers", "provider_check", id=p["id"])}{_btn("Change", "provider_form", face=c.face["id"], id=p["id"])}{_btn("Remove", "provider_del", "ui-btn cv-danger", face=c.face["id"], id=p["id"], confirm="Remove this provider? It is kept as an earlier version.")}</div>{_note(o["error"], True) if o["error"] else ""}<div id="cv-prov-{_esc(p["id"])}"></div></div>"""
    rows = "".join(row(o) for o in await _offers())
    return f"""{_dim("A provider is a machine that does work (a node). Corvid keeps only where it is and the key to it; what it can do, it answers itself.")}{rows or _dim("none yet")}<div class="row"><span class="grow"></span>{_btn("Add a provider", "provider_form", face=c.face["id"])}</div><div id="cv-prov-form"></div>"""

async def _h_provider_form(request, payload, imr): return imr.oob("" if payload.get("close") else _provider_form(payload["face"], AV.lib.get("provider", payload["id"]) if payload.get("id") else None), "cv-prov-form")

async def _h_provider_check(request, payload, imr):
    p = AV.lib.get("provider", payload["id"])
    try: d, assets = await PROV.ask(p, "describe", timeout=6.0), await PROV.assets(p, timeout=6.0)
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), f"""cv-prov-{payload["id"]}""")
    rows = "".join(f"""<div class="row cv-dim"><span class="cv-key">{_esc(cap)}</span><span class="mono">{_esc(", ".join(a["name"] for a in assets if cap in a.get("capabilities", [])))}</span></div>""" for cap in sorted({x for a in assets for x in a.get("capabilities", [])}))
    said = " | ".join(k + ": " + _shown(v)[:60] for k, v in d.items() if isinstance(v, (str, int, float)))
    waiting = ""
    if not p.get("speaks"):   # what its active programs can do but have nothing to do it with yet: a capability shows above only once something serves it
        mods, kinds = (await PROV.machine(p, "GET", "/modules"))["modules"], (await PROV.manage(p, "GET"))["kinds"]
        idle = sorted({c for m in mods if m["state"] == "active" for c in m.get("provides", [])} - {x for a in assets for x in a.get("capabilities", [])})
        where = lambda kind: ", ".join(f"""{f.get("name") or f["id"]}, {v.get("name") or v["id"]}""" for f in _faces() for v in (f.get("views") or [f]) for sp in v.get("main", []) if sp["panel"] == "assets" and sp.get("kind") == kind)   # the faces whose manifests manage that kind
        make = "; ".join(k.get("label", n) + (" - made in " + where(n) if where(n) else "") for n, k in kinds.items())
        waiting = _dim(_esc(f"Active, with nothing to serve yet: {', '.join(idle)}." + (f" Things that can be made there: {make}." if make else ""))) if idle else ""
    return imr.oob(f"""<div class="cv-form">{_dim(_esc(said))}{rows or _dim("offers nothing yet")}{waiting}</div>""", f"""cv-prov-{payload["id"]}""")

async def _h_provider_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes providers.", True), "cv-msg")
    old = AV.lib.get("provider", payload["id"]) if payload.get("id") else {}
    if not (payload.get("name", "").strip() and payload.get("url", "").strip()): return imr.oob(_note("A provider needs a name and an address.", True), "cv-msg")
    AV.lib.save("provider", {"id": old.get("id") or _slug(payload["name"]), "name": payload["name"].strip(), "url": PROV.address(payload["url"]), "key": payload.get("key") or old.get("key", ""), **({"speaks": payload["speaks"]} if payload.get("speaks") else {})}, by=_user(request))
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note(f"""Saved {payload["name"]}."""))

async def _h_provider_del(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes providers.", True), "cv-msg")
    AV.lib.remove("provider", payload["id"])
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note("Removed."))

def _cand_value(choices: list, cand: dict) -> str:
    """The option that is this candidate: its provider and asset, or the asset alone when it names no provider."""
    return next((v for v, _ in choices if v and (v == cand.get("provider", "") + "|" + cand.get("asset", "") or (not cand.get("provider") and v.split("|", 1)[1] == cand.get("asset")))), "|" + cand["asset"] if cand.get("asset") else "")

_OPS = {"number": [(">", "is more than"), ("<", "is less than"), (">=", "is at least"), ("<=", "is at most")], "yes/no": [("yes", "yes"), ("no", "no")], "": [("==", "is"), ("!=", "is not")]}   # how a case is put together from a fact, by the fact's kind

def _option(v, label, on) -> str: return f"""<option value="{_esc(v)}" {"selected" if v == on else ""}>{_esc(label)}</option>"""
def _options(pairs, on) -> str: return "".join(_option(v, l, on) for v, l in pairs)
def _fact(x) -> dict: return {"is": x, "label": "", "kind": ""} if isinstance(x, str) else {"label": "", "kind": "", **x}
def _case_parts(when: str) -> tuple:
    """(fact, op, value) when the condition is one the case chooser makes, else None: it is then shown as written."""
    if not when: return "", "", ""
    if m := re.fullmatch(r"\s*(not\s+)?(\w+)\s*", when): return m[2], "no" if m[1] else "yes", ""
    if m := re.fullmatch(r"""\s*(\w+)\s*(>=|<=|==|!=|>|<)\s*([\w.'"-]+)\s*""", when): return m[1], m[2], m[3]
    return None
def _case_made(fact: str, op: str, value: str) -> str: return "" if not fact else fact if op == "yes" else f"not {fact}" if op == "no" else f"{fact} {op} {value.strip()}" if value.strip() else ""

def _cand_row(role: str, i: int, cand: dict, choices: list, facts: dict) -> str:
    """One candidate: what fills the role, and in which case - chosen from the role's facts (always / a fact compared with a value), or written out as a condition when the chooser cannot say it."""
    cur, nm = _cand_value(choices, cand), f"{_esc(role)}_{i}"
    opts = "".join(f"""<option value="{_esc(v)}" {"selected" if v == cur else ""}>{_esc(label)}</option>""" for v, label in ([*choices, (cur, cand["asset"] + "  -  not offered now")] if cur and cur not in [v for v, _ in choices] else choices))
    parts, fs = _case_parts(cand.get("when", "")), {k: _fact(x) for k, x in facts.items()}
    parts = None if parts and parts[0] and parts[0] not in fs else parts   # a condition over a fact the role does not list (a caller's case) is shown as written
    f0, op0, v0 = parts or ("", "", "")
    sel = lambda name, pairs, on: f"""<select name="{name}_{nm}" class="module-select">{_options(pairs, on)}</select>"""
    ops = [x for k in {fs[f0]["kind"] if f0 in fs else ""} | {""} for x in _OPS.get(k, [])] if f0 else _OPS["number"] + _OPS["yes/no"] + _OPS[""]
    chooser = f"""<span class="cv-dim">used</span>{sel("cf", [("", "always")] + [(k, f["label"] or k) for k, f in fs.items()], f0)}{sel("co", ops, op0)}<input name="cv_{nm}" class="module-select" style="width:6rem" value="{_esc(v0)}" placeholder="value">""" if fs else """<span class="cv-dim">used always, unless a condition is written out:</span>"""   # a role without facts has nothing to choose a case from
    written = f"""<input name="w_{nm}" class="module-select mono grow" value="{_esc(cand.get("when", "") if parts is None else "")}" placeholder="or a condition written out (optional)" title="Any condition over the facts, as a Python expression, e.g. chars > 20000 and not images. When filled it is used instead of the choice before it.">"""
    return f"""<div class="row" style="flex-wrap:wrap"><span class="cv-dim">{i + 1}.</span><select name="r_{nm}" class="module-select mono">{opts}</select>{chooser}{written}<input name="n_{nm}" class="module-select" value="{_esc(cand.get("note", ""))}" placeholder="note"></div>"""

async def p_bindings(c) -> str:
    roles, offers = _all_roles(), await _offers()
    if not roles: return _no_pipelines()
    def one(r, need):
        choices, cands = _choices(offers, need, "(none)"), _cands(r, [c.spec["profile"]])
        facts = ", ".join(f"""{k} ({_fact(x)["label"]})""" if _fact(x)["label"] else k for k, x in (need.get("facts") or {}).items()) or "none"
        return f"""<div class="cv-role"><b>{_esc(r)}</b> <span class="cv-dim">{_esc(need.get("about", ""))} | needs: {_esc(", ".join(need.get("needs") or []))} | facts for its cases: {_esc(facts)}</span>{"".join(_cand_row(r, i, cand, choices, need.get("facts") or {}) for i, cand in enumerate([*cands, {}]))}</div>"""
    about = _dim(f"""A role is a need a pipeline names instead of a model - "main" is whoever answers in a conversation. Each role has candidates in order of preference (profile {_esc(c.spec["profile"])}): the first one whose case holds and which fits where it runs is used. "Used" says in which case a line is chosen: always, or when one of the role's facts (listed beside the role) compares with a value - for example a large model when the length of the conversation is more than 20000 characters, another when images come with it. Put the "always" line last: lines are tried from the top. A pin, in a conversation or a run, stands above this list. To drop a line set it to (none); an empty line for one more is always at the end.""")
    none = "" if any(o["assets"] for o in offers) else _note("No provider answers yet, so there is nothing to choose from. Add one above, or see why it does not answer.", True)
    return f"""{about}{_unreached(offers)}{none}<form id="cv-bind-f" onsubmit="return false">{"".join(one(r, need) for r, need in roles.items())}<div class="row"><span class="grow"></span>{_btn("Save", "bindings_save", face=c.face["id"], profile=c.spec["profile"], include="#cv-bind-f")}</div></form>"""

async def _h_bindings_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes this profile.", True), "cv-msg")
    old, new = _profile(payload["profile"]), {}
    for r in _all_roles():
        before, i, new[r] = {x.get("asset"): x for x in _cands(r, [payload["profile"]])}, 0, []
        while f"r_{r}_{i}" in payload:
            prov, _, asset = payload[f"r_{r}_{i}"].partition("|")
            if asset: new[r].append({**{k: v for k, v in before.get(asset, {}).items() if k not in ("provider", "when", "note")}, **({"provider": prov} if prov else {}), "asset": asset, **({"when": w} if (w := payload.get(f"w_{r}_{i}", "").strip() or _case_made(payload.get(f"cf_{r}_{i}", ""), payload.get(f"co_{r}_{i}", ""), payload.get(f"cv_{r}_{i}", ""))) else {}), **({"note": payload[f"n_{r}_{i}"].strip()} if payload.get(f"n_{r}_{i}", "").strip() else {})})   # what the line does not show (request defaults, streams) stays with its asset
            i += 1
    AV.lib.save("bindings", {**{k: v for k, v in old.items() if k not in ("modified", "by")}, "roles": {r: cs for r, cs in new.items() if cs}}, by=_user(request))
    return await _refresh(request, imr, payload["face"], _note("Saved. Work started from now on uses it; the version before is kept."))

_WHO = [("nobody", "nobody"), ("admins", "portal admins only"), ("everyone", "everyone who can open Corvid")]
_LIMITS = {"python": ("Who may run Python code of their own choosing", "Code given when the work starts, or read from a file that can change. It runs as the portal itself: it can read, change and delete anything the portal can, and reach the network."),
           "python_fixed": ("Who may run pipelines with Python code written into them", "The code is part of the pipeline and shown before it starts; only those who may change pipelines can change it (an approved tool used from Athena, for example). It still runs as the portal itself.")}   # each is the owner's decision alone; Aviary only asks what is set here

async def p_limits(c) -> str:
    """The owner's decisions on what runs may do beyond the default (library object policy "aviary")."""
    pol = AV.policy()
    fields = [BI.SettingField(k, label, "select", options=_WHO + ([(json.dumps(pol[k]), "these people: " + ", ".join(pol[k]))] if isinstance(pol.get(k), list) else []), hint=hint) for k, (label, hint) in _LIMITS.items()]
    return f"""{_dim("Nothing outside this portal sets these. A list of names instead of one of the choices can be written in the policy object itself (Library, policy).")}<form id="cv-lim-f" onsubmit="return false">{_group(fields).render({k: json.dumps(pol[k]) if isinstance(pol.get(k), list) else pol.get(k, "nobody") for k in _LIMITS})}<div class="row"><span class="grow"></span>{_btn("Save", "limits_save", face=c.face["id"], include="#cv-lim-f")}</div></form>"""

async def _h_limits_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin sets the limits.", True), "cv-msg")
    pol = AV.policy()
    AV.lib.save("policy", {**{k: v for k, v in pol.items() if k not in ("modified", "by", "id")}, "id": "aviary", **{k: json.loads(payload[k]) if payload[k].startswith("[") else payload[k] for k in _LIMITS if payload.get(k)}}, by=_user(request))
    return await _refresh(request, imr, payload["face"], _note("Saved. It holds for runs started from now on."))

async def p_guide(c) -> str:
    """What is still missing before anything can run, in the order to do it."""
    offers, roles, prof = await _offers(), _all_roles(), _profile(c.spec["profile"])
    up, open_roles = [o for o in offers if not o["error"]], [r for r in roles if not _cands(r, [prof["id"]])]
    steps = [(bool(roles), "Aviary has its pipelines", "" if roles else "none found - see the note under 2."),
             (bool(up), "A provider answers", f"{len(up)} of {len(offers)} answer" if offers else "add one under 1."),
             (bool(roles) and not open_roles, "Every role is filled", "still open: " + ", ".join(open_roles) if open_roles else ""),
             (False, "Try it", "open the Tessa tab and say something; \"the run behind this\" on an answer shows what was done")]
    rows = "".join(f"""<div class="row"><span class="{"cv-ok" if ok else "cv-dim"}">{"&#x2713;" if ok else "&#x25CB;"}</span><span class="grow">{_esc(label)}{_dim(_esc(hint))}</span></div>""" for ok, label, hint in steps)
    return rows

async def p_library(c) -> str:
    def info(kind, o): return " | ".join(x for x in (o["id"], f"""{len(AV.lib.versions(kind, o["id"]))} earlier versions""" if AV.lib.versions(kind, o["id"]) else "", str(o.get("objective") or o.get("about") or "")[:120]) if x)
    def rows(kind): return "".join(f"""<div class="list-row row"><b>{_esc(o.get("name") or o["id"])}</b><span class="chip">{AV.lib.origin(kind, o["id"])}</span><span class="cv-dim grow">{_esc(info(kind, o))}</span>{_btn("Open", "lib_open", face=c.face["id"], kind=kind, id=o["id"])}</div>""" for o in AV.lib.list(kind))
    kinds = "".join(f"""<details><summary class="cv-dim"><b>{_esc(k)}</b> ({len(AV.lib.list(k))})</summary>{rows(k) or _dim("none")}<div class="row"><span class="grow"></span>{_btn("New", "lib_open", face=c.face["id"], kind=k, id="")}</div></details>""" for k in c.spec["kinds"])
    return f"""{_dim("Everything Corvid and Aviary keep, as the JSON it is. Shipped objects come with the software and are never changed; saving one makes it yours, and removing yours brings the shipped one back. Every save keeps the version before it.")}{kinds}<div id="cv-lib-edit"></div>"""

async def _h_lib_open(request, payload, imr):
    kind, oid = payload["kind"], payload["id"]
    if payload.get("close"): return imr.oob("", "cv-lib-edit")
    obj = {k: v for k, v in AV.lib.get(kind, oid).items() if k not in ("modified", "by")} if oid else {"id": "", "name": ""}
    back = _btn("Back to shipped", "lib_remove", face=payload["face"], kind=kind, id=oid, confirm="Remove your version? It is kept as an earlier version.") if oid and AV.lib.origin(kind, oid) == "mine" else ""
    return imr.oob(f"""<form class="cv-form" id="cv-lib-f" onsubmit="return false"><div class="row"><b>{_esc(kind)}</b><span class="mono grow">{_esc(oid or "new")}</span>{_btn("Save as mine", "lib_save", face=payload["face"], kind=kind, include="#cv-lib-f")}{back}{_btn("Close", "lib_open", face=payload["face"], kind=kind, id=oid, close="1")}</div><textarea name="json" class="module-select mono cv-json" spellcheck="false">{_esc(json.dumps(obj, indent=1, ensure_ascii=False))}</textarea></form>""", "cv-lib-edit")

async def _h_lib_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes the library.", True), "cv-msg")
    try: obj = json.loads(payload["json"])
    except ValueError as e: return imr.oob(_note(f"Not saved, the text is not JSON: {e}", True), "cv-msg")
    if not _slug(str(obj.get("id", ""))): return imr.oob(_note("Not saved: it needs an id.", True), "cv-msg")
    AV.lib.save(payload["kind"], {**obj, "id": _slug(obj["id"])}, by=_user(request))
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note(f"""Saved {payload["kind"]} {obj["id"]}."""))

async def _h_lib_remove(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes the library.", True), "cv-msg")
    AV.lib.remove(payload["kind"], payload["id"])
    return await _refresh(request, imr, payload["face"], _note("Removed yours."))

# --- Panel: runs (start a pipeline, follow and steer what runs) ---

_FIELD = {"boolean": "checkbox", "integer": "number", "number": "number", "list": "json", "object": "json", "code": "textarea", "long": "textarea", "items": "items"}
def _levels(show: dict, keys) -> dict:
    """How much a face shows of each input: "shown", "advanced" (under More) or "fixed" (not shown: the face's value holds). show: {input: level, "*": the level of every input it does not name}."""
    return {k: show.get(k, show.get("*", "shown")) for k in keys}

def _exposed(fields: list, levels: dict, values: dict, prefix: str, form_id: str, fm=None) -> str:
    """Settings fields at their levels, drawn by the portal's settings group: the shown ones, the advanced ones in its Advanced section, a fixed one not at all. Also tells the form which fields it holds, so an unticked box is told from one that was not there. fm: the file manager an items field picks from."""
    held = [f for f in fields if levels.get(f.name, "shown") != "fixed"]
    for f in held: f.advanced = levels.get(f.name) == "advanced"
    return f"""{_group(held).render(values, fm=fm, name_prefix=prefix) if held else ""}<input type="hidden" name="{prefix}_held" value="{_esc(",".join(f.name for f in held))}">"""

def _held(payload: dict, prefix: str) -> set: return set(filter(None, payload.get(prefix + "_held", "").split(",")))

def _may(request) -> list: return [what for what in _LIMITS if AV.allows(what, _user(request), _admin(request))]   # what the owner's policy allows this person's runs beyond the default
def _free_code(plan: dict) -> list: return [st for st in _code_steps(plan) if not (st.get("config") or {}).get("script")]   # code steps whose code is not written into the pipeline
def _code_steps(plan: dict) -> list:
    """Every step of a plan that runs code, also inside groups and inside plans written into a step."""
    out = []
    for st in plan.get("steps", []): out += ([st] if st.get("type") == "python" else []) + _code_steps(st) + _code_steps((st.get("config") or {}).get("plan") or {})
    return out
def _param_fields(pl: dict) -> list:
    """A pipeline's parameters as form fields. "pick": <library kind> makes one a choice among that kind's objects (a space, a prompt, ...)."""
    picks = lambda p: [(o["id"], o.get("name") or o["id"]) for o in AV.lib.list(p["pick"])]
    return [BI.SettingField(k, p.get("label") or k, "select" if p.get("pick") else _FIELD.get(p.get("type"), "text"), default=p.get("default"), options=picks(p) if p.get("pick") else None, hint=p.get("hint", ""), step=1 if p.get("type") == "integer" else None) for k, p in (pl.get("params") or {}).items()]

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
    acts = _btn("Open", "run_view", id=r.id) + (_btn("Stop", "run_stop", face=face_id, id=r.id, title="No further steps start; those working finish") + _btn("Stop now", "run_stop", "ui-btn cv-danger", face=face_id, id=r.id, now="1", title="Steps working are cut off too; what they had not kept is done again if it goes on") if st in LIVE else (_btn("Go on", "run_go", face=face_id, id=r.id) if st != "done" else "") + _btn("Again", "run_again", face=face_id, id=r.id, title="A new run with the same inputs: syncs the same files again, asks the same again") + _btn("&#x2715;", "run_remove", "ui-btn cv-small", face=face_id, id=r.id, confirm="Remove this run and its records?"))
    info = " | ".join(x for x in (f"""{len(r.plan["steps"])} steps""" if st == "done" else f"""{len(v["done"])} of {len(r.plan["steps"])} steps""", ", ".join(v["busy"]), _esc(r.meta.get("error", ""))[:200], _when(r.meta["created"]), _esc(r.meta.get("owner", ""))) if x)
    return f"""<div class="list-row"><div class="row"><b>{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(st, "")}">{_esc(st)}</span><span class="grow">{_esc(_about(r))}</span>{acts}</div>{_dim(info)}</div>"""

def _run_list(request, face: dict, key: str) -> str:
    """The runs this person may see here (their own; an admin: everyone's), of the groups the panel shows, newest first. Polls itself while one is under way."""
    spec = _spec(face, key)
    runs = sorted((r for r in AV.director.runs.values() if not r.meta.get("parent") and (_admin(request) or r.meta.get("owner") == _user(request)) and (not spec.get("groups") or r.plan.get("group") in spec["groups"])), key=lambda r: r.meta["created"], reverse=True)[:30]   # a run made by another run's step is shown inside that run
    poll = f"""hx-get="{_P}/runs?face={_esc(face["id"])}&amp;key={key}" hx-trigger="every 2s" hx-swap="outerHTML" """ if any(r.meta["state"] in LIVE for r in runs) else ""
    ended = [r.id for r in runs if r.meta["state"] not in LIVE]
    clear = f"""<div class="row"><span class="grow"></span>{_btn(f"Remove the {len(ended)} that ended", "run_remove", "ui-btn cv-small", face=face["id"], ids=",".join(ended), confirm="Remove every run here that is not under way, with its records?")}</div>""" if len(ended) > 1 else ""
    return f"""<div id="cv-runs" {poll}>{clear}{"".join(_run_row(face["id"], r) for r in runs) or _dim("nothing has run here yet")}</div>"""

async def p_runs(c) -> str:
    plans = "".join(f"""<div class="list-row row"><b>{_esc(pl.get("name") or pl["id"])}</b><span class="cv-dim grow">{_esc(pl.get("objective", ""))[:170]}</span>{_btn("Set up", "run_form", face=c.face["id"], id=pl["id"], key=c.key)}</div>""" for pl in AV.lib.list("pipeline") if not c.spec.get("groups") or pl.get("group") in c.spec["groups"])
    return f"""{_dim("A pipeline says what is to be done; Aviary decides how, with what is free. A run goes on when this page is closed.")}{plans or _no_pipelines()}<div id="cv-run-form"></div>{_run_list(c.request, c.face, c.key)}"""

def _run_spec(payload: dict) -> dict: return _spec(AV.lib.get("face", payload["face"]), payload["key"]) if payload.get("key") else {}

async def _run_form_html(request, face_id: str, pid: str, key: str, picked: dict = None) -> str:
    """The form that sets up one pipeline's run. picked: values to show instead of the defaults (the files just uploaded, ticked)."""
    pl, offers, spec = AV.lib.get("pipeline", pid), await _offers(), _run_spec({"face": face_id, "key": key})
    show = {**spec.get("show", {}), **spec.get("show_for", {}).get(pl["id"], {})}   # the panel's levels for every pipeline it lists, then those it gives for this one
    params = pl.get("params") or {}
    values = {**{k: spec.get("inputs", {}).get(k, p.get("default")) for k, p in params.items()}, **(picked or {})}
    items = next((k for k, p in params.items() if p.get("type") == "items"), None)
    fm = AV.space(values[params[items]["space_from"]])[0] if items else None
    role_level = show.get("roles", show.get("*", "shown"))
    roles = "" if role_level == "fixed" else _exposed(_role_fields(pl.get("roles") or {}, offers, "(as the profile says)"), {r: role_level for r in pl.get("roles") or {}}, {}, "r_", "cv-run-f")
    code, sure = _code_steps(pl), ""
    if code and not {"python" if _free_code(pl) else "python_fixed"} <= set(_may(request)): sure = _note("This pipeline runs " + ("Python code of your own choosing" if _free_code(pl) else "the Python code written into it") + ", and you are not among those who may on this portal. The owner decides who may: Settings, Limits.", True)
    elif code and not _free_code(pl): sure = _dim("Runs the Python code written into this pipeline: " + ", ".join(st["id"] for st in code) + ".") + "".join(f"""<details><summary class="cv-dim">step {_esc(st["id"])}: the code</summary><div class="quote-block mono cv-log">{_esc(st["config"]["script"])}</div></details>""" for st in code)
    elif code:
        shown = "".join(f"""<details><summary class="cv-dim">step {_esc(st["id"])}: the code</summary><div class="quote-block mono cv-log">{_esc((st.get("config") or {}).get("script") or "given when it runs (a parameter or a file)")}</div></details>""" for st in code)
        sure = f"""<div class="cv-err">This pipeline runs Python code as the portal itself: it can read, change and delete anything the portal can, and reach the network. Nothing limits it once started.{shown}<label><input type="checkbox" name="sure" value="1"> I have looked at what it runs and want it to run</label></div>"""
    upload = f"""<form class="cv-form" hx-post="{_P}/upload" hx-encoding="multipart/form-data" hx-target="#cv-run-form" hx-swap="innerHTML"><b>Bring files into {_esc(AV.lib.get("space", values[params[items]["space_from"]]).get("name") or values[params[items]["space_from"]])}</b>{_dim("From this computer, into a folder of the space; they are then ticked above.")}<input type="hidden" name="face" value="{_esc(face_id)}"><input type="hidden" name="pid" value="{_esc(pid)}"><input type="hidden" name="key" value="{_esc(key)}"><input type="hidden" name="space" value="{_esc(values[params[items]["space_from"]])}"><input type="hidden" name="field" value="{_esc(items)}">{_dim("Into the folder ticked here (the space itself when none is):")}{fm.folder_picker_html()}<div class="row"><input name="new_folder" class="module-select grow" placeholder="a new folder inside it (optional)"></div><div class="row"><input type="file" name="files" multiple class="module-select grow"><button type="submit" class="ui-btn">Upload</button></div></form>""" if items else ""
    return f"""<form class="cv-form" id="cv-run-f" onsubmit="return false"><div class="row"><b class="grow">{_esc(pl.get("name") or pl["id"])}</b>{_btn("Start", "run_start", face=face_id, id=pl["id"], key=key, include="#cv-run-f")}{_btn("Close", "run_form", face=face_id, close="1")}</div>{_dim(_esc(pl.get("objective", "")))}{_exposed(_param_fields(pl), _levels(show, params), values, "p_", "cv-run-f", fm)}{_unreached(offers) if pl.get("roles") else ""}{roles}{sure}</form>{upload}"""

async def _h_run_form(request, payload, imr):
    if payload.get("close"): return imr.oob("", "cv-run-form")
    return imr.oob(await _run_form_html(request, payload["face"], payload["id"], payload.get("key", "")), "cv-run-form")

async def _h_run_start(request, payload, imr):
    face, pl = AV.lib.get("face", payload["face"]), AV.lib.get("pipeline", payload["id"])
    if _code_steps(pl) and ("python" if _free_code(pl) else "python_fixed") not in _may(request): return imr.oob(_note("Not started: it runs Python code, and you are not among those who may start that here (Settings, Limits).", True), "cv-msg")
    if _free_code(pl) and not payload.get("sure"): return imr.oob(_note("Not started: it runs Python code, and the box saying you have looked at it is not ticked.", True), "cv-msg")
    spec, held = _run_spec(payload), _held(payload, "p_")
    given = {**{k: v for k, v in spec.get("inputs", {}).items() if k in (pl.get("params") or {})}, **{k: v for k, v in _group(_param_fields(pl)).parse(payload, "p_").items() if k in held and v not in ("", None, {}, [])}}   # what the form did not hold is the panel's own value, else the pipeline's default
    try: rid = await AV.start(pl, given, owner=_user(request), profiles=face.get("profiles", []), pins=_picked(payload, pl.get("roles") or {}, "r_"), may=_may(request))
    except ValueError as e: return imr.oob(_note(f"Not started: {e}", True), "cv-msg")
    return await _refresh(request, imr, face["id"], _note(f"Started as {rid}."))

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

def _run_view(r) -> str:
    """One run, whatever its pipeline: who fills its roles, each step and where it stands, what exists of its results, the last of its journal."""
    v, have = r.view(), set(r.data)
    nxt, kept = set(v["course"][0]) if v["course"] else set(), {unquote(f.stem) for f in (r.dir / "kept").glob("*.json")}
    def where(s): return "done" if "@" + s["id"] in have or (r.meta["state"] == "done" and s["id"] not in v["unreached"]) else "running" if s["id"] in v["busy"] else "unreached" if s["id"] in v["unreached"] else "next" if s["id"] in nxt else "waiting"   # a finished run read back from disk has only what its plan kept: its other steps were done all the same
    bound = "".join(f"""<div class="cv-dim"><b>{_esc(role)}</b>: <span class="mono">{_esc(b.get("asset"))}</span> on {_esc(b.get("provider"))}. {_esc(b.get("will", ""))}</div>""" for role, b in (r.meta.get("bound") or {}).items())
    steps = "".join(f"""<tr><td class="mono">{_esc(s["id"])}</td><td>{_esc(s["type"])}</td><td class="{_STATE.get(where(s), "")}">{where(s)}</td><td>{"kept" if "@" + s["id"] in kept else ""}</td></tr>""" for s in r.plan["steps"])
    start = set(r.plan.get("params") or {}) | set(r.plan.get("data") or {})
    keys = "".join(f"""<tr><td class="mono">{_esc(k)}</td><td>{_esc(_shown(val)[:400])}</td></tr>""" for k, val in r.data.items() if not k.startswith("@") and k not in start)
    again = _btn("It may run again", "run_decide", id=r.id, step=r.meta.get("held_at", "")) if r.meta["state"] == "held" else ""
    subs = "".join(f"""<div class="row cv-dim"><span class="mono grow">{_esc(c.id.split("~", 1)[1])}</span><span class="chip {_STATE.get(c.meta["state"], "")}">{_esc(c.meta["state"])}</span>{_btn("Open", "run_view", "ui-btn cv-small", id=c.id)}</div>""" for c in sorted(AV.director.runs.values(), key=lambda c: c.meta["created"]) if c.meta.get("parent") == r.id)
    up = _btn("Up", "run_view", id=r.meta["parent"]) if r.meta.get("parent") else ""
    return f"""<div class="cv-sec"><div class="row"><b class="grow">{_esc(r.plan.get("name") or r.id)}</b><span class="chip {_STATE.get(r.meta["state"], "")}">{_esc(r.meta["state"])}</span></div><div class="row">{again}{up}{_btn("Refresh", "run_view", id=r.id)}{_btn("Close", "run_view", id=r.id, close="1")}</div>{_dim(_esc(r.id) + " | " + _esc(r.meta.get("owner", "")))}{_note(r.meta["error"], True) if r.meta.get("error") else ""}<b>Roles</b>{bound or _dim("none placed yet")}<b>Steps</b><table class="cv-tbl"><tr><th>step</th><th>type</th><th>state</th><th></th></tr>{steps}</table>{"<b>Runs its steps made</b>" if subs else ""}{subs}<b>What exists of its results</b><table class="cv-tbl">{keys}</table><b>Journal</b><div class="quote-block mono cv-log">{_esc(chr(10).join((r.dir / "journal.jsonl").read_text().splitlines()[-12:]))}</div></div>"""

async def _h_run_view(request, payload, imr): return imr.oob("" if payload.get("close") else _run_view(_run(request, payload["id"])), "cv-run-view")

async def _h_run_decide(request, payload, imr):
    r = _run(request, payload["id"])
    AV.director.decide(r.id, payload["step"], again=True)
    await AV.go(r.id)
    return imr.oob(_run_view(r), "cv-run-view")

# --- Panels: assets (what a provider lets a manager make there, by kind: the provider says what one is made of) and records (what such an asset holds, through capabilities the panel names) ---

def _asset_fields(kind: dict, assets: list, new: bool) -> list:
    """The kind's own fields as form fields; one that picks a model lists what that provider offers for the capability named."""
    def field(f):
        cap = f.get("pick", "").partition(":")[2]
        return BI.SettingField(f["name"], f.get("label") or f["name"], "select" if cap else _FIELD.get(f.get("type"), "text"), default=f.get("default"), options=[("", "(choose)")] + [(a["name"], a["name"]) for a in assets if cap in a.get("capabilities", [])] if cap else None, hint=f.get("hint", ""))
    return ([BI.SettingField("new_name", "Name", "text", hint="Short, without spaces; it is how it is named everywhere from here on.")] if new else []) + [field(f) for f in kind["fields"]]   # the new one's name is "new_name": the button's own values carry the name of the one being changed

async def p_assets(c) -> str:
    kind, out = c.spec["kind"], ""
    for o in await _offers():
        p, pname = o["p"], o["p"].get("name") or o["p"]["id"]
        if o["error"]:
            out += _note(o["error"], True)
            continue
        if p.get("speaks"):
            out += _dim(f"""{_esc(pname)} speaks {_esc(p["speaks"])}: nothing can be made there from here.""")
            continue
        try: kinds = (await PROV.manage(p, "GET"))["kinds"]
        except PROV.ProviderError:
            out += _dim(f"{_esc(pname)}: this provider's software has no way yet to make things on it from here (it needs the update that adds /assets).")
            continue
        if kind not in kinds:
            out += _dim(f"{_esc(pname)}: nothing active there manages this kind. Install or activate its module on that machine: Settings, Machines.")
            continue
        k = kinds[kind]
        def row(a):
            said = " | ".join(f.get("label", f["name"]) + ": " + _shown(a.get(f["name"])) for f in k["fields"] if a.get(f["name"]) not in (None, ""))
            return f"""<div class="list-row row"><b>{_esc(a["name"])}</b><span class="chip">{_esc(a.get("status", ""))}</span><span class="cv-dim grow">{_esc(said)}</span>{_btn("Change", "asset_form", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"])}{_btn("Remove", "asset_del", "ui-btn cv-danger", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"], confirm="Remove it from that machine?" + (" What it holds stays on disk there." if k.get("holds") else ""))}{_btn("Remove with what it holds", "asset_del", "ui-btn cv-danger", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"], data="1", confirm="Remove it AND delete everything it holds on that machine? This cannot be undone.") if k.get("holds") else ""}</div>"""
        rows = "".join(row(a) for a in (await PROV.manage(p, "GET", kind))["assets"])
        out += f"""<div class="row"><b>{_esc(k.get("label", kind))}s on {_esc(pname)}</b><span class="grow"></span>{_btn("New", "asset_form", face=c.face["id"], pid=p["id"], kind=kind)}</div>{_dim(_esc(k.get("about", "")))}{rows or _dim("none yet - New makes the first")}"""
    return f"""{out or _dim("no provider yet - add one in Settings")}<div id="cv-asset-form"></div>"""

async def _h_asset_form(request, payload, imr):
    if payload.get("close"): return imr.oob("", "cv-asset-form")
    p, kind, name = AV.lib.get("provider", payload["pid"]), payload["kind"], payload.get("name", "")
    k, assets = (await PROV.manage(p, "GET"))["kinds"][kind], next(o["assets"] for o in await _offers() if o["p"]["id"] == p["id"])
    cur = next((a for a in (await PROV.manage(p, "GET", kind))["assets"] if a["name"] == name), {})
    head = f"""Change {_esc(name)}""" if name else f"""New {_esc(k.get("label", kind)).lower()} on {_esc(p.get("name") or p["id"])}"""
    return imr.oob(f"""<form class="cv-form" id="cv-asset-f" onsubmit="return false"><b>{head}</b>{_group(_asset_fields(k, assets, not name)).render({f["name"]: cur.get(f["name"], f.get("default")) for f in k["fields"]})}<div class="row"><span class="grow"></span>{_btn("Save", "asset_save", face=payload["face"], pid=p["id"], kind=kind, name=name, include="#cv-asset-f")}{_btn("Cancel", "asset_form", close="1")}</div></form>""", "cv-asset-form")

async def _h_asset_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin makes or changes things on a provider.", True), "cv-msg")
    p, kind = AV.lib.get("provider", payload["pid"]), payload["kind"]
    k, name = (await PROV.manage(p, "GET"))["kinds"][kind], payload.get("name") or _slug(payload.get("new_name", ""))
    body = {key: v for key, v in _group(_asset_fields(k, [], False)).parse(payload).items() if v not in ("", None)}
    if not name: return imr.oob(_note("It needs a name.", True), "cv-msg")
    try: await PROV.manage(p, "PUT", kind, name, body)
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note(f"Saved {name}."))

async def _h_asset_del(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin removes things from a provider.", True), "cv-msg")
    try: await PROV.manage(AV.lib.get("provider", payload["pid"]), "DELETE", payload["kind"], payload["name"], query="?confirm=1" + ("&data=1" if payload.get("data") else ""))
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note(f"""Removed {payload["name"]}{" and what it held" if payload.get("data") else ""}."""))

async def _asset_pick(c, cap: str):
    """(provider, asset name, the row of tabs choosing it) among every asset offering cap; the choice is kept by the face's tab, so the views of one face show the same asset. None when there is none."""
    offers = await _offers()
    have = [(o["p"], a["name"]) for o in offers for a in o["assets"] if cap in a.get("capabilities", [])]
    if not have: return None, None, _unreached(offers) + _dim("nothing of this kind exists yet")
    cur = c.tab.get("asset") if c.tab.get("asset") in [p["id"] + "|" + n for p, n in have] else have[0][0]["id"] + "|" + have[0][1]
    p, name = next((p, n) for p, n in have if p["id"] + "|" + n == cur)
    return p, name, _tab_row("cv-asset-tabs", c.host, [(n, p2["id"] + "|" + n == cur, {"asset": p2["id"] + "|" + n}) for p2, n in have])

def _program_btns(c, p: dict, name: str) -> str:
    """The panel's ways to steer the program behind an asset, from its data: "cancel" and "retry" (capabilities: stop its work on what was added, take up what failed again) and "service" (the name of the program on its machine, {asset} filled: stopped at once, or started again, from here)."""
    sp, kw = c.spec, {"face": c.face["id"], "pid": p["id"], "asset": name}
    svc = sp.get("service", "").replace("{asset}", name)
    return "".join(x for x in (
        _btn("Stop its work", "program", cap=sp["cancel"], title="Asks the program to stop working on what was added; what is half done is marked failed", **kw) if sp.get("cancel") else "",
        _btn("Take up failed again", "program", cap=sp["retry"], **kw) if sp.get("retry") else "",
        _btn("Hard stop", "program", "ui-btn cv-danger", svc=svc, verb="kill", confirm="Kill its program at once? Work under way is lost and has to be taken up again.", title="Kills the program on its machine; it starts again with the next work", **kw) if svc else "",
        _btn("Restart it", "program", svc=svc, verb="restart", **kw) if svc else ""))

async def _h_program(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin steers a provider's programs.", True), "cv-msg")
    p = AV.lib.get("provider", payload["pid"])
    try: await (PROV.machine(p, "POST", "/node/restart", {}, timeout=20.0) if payload.get("node") else PROV.machine(p, "POST", f"""/services/{quote(payload["svc"])}/{payload["verb"]}""", {}, timeout=300.0) if payload.get("svc") else PROV.run(p, payload["cap"], {"model": payload["asset"]}))
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    return await _refresh(request, imr, payload["face"], _note(f"""{payload["asset"]}: {payload.get("verb") or "asked"} - done."""))

async def p_records(c) -> str:
    """What an asset holds. The panel's own data says how to ask: {"list": capability, "in": the list's field in its answer, "status": capability, "remove": capability, "id": a record's id field, "columns": {heading: field}}, and how to steer its program (see _program_btns). Which asset: chosen at the top, among all that offer the list capability."""
    p, name, chips = await _asset_pick(c, c.spec["list"])
    if not p: return chips
    try: status, found = (await PROV.run(p, c.spec["status"], {"model": name}))["result"] if c.spec.get("status") else {}, (await PROV.run(p, c.spec["list"], {"model": name, "page_size": 200}))["result"]
    except PROV.ProviderError as e: return f"""{chips}{_note(str(e), True)}"""
    cols, recs = c.spec["columns"], found.get(c.spec.get("in", "documents"), [])
    def row(d):
        cells = "".join(f"""<td>{_esc(_shown(d.get(f))[:160])}</td>""" for f in cols.values())
        return f"""<tr>{cells}<td>{_btn("&#x2715;", "record_del", "ui-btn cv-small", face=c.face["id"], pid=p["id"], asset=name, cap=c.spec["remove"], rid=str(d.get(c.spec.get("id", "id"))), confirm="Remove this from what it holds?") if c.spec.get("remove") else ""}</td></tr>"""
    counts = " | ".join(f"{k}: {v}" for k, v in (status.get("counts") or {}).items()) + (" | working on what was added" + (f""": {_shown(status["doing"])[:200]}""" if status.get("doing") else "") if status.get("busy") else "")
    heads = "".join(f"""<th>{_esc(h)}</th>""" for h in cols)
    return f"""{chips}<div class="row">{_dim(_esc(counts))}<span class="grow"></span>{_program_btns(c, p, name)}</div><table class="cv-tbl"><tr>{heads}<th>{"remove" if c.spec.get("remove") else ""}</th></tr>{"".join(row(d) for d in recs)}</table>{"" if recs else _dim("it holds nothing yet")}"""

def _dig(d, path: str):
    for k in path.split("."): d = d.get(k) if isinstance(d, dict) else None
    return d

GRAPH_LAYOUTS = (("force", "Force"), ("ring", "Ring (by type)"), ("rings", "Rings (hubs inside)"))   # the layouts the portal's graph_view.js knows

async def p_graph(c) -> str:
    """An asset's graph, drawn by the portal's graph_view.js. The panel's data: {"graph": capability answering {nodes, edges, is_truncated}, "labels": capability answering {labels} (what the graph can be centred on), "type" and "info": where a node's kind and description are in it, "joins": a separator the program puts between merged descriptions}. Centre, depth and size are kept by the face's tab; a large graph is asked for a part at a time (around one label, at most so many nodes)."""
    p, name, chips = await _asset_pick(c, c.spec["graph"])
    if not p: return chips
    g = {"label": c.tab.get("g_label") or "*", "depth": int(c.tab.get("g_depth") or 2), "max_nodes": int(c.tab.get("g_max") or 300), "layout": c.tab.get("g_layout") or "force"}
    try: data, labels = (await PROV.run(p, c.spec["graph"], {"model": name, **g}))["result"], (await PROV.run(p, c.spec["labels"], {"model": name}))["result"].get("labels", []) if c.spec.get("labels") else []
    except PROV.ProviderError as e: return f"""{chips}{_note(str(e), True)}"""
    text = lambda d, n: str(_dig(d, c.spec.get("info", "properties.description")) or "").replace(c.spec.get("joins") or "\x00", "\n")[:n]
    nodes = [{"id": str(n.get("id")), "label": str((n.get("labels") or [n.get("id")])[0]), "type": str(_dig(n, c.spec.get("type", "properties.entity_type")) or ""), "info": text(n, 800)} for n in data.get("nodes", [])]
    edges = [{"s": str(e.get("source")), "t": str(e.get("target")), "info": text(e, 300)} for e in data.get("edges", [])]
    fid, opts = f"cv-graph-f-{c.face['id']}", "".join(f"""<option value="{_esc(l)}">""" for l in labels[:3000])
    layouts = "".join(f"""<option value="{v}"{" selected" if v == g["layout"] else ""}>{l}</option>""" for v, l in GRAPH_LAYOUTS)
    said = f"""{len(nodes)} nodes, {len(edges)} edges""" + (" - cut at the most nodes asked for: centre it on a label, or ask for more" if data.get("is_truncated") else "")
    form = f"""<form id="{fid}" class="row" style="flex-wrap:wrap" onsubmit="return false"><input name="g_label" list="{fid}-l" value="{_esc(g["label"])}" class="module-select" style="width:13rem" title="what it is centred on: pick from the list, or * for everything"><datalist id="{fid}-l"><option value="*">{opts}</datalist><label class="row cv-dim">depth<input type="number" name="g_depth" value="{g["depth"]}" min="1" max="6" class="module-select" style="width:4rem"></label><label class="row cv-dim">most nodes<input type="number" name="g_max" value="{g["max_nodes"]}" min="10" step="50" class="module-select" style="width:5rem"></label><label class="row cv-dim">layout<select name="g_layout" class="module-select">{layouts}</select></label>{_btn("Show", "open_tab", id=c.host, include="#" + fid)}<span class="cv-dim">{said}</span></form>"""
    init = f"""(function go() {{ var b = document.getElementById('cv-graph'); if (!b || b.dataset.ready) return; if (!window.graphView) return setTimeout(go, 50); b.dataset.ready = 1; graphView(b, {{layout: b.dataset.layout, onOpen: function (n) {{ htmx.ajax('POST', '/im/in', {{values: {{type: 'corvid_open_tab', branch: '{IM.branch_id}', lvl: 1, id: '{c.host}', g_label: n.id}}, swap: 'none'}}); }}}}); }})();"""
    js = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False).replace("</", "<\\/")
    return f"""{chips}{form}{_dim("Tap a node for what it is and what it links to; double-tap to centre on it. Drag to move, wheel or two fingers to zoom.")}<div id="cv-graph" class="cv-graph" data-layout="{_esc(g["layout"])}"><script type="application/json">{js}</script></div><script src="/static/js/graph_view.js"></script><script>{init}</script>"""

async def _h_record_del(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin removes what an asset holds, for now.", True), "cv-msg")
    try: await PROV.run(AV.lib.get("provider", payload["pid"]), payload["cap"], {"model": payload["asset"], "ids": [payload["rid"]]})
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    return await _refresh(request, imr, payload["face"], _note("Removed."))

# --- Panel: machines (each provider's own programs, as it lists them: what is active, installed, could be installed, and doing it) ---

INSTALLS = {}   # (provider id, module) -> {"lines", "done", "ok"}: an install going on, followed by the page while it lasts; the node's own log keeps it all

def _install_view(pid: str, name: str) -> str:
    rec = INSTALLS[(pid, name)]
    poll = "" if rec["done"] else f"""hx-get="{_P}/install?pid={_esc(pid)}&amp;name={_esc(name)}" hx-trigger="every 2s" hx-swap="outerHTML" """
    head = _note("Installed and active." if rec["ok"] else "Did not finish; the last lines say why.", not rec["ok"]) if rec["done"] else _dim("Installing - this goes on at the node if this page is closed.")
    return f"""<div {poll}>{head}<div class="quote-block mono cv-log">{_esc(chr(10).join(rec["lines"][-14:]))}</div></div>"""

async def p_machines(c) -> str:
    out = ""
    for o in await _offers():
        p, pname = o["p"], o["p"].get("name") or o["p"]["id"]
        if p.get("speaks"):
            out += _dim(f"""{_esc(pname)} speaks {_esc(p["speaks"])}: its programs are managed where it runs.""")
            continue
        try: d = await PROV.machine(p, "GET", "/modules", timeout=8.0)
        except PROV.ProviderError as e:
            out += _note(str(e), True)
            continue
        def row(m):
            st, pid, name = m["state"], p["id"], m["name"]
            acts = (_btn("Deactivate", "machine_act", face=c.face["id"], pid=pid, name=name, verb="deactivate", confirm="Stop offering what it does, now? Its files stay.") if st == "active"
                    else _btn("Activate", "machine_act", face=c.face["id"], pid=pid, name=name, verb="activate") if st == "installed" else "")
            acts += _btn("Install" if st not in ("active", "installed") else "Install again", "machine_form", pid=pid, name=name) if m.get("plan") else ""
            acts += _btn("Remove", "machine_act", "ui-btn cv-danger", face=c.face["id"], pid=pid, name=name, verb="remove", confirm="Remove its installed program and environment from that machine? Models and results stay.") if m.get("installed") and st != "active" else ""
            live = _install_view(pid, name) if (pid, name) in INSTALLS else ""
            err = _note(m["error"], True) if m.get("error") else ""
            return f"""<div class="list-row"><div class="row"><b>{_esc(m.get("label") or name)}</b><span class="chip {"cv-ok" if st == "active" else "cv-mid" if st == "installed" else ""}">{_esc(st)}</span><span class="cv-dim grow">{_esc(", ".join(m.get("provides") or []))}</span>{acts}</div>{err}<div id="cv-mod-{_esc(pid)}-{_esc(name)}">{live}</div></div>"""
        order = {"active": 0, "installed": 1}
        rows = "".join(row(m) for m in sorted(d["modules"], key=lambda m: (order.get(m["state"], 2), m["name"])))
        on = sum(m["state"] == "active" for m in d["modules"])
        out += f"""<details class="cv-machine"><summary><b>{_esc(pname)}</b> <span class="cv-dim">{_esc(p["url"])} | {on} active, {sum(m["state"] == "installed" for m in d["modules"])} installed, {len(d["modules"])} known</span></summary>{rows}{await _services(c.face["id"], p)}{await _locations(c.face["id"], p)}</details>"""
    return f"""{_dim("Each machine's programs, as it lists them. Installed means present; active means offered. Installing shows the program's options and what it needs from the system before anything is done; it is done by the machine itself, which downloads what the program names.")}{out or _dim("no provider yet")}"""

async def _services(face_id: str, p: dict) -> str:
    """The programs the machine has running or has run (its services), each stopped, killed or started again from here, with its log; and the node itself restarted."""
    try: svcs = (await PROV.machine(p, "GET", "/services", timeout=8.0))["services"]
    except PROV.ProviderError as e: return _dim(f"its running programs: {_esc(e)}")
    def row(sv):
        kw = {"face": face_id, "pid": p["id"], "asset": sv["name"], "svc": sv["name"]}
        up = sv["status"] not in ("stopped",) and not sv["status"].startswith("exited")
        said = " | ".join(x for x in (f"""{sv["rss_gb"]} GB""" if sv.get("rss_gb") else "", f"""{sv["active"]} working""" if sv.get("active") else "", f"""idle {sv["idle_s"]} s""" if up and sv.get("idle_s") is not None else "", _esc(sv.get("detail", ""))[:120]) if x)
        acts = (_btn("Stop", "program", verb="stop", title="Finishes what it is doing, then stops", **kw) + _btn("Kill", "program", "ui-btn cv-danger", verb="kill", confirm=f"""Kill {sv["name"]} at once? Work under way is lost.""", **kw) if up else "") + _btn("Restart" if up else "Start", "program", verb="restart" if up else "start", **kw) + _btn("Log", "svc_log", pid=p["id"], svc=sv["name"])
        return f"""<div class="list-row"><div class="row"><span class="mono cv-key">{_esc(sv["name"])}</span><span class="chip {"cv-ok" if sv["status"] == "up" else "cv-bad" if "fail" in sv["status"] or "exit" in sv["status"] else ""}">{_esc(sv["status"])}</span><span class="cv-dim grow">{said}</span>{acts}</div><div id="cv-log-{_esc(p["id"])}-{_elid(sv["name"])}"></div></div>"""
    restart = _btn("Restart the node", "program", "ui-btn cv-danger", face=face_id, pid=p["id"], asset="the node", node="1", confirm="Restart this machine's node? Work under way ends; what supervises it starts it again with its current settings and programs.")
    return f"""<div class="cv-role"><div class="row"><b class="grow">Running programs</b>{restart}</div>{"".join(row(sv) for sv in svcs) or _dim("none has run since the node started")}</div>"""

async def _h_svc_log(request, payload, imr):
    el = f"""cv-log-{payload["pid"]}-{_elid(payload["svc"])}"""
    if payload.get("close"): return imr.oob("", el)
    try: tail = (await PROV.machine(AV.lib.get("provider", payload["pid"]), "GET", f"""/services/{quote(payload["svc"])}/log?n=60""", timeout=8.0))["tail"]
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), el)
    return imr.oob(f"""<div class="quote-block mono cv-log">{_esc(chr(10).join(tail)) or "(empty)"}</div>{_btn("Close", "svc_log", pid=payload["pid"], svc=payload["svc"], close="1")}""", el)

async def _locations(face_id: str, p: dict) -> str:
    """Where the machine keeps each kind of thing (models, results, logs...), as it lists them, each changeable from here."""
    try: locs = (await PROV.machine(p, "GET", "/locations", timeout=8.0))["locations"]
    except PROV.ProviderError as e: return _dim(f"where it keeps things: {_esc(e)}")
    def row(l):
        free = f"""{l["disk"]["free_gb"]} of {l["disk"]["total_gb"]} GB free""" if l.get("disk") else ""
        return f"""<div class="list-row"><div class="row"><b class="cv-key">{_esc(l["name"])}</b><span class="mono grow">{_esc(l["path"])}</span><span class="cv-dim">{_esc(l.get("kind", ""))} | {free}{"" if l.get("exists") else " | missing"}</span>{_btn("Change", "loc_form", face=face_id, pid=p["id"], name=l["name"], at=l["path"])}</div><div id="cv-loc-{_esc(p["id"])}-{_esc(l["name"])}"></div></div>"""
    return f"""<div class="cv-role"><b>Where it keeps things</b>{_dim("A program sees a changed place at its next start. Moving takes what is there along, and waits for no work to be running.")}{"".join(row(l) for l in locs)}</div>"""

async def _h_loc_form(request, payload, imr):
    """A folder browser over the machine's own folders: each folder opens, "Use this folder" takes the one shown. Typing a path is possible, never needed."""
    p, name, el = AV.lib.get("provider", payload["pid"]), payload["name"], f"""cv-loc-{payload["pid"]}-{payload["name"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: b = await PROV.machine(p, "GET", "/browse?path=" + quote(payload.get("at") or ""), timeout=8.0)
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), el)
    go = lambda label, at: f"""<span class="chip cv-link" {_act("loc_form", face=payload["face"], pid=p["id"], name=name, at=at)}>{label}</span>"""
    dirs = "".join(go(f"&#x1F4C1; {_esc(d)}", b["path"].rstrip("/") + "/" + d) for d in b["folders"]) or _dim("no folders inside")
    up = go("&#x2B06; up", b["parent"]) if b["parent"] else ""
    fid = f"cv-locf-{p['id']}-{name}"
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false"><div class="row"><b class="mono grow">{_esc(b["path"])}</b><span class="cv-dim">{b["disk"]["free_gb"]} GB free</span></div><div class="row" style="flex-wrap:wrap">{up}{dirs}</div><div class="row"><input name="path" class="module-select mono grow" value="{_esc(b["path"])}" title="the folder shown; a path typed here is used instead"></div><label class="row"><input type="checkbox" name="move" value="1"> take what is there now along</label><div class="row"><span class="grow"></span>{_btn("Use this folder", "loc_save", face=payload["face"], pid=p["id"], name=name, include="#" + fid, confirm="Change where this machine keeps " + name + "?")}{_btn("Cancel", "loc_form", pid=p["id"], name=name, close="1")}</div></form>""", el)

async def _h_loc_save(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes where a machine keeps things.", True), "cv-msg")
    try: got = await PROV.machine(AV.lib.get("provider", payload["pid"]), "PUT", f"""/locations/{payload["name"]}""", {"path": payload["path"].strip(), "move": bool(payload.get("move"))}, timeout=3600.0)
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    return await _refresh(request, imr, payload["face"], _note(f"""{payload["name"]} is now kept in {got["path"]}""" + (f""" ({got["moved"]} moved along)""" if "moved" in got else "") + ". Programs that use it see it at their next start."))

async def _h_machine_form(request, payload, imr):
    p, name = AV.lib.get("provider", payload["pid"]), payload["name"]
    m, el = await PROV.machine(p, "GET", f"/modules/{name}"), f"""cv-mod-{payload["pid"]}-{name}"""
    if payload.get("close"): return imr.oob("", el)
    plan = m["plan"]
    d = next((x for x in plan["drivers"] if x["driver"] == (payload.get("driver") or plan["driver"])), None)
    if not d: return imr.oob(_note("No way to install it fits this machine: " + "; ".join(b["block"] for x in plan["drivers"] for b in x.get("blocks", [])), True), el)
    pick = BI.SettingField("driver", "How", "select", options=[(x["driver"], x["driver"] + (" - blocked here" if x.get("blocks") else "" if x.get("ok") else " - needs system packages")) for x in plan["drivers"]], hx_intent="corvid_machine_form", hx_target="none")
    opts = [BI.SettingField("opt_" + k, k, "select" if o.get("choices") else "text", options=[(str(ch), str(ch)) for ch in o.get("choices") or []] or None, hint=o.get("hint", "") + (" (has to be decided)" if k in d.get("decide", []) else "")) for k, o in d.get("options", {}).items()]
    ns = d.get("needs_system")
    sysnote = _note(f"""Needs {", ".join(ns["missing"])}: {ns["manager"] or "no package manager"} would install {" ".join(ns["packages"]) or "nothing known"}. """ + ("The machine's owner allows system packages." if ns["allowed"] else "Not allowed on that machine: install them there by hand, or allow system packages in its node.json."), not ns["allowed"]) if ns and ns.get("missing") else ""
    blocks = _note("Blocked here: " + "; ".join(b["block"] for b in d["blocks"]), True) if d.get("blocks") else ""
    values = {"driver": d["driver"], **{"opt_" + k: o.get("default", "") for k, o in d.get("options", {}).items()}}
    return imr.oob(f"""<form class="cv-form" id="cv-mf-{_esc(name)}" onsubmit="return false"><input type="hidden" name="pid" value="{_esc(p["id"])}"><input type="hidden" name="name" value="{_esc(name)}">{_group([pick, *opts]).render(values)}{sysnote}{blocks}<div class="row"><span class="grow"></span>{_btn("Install", "machine_install", pid=p["id"], name=name, include="#cv-mf-" + name)}{_btn("Cancel", "machine_form", pid=p["id"], name=name, close="1")}</div></form>""", el)

async def _install_task(p: dict, name: str, body: dict):
    rec = INSTALLS[(p["id"], name)]
    try:
        async for ln in PROV.machine_lines(p, f"/modules/{name}/install", body):
            rec["lines"].append(ln.get("line") or ln.get("status") or ln.get("error") or json.dumps(ln))
            rec["ok"] = rec["ok"] or ln.get("status") == "active"
    except PROV.ProviderError as e: rec["lines"].append(str(e))
    rec["done"] = True
    _OFFERS["t"] = 0

async def _h_machine_install(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin installs on a machine.", True), "cv-msg")
    p, name = AV.lib.get("provider", payload["pid"]), payload["name"]
    if not ((p["id"], name) in INSTALLS and not INSTALLS[(p["id"], name)]["done"]):
        INSTALLS[(p["id"], name)] = {"lines": [], "done": False, "ok": False}
        asyncio.create_task(_install_task(p, name, {"driver": payload.get("driver", ""), "options": {k[4:]: v for k, v in payload.items() if k.startswith("opt_") and v != ""}}))
    return imr.oob(_install_view(p["id"], name), f"cv-mod-{p['id']}-{name}")

async def _h_machine_act(request, payload, imr):
    if not _admin(request): return imr.oob(_note("Only a portal admin changes what a machine runs.", True), "cv-msg")
    p, name, verb = AV.lib.get("provider", payload["pid"]), payload["name"], payload["verb"]
    try: await (PROV.machine(p, "DELETE", f"/modules/{name}?confirm=1") if verb == "remove" else PROV.machine(p, "POST", f"/modules/{name}/{verb}"))
    except PROV.ProviderError as e: return imr.oob(_note(str(e), True), "cv-msg")
    _OFFERS["t"] = 0
    return await _refresh(request, imr, payload["face"], _note(f"{name}: {verb} done."))

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
    head = f"""<b>{_esc(t["title"])}</b>"""
    return f"""<div class="cv-chat">{_cm(c.face["id"]).shell(t["id"], t["messages"], user=c.request.state.user, header_html=head, is_working=_working(t), stop_intent=_stop_vals(t["id"]))}</div>"""

async def p_conversations(c) -> str:
    cur = _current(c.request, c.face, c.tab)["id"]
    rows = "".join(f"""<div class="list-row row{" cv-on" if t["id"] == cur else ""}"><span class="grow cv-link" {_act("open_tab", id=c.face["id"], cid=t["id"])}><span id="cv-talk-title-{t["id"]}">{_esc(t["title"])}</span>{_dim(_when(t["changed"]))}</span>{_btn("&#x2715;", "talk_del", "ui-btn cv-small", face=c.face["id"], cid=t["id"], confirm="Delete this conversation? Its runs stay.")}</div>""" for t in _talks(_user(c.request), c.face["id"]))
    return f"""<div class="row">{_btn("New conversation", "talk_new", face=c.face["id"])}</div>{rows}"""

async def p_roles(c) -> str:
    """Who fills the roles of this face's conversation pipeline in the conversation shown: what the profile's candidates give, unless one is pinned here."""
    conv, t = _conv_spec(c.face), _current(c.request, c.face, c.tab)
    pl, offers = AV.lib.get("pipeline", _pipe(conv, t)) if AV.lib.has("pipeline", _pipe(conv, t)) else None, await _offers()
    if not pl: return _no_pipelines()
    def usual(r):
        cs = _cands(r, c.face.get("profiles", []))
        return "not pinned: " + ("; ".join(x["asset"] + (" when " + x["when"] if x.get("when") else "") for x in cs) if cs else "nothing yet - set it in Settings")
    fields = _role_fields(pl.get("roles") or {}, offers, "")
    for f in fields: f.options, f.hx_intent, f.hx_target = [("", usual(f.name)), *f.options[1:]], "corvid_pin", "none"
    return f"""{_unreached(offers)}<form onsubmit="return false"><input type="hidden" name="cid" value="{_esc(t["id"])}"><input type="hidden" name="pipeline" value="{_esc(pl["id"])}">{_group(fields).render(_role_values(t["pins"]), name_prefix="r_")}</form>{_dim("A choice here is a pin: it holds for this conversation and nothing switches it.")}"""

async def p_params(c) -> str:
    """The inputs of the face's conversation pipeline as they hold for the conversation shown: its own value where one was set here, else the face's, else the pipeline's default. How much is shown is the conversation panel's "show" (see _levels)."""
    conv, t = _conv_spec(c.face), _current(c.request, c.face, c.tab)
    if not AV.lib.has("pipeline", _pipe(conv, t)): return _no_pipelines()
    pl, pick = AV.lib.get("pipeline", _pipe(conv, t)), _pipe_pick(c.face, conv, t)
    own, params = t.get("inputs", {}), {k: v for k, v in (pl.get("params") or {}).items() if k != "messages"}
    levels = _levels(conv.get("show", {}), params)
    if all(v == "fixed" for v in levels.values()): return pick + _dim("This face keeps its own values for everything.")
    here = "Set in this conversation: " + ", ".join(params[k].get("label") or k for k in own if k in params) if own else "Nothing is set in this conversation: these are the face's values."
    back = _btn("Back to the face's", "param_save", face=c.face["id"], cid=t["id"], clear="1") if own else ""
    to_face = _btn("Make these the face's", "param_save", face=c.face["id"], cid=t["id"], to_face="1", include="#cv-param-f", confirm="Use these values for every conversation of this face that sets none of its own?") if _admin(c.request) else ""
    values = {k: own.get(k, conv.get("inputs", {}).get(k, v.get("default"))) for k, v in params.items()}
    return f"""{pick}<form id="cv-param-f" onsubmit="return false">{_exposed(_param_fields({"params": params}), levels, values, "p_", "cv-param-f")}</form>{_dim(_esc(here))}<div class="row">{_btn("Use in this conversation", "param_save", face=c.face["id"], cid=t["id"], include="#cv-param-f")}{back}{to_face}</div>"""

async def _h_param_save(request, payload, imr):
    user, face = _user(request), AV.lib.get("face", payload["face"])
    t, conv = _talk(user, payload["cid"]), _conv_spec(face)
    params = {k: v for k, v in (AV.lib.get("pipeline", _pipe(conv, t)).get("params") or {}).items() if k != "messages"}
    vals = {k: v for k, v in _group(_param_fields({"params": params})).parse(payload, "p_").items() if k in _held(payload, "p_")}   # only what the form held: a fixed or hidden input keeps the face's value
    if payload.get("to_face"):
        if not _admin(request): return imr.oob(_note("Only a portal admin changes a face.", True), "cv-msg")
        conv["inputs"] = {**conv.get("inputs", {}), **vals}   # conv is the panel's own entry inside face, so the face now carries the values
        AV.lib.save("face", {k: v for k, v in face.items() if k not in ("modified", "by")}, by=user)
    _talk_save(user, {**t, "inputs": {} if payload.get("clear") or payload.get("to_face") else {k: v for k, v in vals.items() if v != conv.get("inputs", {}).get(k, params[k].get("default"))}})
    state = _tabs(await TM._load(request))
    return imr.oob(await _region(request, state, "right"), "cv-right")

def _pipe_pick(face: dict, conv: dict, t: dict) -> str:
    """The choice among what the face allows to answer in it (its conversation panel's "pipelines"), for the conversation shown; nothing when the face allows only its own."""
    ids = [conv["pipeline"]] + [i for i in conv.get("pipelines", []) if i != conv["pipeline"] and AV.lib.has("pipeline", i)]
    if len(ids) < 2: return ""
    f = BI.SettingField("pipeline", "What answers", "select", options=[(i, AV.lib.get("pipeline", i).get("name") or i) for i in ids if AV.lib.has("pipeline", i)], hint="For this conversation; its roles and options follow it.", hx_intent="corvid_talk_pipe", hx_target="none")
    return f"""<form onsubmit="return false"><input type="hidden" name="cid" value="{_esc(t["id"])}"><input type="hidden" name="face" value="{_esc(face["id"])}">{_group([f]).render({"pipeline": _pipe(conv, t)})}</form>"""

async def _h_talk_pipe(request, payload, imr):
    user = _user(request)
    t, conv = _talk(user, payload["cid"]), _conv_spec(AV.lib.get("face", payload["face"]))
    if payload.get("pipeline") in [conv["pipeline"], *conv.get("pipelines", [])]: _talk_save(user, {**t, "pipeline": payload["pipeline"], "inputs": {}, "pins": {}})   # inputs and pins belong to a pipeline: a new one starts from the face's
    return imr.oob(await _region(request, _tabs(await TM._load(request)), "right"), "cv-right")

async def _h_pin(request, payload, imr):
    t = _talk(_user(request), payload["cid"])
    t["pins"] = _picked(payload, AV.lib.get("pipeline", payload["pipeline"]).get("roles") or {}, "r_")
    _talk_save(_user(request), t)
    return imr

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
    t = _talk(user, cid)
    if not content or _working(t): return imr
    imr.raw(_take(user, t, _msg("user", content, user_name=user)))
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

async def _again(request, imr, t: dict, i: int):
    """The talk cut back to message i (a person's) and answered again from there. What is cut is not lost: it is kept in the conversation's file under "earlier"."""
    user, cid = _user(request), t["id"]
    if _working(t): return imr
    if t["messages"][i + 1:]: t.setdefault("earlier", []).append({"cut": time.time(), "messages": t["messages"][i + 1:]})
    t["messages"] = t["messages"][:i + 1]
    _talk_save(user, {**t, "changed": time.time()})
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
    return imr.oob(_msgs_html(t, user), "cm-msgs-" + t["id"])

async def _turn(user: str, t: dict, think: bool, may: list, spoken: bool = False):
    """One turn, for a talk whose last message is the person's: the face's pipeline runs with the talk so far and the inputs that hold for it (the face's, then the conversation's own), what its steps report is shown as it comes, and its answer (or why there is none) joins the talk with ways to open the run and to have it answered again."""
    face, cid, seen = AV.lib.get("face", t["face"]), t["id"], {"text": "", "thinking": "", "sent": 0.0}
    spec, cm = _conv_spec(face), _cm(t["face"])
    async def push(html_): await WS.send_personal_message(html_, user)
    def watch(step, ev):
        if ev.get("type") not in ("text", "thinking"): return
        seen[ev["type"]] += ev["text"]
        if time.time() - seen["sent"] > 0.12: seen["sent"] = time.time(); asyncio.ensure_future(push(cm.stream_content_html(cid, seen["text"], seen["thinking"][-2000:])))
    inputs = {**spec.get("inputs", {}), **t.get("inputs", {}), "messages": [{"role": m["role"], "content": m["content"]} for m in t["messages"] if m["role"] in ("user", "assistant")], **({"think": True} if think else {})}
    try: rid = await AV.start(_pipe(spec, t), inputs, owner=user, profiles=face.get("profiles", []), pins=t["pins"], watch=watch, may=may, case=face.get("case"))
    except (ValueError, KeyError) as e:
        t["messages"].append(note := _msg("system", f"No answer: {e}"))
        _talk_save(user, {**t, "changed": time.time()})
        return await push(cm.append_message_html(cid, note, viewer_name=user) + cm.working_hide_html(cid))
    _talk_save(user, {**t, "pending": rid, "changed": time.time()})
    state, r, mid = await AV.director.wait(rid), AV.director.runs[rid], uuid.uuid4().hex[:8]
    acts = [{"icon": "&#x2699;", "title": "The run behind this", "vals": {"type": "corvid_run_view", "id": rid, "lvl": 1, "branch": IM.branch_id}}, {"icon": "&#x21BA;", "title": "Answer again", "vals": {"type": "corvid_msg_retry", "id": mid, "lvl": 1, "branch": IM.branch_id}}]
    out = _msg("assistant", _shown(r.data.get(spec.get("answer", "text"))), persona_name=face.get("name") or face["id"], thinking=_shown(r.data.get(spec.get("thinking", ""))), model=(next(iter((r.meta.get("bound") or {}).values()), {}) or {}).get("asset", ""), actions=acts) if state == "done" else _msg("system", f"""No answer: the run is {state}. {r.meta.get("error", "")}""", actions=acts[:1])
    t = _talk(user, cid)
    t["messages"].append({**out, "id": mid})
    _talk_save(user, {**t, "pending": "", "changed": time.time()})
    await push(cm.append_message_html(cid, t["messages"][-1], viewer_name=user) + cm.stream_clear_html(cid) + cm.working_hide_html(cid) + (f"""<div id="cv-run-view" hx-swap-oob="innerHTML">{_run_view(r)}</div>""" if state != "done" else ""))
    if state == "done" and spec.get("speak") and (spoken or spec.get("speak_typed")): asyncio.create_task(MEDIA.say(user, t, mid, t["messages"][-1]["content"], may))   # an answer to spoken words is spoken; "speak_typed" speaks every answer

async def _h_stop(request, payload, imr):
    t = _talk(_user(request), payload["cid"])
    if _working(t): AV.director.stop(t["pending"], now=True)
    return imr

async def _h_msg_delete(request, payload, imr):
    for t in (json.loads(f.read_text()) for f in _talk_dir(_user(request)).glob("*.json")):
        if any(m["id"] == payload["id"] for m in t["messages"]): _talk_save(_user(request), {**t, "messages": [m for m in t["messages"] if m["id"] != payload["id"]]})
    return imr.oob("", f"""cm-msg-{payload["id"]}""", swap="delete")

PANELS = {"providers": p_providers, "bindings": p_bindings, "guide": p_guide, "limits": p_limits, "library": p_library, "runs": p_runs, "review": p_review, "conversation": p_conversation, "conversations": p_conversations, "roles": p_roles, "params": p_params, "assets": p_assets, "records": p_records, "graph": p_graph, "gallery": MEDIA.p_gallery, "machines": p_machines}

# --- The face shell: faces are tabs; the active one's panels fill the workspace and the two side toolbars ---

def _tabs(state: dict) -> dict:
    """The tab state brought in line with the faces that exist now: one tab per face, in the faces' order; what a tab remembers (the conversation it shows) is kept."""
    faces, old = _faces(), state.get("tabs", {})
    state["tabs"] = {f["id"]: {**old.get(f["id"], {}), "id": f["id"], "label": f.get("name") or f["id"], "icon": f.get("icon", ""), "order": n, "path": f["id"]} for n, f in enumerate(faces)}
    if state.get("active") not in state["tabs"]: state["active"] = faces[0]["id"]
    return state

async def _region(request, state: dict, region: str, msg: str = "") -> str:
    host, tab = AV.lib.get("face", state["active"]), state["tabs"][state["active"]]
    guest, gview = _guest(host, tab)
    face = guest if guest and region == "main" else host
    lay = _layout(face, {"view": gview} if face is guest else tab)
    vid = lay["id"] if face.get("views") else ""
    parts = [(spec, await PANELS[spec["panel"]](SimpleNamespace(request=request, face=face, spec=spec, key=f"{vid}:{region}.{n}", tab=tab, host=host["id"]))) for n, spec in enumerate(lay.get(region, []))]
    bar = ""
    if region == "main":
        hosted = [(host.get("name") or host["id"], not guest, {"embed": ""})] + [(f.get("name") or f["id"], bool(guest) and guest["id"] == f["id"], {"embed": f["id"] + ":"}) for f in _faces() if f["id"] in host.get("embeds", [])]
        views = [(v.get("name") or v["id"], v["id"] == vid, {"embed": f"""{guest["id"]}:{v["id"]}"""} if guest else {"view": v["id"]}) for v in face.get("views", [])]
        bar = (_tab_row("cv-host-tabs", host["id"], hosted) if host.get("embeds") else "") + (_tab_row("cv-view-tabs", host["id"], views) if views else "")
    if region == "main" and len(parts) == 1 and parts[0][0]["panel"] == "conversation": return bar + parts[0][1]   # a conversation alone fills the workspace
    body = "".join(_sec(spec.get("title", ""), html_) for spec, html_ in parts)
    top = f"""{_dim(_esc(face.get("about", "")))}<div id="cv-msg">{msg}</div>""" if region == "main" else ""
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

async def _refresh(request, imr, face_id: str, msg: str = ""):
    """Everything of the face redrawn, with a message at the top of the workspace."""
    state = _tabs(await TM._load(request))
    if _guest(AV.lib.get("face", state["active"]), state["tabs"][state["active"]])[0] is None or state["tabs"][state["active"]]["embed"].split(":")[0] != face_id: state["active"] = face_id   # a face shown inside another stays inside it
    for region, el in REGIONS.items(): imr.oob(await _region(request, state, region, msg), el)
    return imr

# --- Routes and init ---

@router.get("")
@router.get("/")
async def root(request: Request):
    state = _tabs(await TM._load(request))
    bars = {"top": UI.toolbar(side="top", content=await TM.tab_bar_fn(state, "cv-tab-bar", "corvid", 1, allow_new=False, closable=False), size="2.5rem", id="cv-top", nesting_level=1, start_open=True, resizable=False),
            "left": UI.toolbar(side="left", content=f"""<div id="cv-left">{await _region(request, state, "left")}</div>""", size="14rem", id="cv-leftbar", nesting_level=1, start_open=bool(_layout(AV.lib.get("face", state["active"]), state["tabs"][state["active"]]).get("left")), resizable=True),
            "right": UI.toolbar(side="right", content=f"""<div id="cv-right">{await _region(request, state, "right")}</div>""", size="19rem", id="cv-rightbar", nesting_level=1, start_open=True, resizable=True)}
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

@router.get("/media/{space}/{path:path}")
async def media_file(request: Request, space: str, path: str): return await MEDIA.media_file(request, space, path)

@router.get("/audio/{name}")
async def audio_file(request: Request, name: str): return await MEDIA.audio_file(request, name)

@router.get("/install", response_class=HTMLResponse)
async def install(pid: str, name: str): return HTMLResponse(_install_view(pid, name))

@router.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, face: str, key: str): return HTMLResponse(_run_list(request, AV.lib.get("face", face), key))

def init_module(env: dict):
    global UI, BI, WS, IM, TM, CM, AV, PROV, ROLES, DATA
    ENV.update(env)
    BI, WS, UI = env["tools"]["built_ins"], env["ws"], env["templates"].env.globals["UI"]
    AV, PROV, ROLES, DATA = env["tools"]["aviary"].AVIARY, env["tools"]["aviary"].providers, env["tools"]["aviary"].roles, Path(env["data_dir"])
    AV.lib.shipped.append(Path(__file__).parent / "library")
    IM = env["InterfaceManager"](nesting_level=1, db_path=f"""{env["data_dir"]}/im_registry.db""")
    TM = BI.TabManager(namespace="corvid", tab_bar_id="cv-tab-bar", content_id="cv-workspace", render_content_fn=_tab_content, intent_prefix="corvid", IM=IM, scope="user", allow_new=False, closable=False)
    for intent in ("open", "focus"): IM.scripts[f"corvid_{intent}_tab"] = [_with_sides(getattr(TM, f"_{intent}"))]
    CM_OPTS.update(namespace="corvid", view_style="bubble", stream_toggle=False, think_toggle=True, stop_enabled=True, pin_enabled=True, allow_edit=True, allow_delete=True, allow_copy=True, show_info=True, show_model=True, markdown_mode="standard", action_intent_prefix="corvid", branch_id=IM.branch_id, nesting_level=1, IM=IM, intent_name="corvid_say", on_submit=_h_say, placeholder="Say something… (Ctrl+Enter to send)")
    CM = BI.ChatManager(**CM_OPTS)
    IM.scripts.update({f"corvid_{k}": [fn] for k, fn in {"provider_form": _h_provider_form, "provider_check": _h_provider_check, "provider_save": _h_provider_save, "provider_del": _h_provider_del, "bindings_save": _h_bindings_save, "limits_save": _h_limits_save, "lib_open": _h_lib_open, "lib_save": _h_lib_save, "lib_remove": _h_lib_remove, "run_form": _h_run_form, "run_start": _h_run_start, "run_go": _h_run_go, "run_stop": _h_run_stop, "run_view": _h_run_view, "run_decide": _h_run_decide, "review": _h_review, "pin": _h_pin, "talk_new": _h_talk_new, "talk_del": _h_talk_del, "stop": _h_stop, "msg_delete": _h_msg_delete, "msg_retry": _h_msg_retry, "msg_edit_form": _h_msg_edit_form, "msg_edit_save": _h_msg_edit_save, "param_save": _h_param_save, "asset_form": _h_asset_form, "asset_save": _h_asset_save, "asset_del": _h_asset_del, "record_del": _h_record_del, "machine_form": _h_machine_form, "machine_install": _h_machine_install, "machine_act": _h_machine_act, "talk_pipe": _h_talk_pipe, "run_remove": _h_run_remove, "run_again": _h_run_again, "program": _h_program, "svc_log": _h_svc_log, "loc_form": _h_loc_form, "loc_save": _h_loc_save}.items()})
    MEDIA.init(_Live())
    print(f"""[corvid] ready | faces: {[f["id"] for f in _faces()]}""")

CSS = """
.cv{font-size:.8rem;padding:.3rem .5rem}.cv-sec{border:var(--border-thick) solid var(--border);border-radius:var(--radius);padding:.4rem .55rem;margin:.4rem 0;background:var(--surface)}
.cv-dim{font-size:.72rem;color:var(--text_muted)}.cv-key{min-width:7rem}.cv-on{border-color:var(--accent);background:var(--accent_dim)}.cv-small{font-size:.65rem}.cv-link{cursor:pointer}
.cv-ok{color:#00ffa2}.cv-mid{color:#ffcc00}.cv-bad{color:#ff6b6b}.cv-danger{color:#ff6b6b}#cv-workspace{height:100%;min-height:0;display:flex;flex-direction:column}#cv-workspace>.cv{flex:1;min-height:0;overflow-y:auto}.cv-chat{flex:1;min-height:0;height:100%}#cv-workspace>.tabs-container{flex:none}.cv-role{margin:.35rem 0;padding:.25rem 0;border-top:var(--border-thick) solid var(--border)}.cv-edit{width:100%}.cv-machine{border:var(--border-thick) solid var(--border);border-radius:var(--radius);padding:.3rem .5rem;margin:.35rem 0}.cv-machine>summary{cursor:pointer}.cv-gallery{height:72vh}.cv-graph{height:68vh;min-height:20rem;border:var(--border-thick) solid var(--border);border-radius:var(--radius)}
.cv-form{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-log{max-height:14rem;font-size:.7rem}.cv-json{width:100%;min-height:18rem;font-size:.72rem}
.cv-note{border-left:3px solid var(--accent);padding:.3rem .5rem;margin:.3rem 0}.cv-err{border-left:3px solid #ff6b6b;padding:.3rem .5rem;margin:.3rem 0}
.cv-tbl{border-collapse:collapse;font-size:.72rem;margin:.2rem 0 .5rem}.cv-tbl td,.cv-tbl th{border:var(--border-thick) solid var(--border);padding:.12rem .4rem;text-align:left;vertical-align:top;word-break:normal;overflow-wrap:anywhere}.cv-tbl td:first-child{white-space:nowrap}
"""
