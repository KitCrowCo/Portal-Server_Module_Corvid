"""shelf.py - Corvid's panels over what is kept and decided, beside corvid.py: providers (the machines and servers work is done on), bindings (who fills which role, in order, by case), guide (what is still missing before things work), limits (the owner's policy) and library (every kept object, edited in a form where its kind says what it has, else as JSON).
C is a live view of corvid.py's globals, set when Corvid starts."""
import re, json
from pathlib import Path

C = None

def _model_body_field():
    return C.BI.SettingField("model_body", "Request defaults per model", "json", advanced=True, hint='Fields sent with every request for a model on this connection, by pattern, first match used. Case does not matter; a pattern without * or ? matches anywhere in the model\'s name ("qwen3.5" matches "hf.co/unsloth/Qwen3.5-4B-GGUF:Q8_0"), one with them must match the whole name. What a request sets itself wins; options are merged. Example, to keep a model off this machine\'s GPU (Ollama: num_gpu is the number of layers on the GPU): {"qwen3.5": {"options": {"num_gpu": 0}}}')

def _wait_field(): return C.BI.SettingField("read_timeout_s", "Longest silence during work (s)", "number", advanced=True, hint=f"""For a server reached through a translator: how long it may say nothing (between pieces of an answer, or before a whole one) before the work fails with that said. Empty: {C.PROV.READ_IDLE_S:.0f} s. A Magpie node's own waits are its own.""")

def _provider_form(face_id: str, p: dict = None) -> str:
    key_hint = "A Magpie node: its own key, the admin key it showed when it was installed or another key made on that node. Another server: its API key, if it asks for one."
    stored = bool((p or {}).get("key"))
    key_box = f"""<label class="cv-field" style="display:flex;flex-direction:column;gap:.2rem"><span>API key{" (one is stored: it is kept unless the box below is ticked)" if stored else ""}</span><input type="text" name="key" value="" autocomplete="off" data-lpignore="true" style="-webkit-text-security:disc" placeholder="{"a new key, to replace the stored one" if stored else "the key"}"><span class="cv-dim">{key_hint}</span></label>""" + ("""<label class="row"><input type="checkbox" name="key_replace" value="1"> <span>Replace the stored key with what is written above (ticked with nothing written: the stored key is removed)</span></label>""" if stored else "")   # a plain field, not a password one: a browser fills password fields by itself, which would replace the key unasked
    speaks = C.BI.SettingField("speaks", "What it speaks", "select", options=[("", "the node contract (a Magpie node)")] + [(t["id"], (t.get("name") or t["id"]) + " - through a translator") for t in C.AV.lib.list("translator")], hint="A server that is not a Magpie node (an Ollama server on a work machine, ...) is used through a translator: chat and embeddings as that server offers them, nothing of its memory or programs.")
    g = C._group([C.BI.SettingField("name", "Name", "text", hint="What you call this machine."), C.BI.SettingField("url", "Address", "text", hint="host:port, for example 192.168.1.20:8790 (a Magpie node) or 192.168.1.30:11434 (an Ollama server)"), speaks, _model_body_field(), _wait_field()])
    return f"""<form class="cv-form" id="cv-prov-f" onsubmit="return false"><b>{"Change " + C._esc(p.get("name") or p["id"]) if p else "Add a connection"}</b>{g.render({"name": (p or {}).get("name", ""), "url": (p or {}).get("url", ""), "speaks": (p or {}).get("speaks", ""), "model_body": (p or {}).get("model_body", {}), "read_timeout_s": (p or {}).get("read_timeout_s", "")})}{key_box}<div class="row"><span class="grow"></span>{C._btn("Save", "provider_save", face=face_id, id=(p or {}).get("id", ""), include="#cv-prov-f")}{C._btn("Cancel", "provider_form", face=face_id, close="1")}</div></form>"""

def offer_status(o: dict) -> str:
    """A connection's state as last heard, with how old that is; while it is being asked it asks again by itself (GET /offer_status), so the rest of the page never waits on it."""
    caps = sorted({x for a in o["assets"] for x in a.get("capabilities", [])})
    poll = f"""hx-get="{C._P}/offer_status?pid={C.quote(o["p"]["id"])}" hx-trigger="every 2s" hx-swap="outerHTML" """ if o["asking"] else ""
    state, words = o["health"]
    said = """<span class="chip">being asked ...</span>""" if state == "asking" else f"""<span class="cv-ok">answers</span> <span class="cv-dim">{len(o["assets"])} assets | {C._esc(", ".join(caps))} | {C._esc(words)}</span>""" if state == "ok" else f"""<span class="chip {"cv-mid" if state == "missed" else "cv-bad"}" title="{C._esc(o["error"])}">{"may be down" if state == "missed" else "not reached"}</span> <span class="cv-dim">{C._esc(words)}{f" - {len(o['assets'])} assets as it listed them then" if state == "missed" else ""}</span>"""
    return f"""<span id="cv-ost-{C._elid(o["p"]["id"])}" {poll}>{said}{" " + C._dim("asking again ...") if o["asking"] and not o["pending"] else ""}</span>"""

async def p_providers(c) -> str:
    def row(o):
        p = o["p"]
        return f"""<div class="list-row"><div class="row"><b>{C._esc(p.get("name") or p["id"])}</b><span class="cv-dim mono">{C._esc(p["url"])}</span>{f'<span class="chip">speaks {C._esc(p["speaks"])}</span>' if p.get("speaks") else ""}<span class="grow">{offer_status(o)}</span>{C._btn("What it offers", "provider_check", id=p["id"])}{C._btn("Change", "provider_form", face=c.face["id"], id=p["id"])}{C._btn("Remove", "provider_del", "ui-btn cv-danger", face=c.face["id"], id=p["id"], confirm="Remove this provider? It is kept as an earlier version.")}</div>{C._note(o["error"], True) if o["error"] else ""}<div id="cv-prov-{C._esc(p["id"])}"></div></div>"""
    rows = "".join(row(o) for o in await C._offers())
    return f"""{C._dim("A connection is where a place that does work is (a Magpie node, an Ollama server) and the key to it: all Corvid keeps of it. What it holds and can do, it answers itself; its parts and how fast they are measured are under Asio > Resources.")}{rows or C._dim("none yet")}<div class="row"><span class="grow"></span>{C._btn("Add a connection", "provider_form", face=c.face["id"])}</div><div id="cv-prov-form"></div>"""

async def _h_provider_form(request, payload, imr): return imr.oob("" if payload.get("close") else _provider_form(payload["face"], C.AV.lib.get("provider", payload["id"]) if payload.get("id") else None), "cv-prov-form")

async def _h_provider_check(request, payload, imr):
    p = C.AV.lib.get("provider", payload["id"])
    try: d, assets = await C.PROV.ask(p, "describe", timeout=6.0), await C.PROV.assets(p, timeout=6.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), f"""cv-prov-{payload["id"]}""")
    rows = "".join(f"""<div class="row cv-dim"><span class="cv-key">{C._esc(cap)}</span><span class="mono">{C._esc(", ".join(a["name"] for a in assets if cap in a.get("capabilities", [])))}</span></div>""" for cap in sorted({x for a in assets for x in a.get("capabilities", [])}))
    said = " | ".join(k + ": " + C._shown(v)[:60] for k, v in d.items() if isinstance(v, (str, int, float)))
    waiting = ""
    if not p.get("speaks"):   # what its active programs can do but have nothing to do it with yet: a capability shows above only once something serves it
        try: mods, kinds = (await C.PROV.machine(p, "GET", "/modules", timeout=6.0))["modules"], (await C.PROV.manage(p, "GET"))["kinds"]
        except C.PROV.ProviderError as e: return imr.oob(f"""<div class="cv-form">{C._dim(C._esc(said))}{rows or C._dim("offers nothing yet")}{C._note(C.older(e, "list its programs and what can be made there"), True)}</div>""", f"""cv-prov-{payload["id"]}""")
        idle = sorted({c for m in mods if m["state"] == "active" for c in m.get("provides", [])} - {x for a in assets for x in a.get("capabilities", [])})
        where = lambda kind: ", ".join(f"""{f.get("name") or f["id"]}, {v.get("name") or v["id"]}""" for f in C._faces() for v in (f.get("views") or [f]) for sp in v.get("main", []) if sp["panel"] == "assets" and sp.get("kind") == kind)   # the faces whose manifests manage that kind
        make = "; ".join(k.get("label", n) + (" - made in " + where(n) if where(n) else "") for n, k in kinds.items())
        waiting = C._dim(C._esc(f"Active, with nothing to serve yet: {', '.join(idle)}." + (f" Things that can be made there: {make}." if make else ""))) if idle else ""
    return imr.oob(f"""<div class="cv-form">{C._dim(C._esc(said))}{rows or C._dim("offers nothing yet")}{waiting}</div>""", f"""cv-prov-{payload["id"]}""")

async def _h_provider_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes providers.", True), "cv-msg")
    old = C.AV.lib.get("provider", payload["id"]) if payload.get("id") else {}
    if not (payload.get("name", "").strip() and payload.get("url", "").strip()): return imr.oob(C._note("A provider needs a name and an address.", True), "cv-msg")
    key = (payload.get("key") or "").strip() if (payload.get("key_replace") or not old.get("key")) else old["key"]   # a stored key changes only when asked to (the box), so a changed address or name keeps it
    try: mb, wait = C._group([_model_body_field()]).parse(payload).get("model_body") or {}, C._group([_wait_field()]).parse(payload).get("read_timeout_s")
    except C.BI.SettingsError as e: return imr.oob(C._note(f"Request defaults per model: {e}", True), "cv-msg")
    if not isinstance(mb, dict) or not all(isinstance(v, dict) for v in mb.values()): return imr.oob(C._note('Request defaults per model: a JSON object of model name or pattern -> request fields, e.g. {"qwen3.5": {"options": {"num_gpu": 0}}}', True), "cv-msg")
    C.AV.lib.save("provider", {**{k: v for k, v in old.items() if k not in ("modified", "by", "speaks", "model_body", "read_timeout_s")}, "id": old.get("id") or C._slug(payload["name"]), "name": payload["name"].strip(), "url": C.PROV.address(payload["url"]), "key": key, **({"speaks": payload["speaks"]} if payload.get("speaks") else {}), **({"model_body": mb} if mb else {}), **({"read_timeout_s": float(wait)} if wait not in (None, "") else {})}, by=C._user(request))
    C._recheck()
    return await C._refresh(request, imr, payload["face"], C._note(f"""Saved {payload["name"]}."""))

async def _h_provider_del(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes providers.", True), "cv-msg")
    C.AV.lib.remove("provider", payload["id"])
    C.AV.seen.drop(payload["id"] + ":")
    return await C._refresh(request, imr, payload["face"], C._note("Removed."))

def _cand_value(choices: list, cand: dict) -> str:
    """The option that is this candidate: its provider and asset, or the asset alone when it names no provider."""
    if cand.get("pool"): return C._POOL + "|" + cand["pool"]
    return next((v for v, _ in choices if v and (v == cand.get("provider", "") + "|" + cand.get("asset", "") or (not cand.get("provider") and v.split("|", 1)[1] == cand.get("asset")))), "|" + cand["asset"] if cand.get("asset") else "")

_OPS = {"number": [(">", "is more than"), ("<", "is less than"), (">=", "is at least"), ("<=", "is at most")], "yes/no": [("yes", "yes"), ("no", "no")], "": [("==", "is"), ("!=", "is not")]}   # how a case is put together from a fact, by the fact's kind

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
    cur, nm = _cand_value(choices, cand), f"{C._esc(role)}_{i}"
    opts = "".join(f"""<option value="{C._esc(v)}" {"selected" if v == cur else ""}>{C._esc(label)}</option>""" for v, label in ([*choices, (cur, (cand.get("asset") or "pool " + cand.get("pool", "")) + "  -  not offered now")] if cur and cur not in [v for v, _ in choices] else choices))
    parts, fs = _case_parts(cand.get("when", "")), {k: _fact(x) for k, x in facts.items()}
    parts = None if parts and parts[0] and parts[0] not in fs else parts   # a condition over a fact the role does not list (a caller's case) is shown as written
    f0, op0, v0 = parts or ("", "", "")
    sel = lambda name, pairs, on: f"""<select name="{name}_{nm}" class="module-select">{C._options(pairs, on)}</select>"""
    ops = [x for k in {fs[f0]["kind"] if f0 in fs else ""} | {""} for x in _OPS.get(k, [])] if f0 else _OPS["number"] + _OPS["yes/no"] + _OPS[""]
    chooser = f"""<span class="cv-dim">used</span>{sel("cf", [("", "always")] + [(k, f["label"] or k) for k, f in fs.items()], f0)}{sel("co", ops, op0)}<input name="cv_{nm}" class="module-select" style="width:6rem" value="{C._esc(v0)}" placeholder="value">""" if fs else """<span class="cv-dim">used always, unless a condition is written out:</span>"""   # a role without facts has nothing to choose a case from
    written = f"""<input name="w_{nm}" class="module-select mono grow" value="{C._esc(cand.get("when", "") if parts is None else "")}" placeholder="or a condition written out (optional)" title="Any condition over the facts, as a Python expression, e.g. chars > 20000 and not images. When filled it is used instead of the choice before it.">"""
    return f"""<div class="row" style="flex-wrap:wrap"><span class="cv-dim">{i + 1}.</span><select name="r_{nm}" class="module-select mono">{opts}</select>{chooser}{written}<input name="n_{nm}" class="module-select" value="{C._esc(cand.get("note", ""))}" placeholder="note"></div>"""

async def p_bindings(c) -> str:
    roles, offers = C._all_roles(), await C._offers()
    if not roles: return C._no_pipelines()
    def one(r, need):
        choices, cands = C._choices(offers, need, "(none)"), C._cands(r, [c.spec["profile"]])
        facts = ", ".join(f"""{k} ({_fact(x)["label"]})""" if _fact(x)["label"] else k for k, x in (need.get("facts") or {}).items()) or "none"
        return f"""<div class="cv-role"><b>{C._esc(r)}</b> <span class="cv-dim">{C._esc(need.get("about", ""))} | needs: {C._esc(", ".join(need.get("needs") or []))} | facts for its cases: {C._esc(facts)}</span>{"".join(_cand_row(r, i, cand, choices, need.get("facts") or {}) for i, cand in enumerate([*cands, {}]))}</div>"""
    about = C._dim(f"""Nothing has to be set here. A role is only the name a pipeline gives one of its needs ("main" is whoever answers in a conversation). A role with no lines is placed when work starts, over everything that can do it: what fits as things stand, one already running first, then the faster as measured. Lines here (profile {C._esc(c.spec["profile"])}) are optional defaults that narrow that choice, in order of preference: the first whose case holds and which fits is used. "Used" says in which case a line applies: always, or when one of the role's facts (listed beside the role) compares with a value.""")
    none = "" if any(o["assets"] for o in offers) else C._note("No connection answers yet, so there is nothing to choose from. Add one under Machines, or see why it does not answer.", True)
    return f"""{about}{C._unreached(offers)}{none}<form id="cv-bind-f" onsubmit="return false">{"".join(one(r, need) for r, need in roles.items())}<div class="row"><span class="grow"></span>{C._btn("Save", "bindings_save", face=c.face["id"], profile=c.spec["profile"], include="#cv-bind-f")}</div></form>"""

async def _h_bindings_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes this profile.", True), "cv-msg")
    old, new = C._profile(payload["profile"]), {}
    for r in C._all_roles():
        before, i, new[r] = {x.get("asset") or x.get("pool"): x for x in C._cands(r, [payload["profile"]])}, 0, []
        while f"r_{r}_{i}" in payload:
            prov, _, asset = payload[f"r_{r}_{i}"].partition("|")
            if asset: new[r].append({**{k: v for k, v in before.get(asset, {}).items() if k not in ("provider", "asset", "pool", "when", "note")}, **({"pool": asset} if prov == C._POOL else {**({"provider": prov} if prov else {}), "asset": asset}), **({"when": w} if (w := payload.get(f"w_{r}_{i}", "").strip() or _case_made(payload.get(f"cf_{r}_{i}", ""), payload.get(f"co_{r}_{i}", ""), payload.get(f"cv_{r}_{i}", ""))) else {}), **({"note": payload[f"n_{r}_{i}"].strip()} if payload.get(f"n_{r}_{i}", "").strip() else {})})   # what the line does not show (request defaults, streams) stays with its asset
            i += 1
    C.AV.lib.save("bindings", {**{k: v for k, v in old.items() if k not in ("modified", "by")}, "roles": {r: cs for r, cs in new.items() if cs}}, by=C._user(request))
    return await C._refresh(request, imr, payload["face"], C._note("Saved. Work started from now on uses it; the version before is kept."))

_WHO = [("nobody", "nobody"), ("admins", "portal admins only"), ("everyone", "everyone who can open Corvid")]

async def p_limits(c) -> str:
    """The owner's decisions on what runs may do beyond the default (library object policy "aviary")."""
    pol = C.AV.policy()
    fields = [C.BI.SettingField(k, label, "select", options=_WHO + ([(json.dumps(pol[k]), "these people: " + ", ".join(pol[k]))] if isinstance(pol.get(k), list) else []), hint=hint) for k, (label, hint) in C._LIMITS.items()]
    return f"""{C._dim("Nothing outside this portal sets these. A list of names instead of one of the choices can be written in the policy object itself (Library, policy).")}<form id="cv-lim-f" onsubmit="return false">{C._group(fields).render({k: json.dumps(pol[k]) if isinstance(pol.get(k), list) else pol.get(k, "nobody") for k in C._LIMITS})}<div class="row"><span class="grow"></span>{C._btn("Save", "limits_save", face=c.face["id"], include="#cv-lim-f")}</div></form>"""

async def _h_limits_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin sets the limits.", True), "cv-msg")
    pol = C.AV.policy()
    C.AV.lib.save("policy", {**{k: v for k, v in pol.items() if k not in ("modified", "by", "id")}, "id": "aviary", **{k: json.loads(payload[k]) if payload[k].startswith("[") else payload[k] for k in C._LIMITS if payload.get(k)}}, by=C._user(request))
    return await C._refresh(request, imr, payload["face"], C._note("Saved. It holds for runs started from now on."))

async def p_guide(c) -> str:
    """What is still missing before anything can run, in the order to do it."""
    offers, roles = await C._offers(), C._all_roles()
    up = [o for o in offers if not o["error"]]
    open_roles = [r for r, need in roles.items() if not any(all(x in a.get("capabilities", []) for x in need.get("needs") or []) for o in up for a in o["assets"])]   # needs nothing answering can do: placement has nothing to choose from
    steps = [(bool(roles), "Aviary has its pipelines", "" if roles else "none found - see the note under Needs."),
             (bool(up), "A connection answers", f"{len(up)} of {len(offers)} answer" if offers else "add one under Machines."),
             (bool(roles) and not [r for r in open_roles if "chat" in (roles[r].get("needs") or [])], "Something answers in chat; other needs are filled or knowingly left", "; ".join(f"""{r} ({", ".join(roles[r].get("needs") or [])}): only the pipelines that use it wait until a machine offers it""" for r in open_roles) if open_roles else ""),   # a need nothing offers (research on a closed network) is a choice of what is installed, not a fault: only a missing chat model stops everything
             (False, "Try it", "open the Tessa tab and say something; \"the run behind this\" on an answer shows what was done")]
    rows = "".join(f"""<div class="row"><span class="{"cv-ok" if ok else "cv-dim"}">{"&#x2713;" if ok else "&#x25CB;"}</span><span class="grow">{C._esc(label)}{C._dim(C._esc(hint))}</span></div>""" for ok, label, hint in steps)
    return rows

# --- Help: the portal guide (an Aviary library context, so a person reads it here and a model can be given it) ---
GUIDE_ID = "portal_guide"

def _sections(text: str) -> list:
    """The guide cut at its second-level headings: [(heading, markdown)], the part before the first heading as "About this guide"."""
    parts = re.split(r"(?m)^## ", text)
    return [("About this guide", parts[0])] + [(p.split("\n", 1)[0].strip(), p.split("\n", 1)[1] if "\n" in p else "") for p in parts[1:]]

def _section(i: int, head: str, body: str, open_at: str) -> str: return f"""<details class="cv-guide-sec" id="cv-guide-{i}"{" open" if open_at and open_at.lower() in head.lower() else ""}><summary><b>{C._esc(head)}</b></summary>{C.BI.md_plus_transpiler(body)}</details>"""

async def _h_help(request, payload, imr):
    """The portal guide in a window over the page: every section folded, the one about this face open, a search that keeps the sections holding all the words typed. The guide is the library context portal_guide - a copy saved in the library (Settings, Library) is what shows, so it can be added to or corrected."""
    if not C.AV.lib.has("context", GUIDE_ID): return imr.oob(C._note("The guide (library context portal_guide) is not in the library.", True), "cv-msg")
    parts, at = _sections(C.AV.lib.get("context", GUIDE_ID)["text"]), str(payload.get("open") or "")
    at = at if at and any(at.lower() in h.lower() for h, _ in parts) else parts[1][0] if len(parts) > 1 else ""   # the section about this face, else the overview
    secs = "".join(_section(i, h, b, at) for i, (h, b) in enumerate(parts))
    find = """<input type="search" class="grow" placeholder="find a word (every word typed must be in a section)" oninput="var w=this.value.toLowerCase().split(/\\s+/).filter(Boolean);document.querySelectorAll('.cv-guide-sec').forEach(function(d){var t=d.textContent.toLowerCase(),hit=w.every(function(x){return t.indexOf(x)>=0});d.style.display=hit?'':'none';d.open=w.length>0&&hit})">"""
    return imr.oob(C.UI.modal("cv-help", "Guide: what the words mean here, and how the parts fit", f"""<div class="row">{find}</div>{C._dim("The same text can be given to a model as a context (Contexts: Portal guide).")}{secs}""", width="95%", max_width="60rem"), "cv-help-slot")

def _kind(kind: str) -> dict: return C.AV.lib.get("kind", kind) if C.AV.lib.has("kind", kind) else {}   # what a kind is for and which of its parts a form shows (library kind "kind"); a kind without one is edited as JSON
def _people() -> list:
    """The portal's user names."""
    from core_files.database import SessionLocal
    from core_files.models import User
    with SessionLocal() as db: return sorted(u.username for u in db.query(User).all())

def _kind_fields(k: dict, obj: dict = None) -> list:
    """A kind's parts as form fields. "pick_from": [[value, label]] is a fixed choice; "pick": <library kind> a choice among that kind's objects (with "many": a tick list of them); "pick_assets": a tick list of what the providers hold ("<provider>|<asset>"); "pick_users": a tick list of the portal's people ("everyone": true adds "*", everyone); "pick_user": one of them, "empty" naming what none means. A tick list also shows what the object already holds that is not among today's choices (a machine that is off, a pattern), so saving the form does not drop it."""
    held = lambda n, have: [(v, f"{v}  -  as written") for v in (obj or {}).get(n) or [] if v not in have]
    def assets(n):
        have = [(o["p"]["id"] + "|" + a["name"], a["name"], "", o["p"].get("name") or o["p"]["id"]) for o in C._offers_now() for a in o["assets"]]
        return have + [(v, label, "", "kept") for v, label in held(n, [x[0] for x in have])]
    def people(n):
        us = _people()
        return [(u, u) for u in us] + held(n, us)
    def folders(sid):   # the folders at the top of a library space, for a field that names one (picked, or a new name typed)
        root = Path(C.AV.lib.get("space", sid)["root"]) if C.AV.lib.has("space", sid) else None
        return [(d.name, d.name) for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith((".", "_"))] if root and root.is_dir() else []
    choice = lambda n, f: [tuple(o) for o in f["pick_from"]] if f.get("pick_from") else (C._kind_options(f["pick"]) if f.get("many") else [("", "(none)")] + [(o["id"], o.get("name") or o["id"]) for o in C.AV.lib.list(f["pick"])]) if f.get("pick") else assets(n) if f.get("pick_assets") else [*([("*", "everyone")] if f.get("everyone") else []), *people(n)] if f.get("pick_users") else [("", f.get("empty") or "(nobody)")] + people(n) if f.get("pick_user") else folders(f["pick_dir"]) if f.get("pick_dir") else None
    kind = lambda f: "checklist" if f.get("pick") and f.get("many") else "select" if f.get("pick_from") or f.get("pick") or f.get("pick_user") else "checklist" if f.get("pick_assets") or f.get("pick_users") else "combo" if f.get("pick_dir") else C._FIELD.get(f.get("type"), "text")
    return [C.BI.SettingField(n, f.get("label") or n, kind(f), default=f.get("default"), options=choice(n, f), hint=f.get("hint", ""), step=1 if f.get("type") == "integer" else None, section=f.get("section", ""), advanced=bool(f.get("advanced"))) for n, f in (k.get("fields") or {}).items()]   # "section": fields drawn folded together under that name; "advanced": under Advanced; "pick_user": one of the portal's people; "pick_dir": <space id> - a folder of that space, picked or a new name typed

async def p_library(c) -> str:
    def info(kind, o): return " | ".join(x for x in (o["id"], C.AV.status(kind, o["id"]), f"""{len(C.AV.lib.versions(kind, o["id"]))} earlier versions""" if C.AV.lib.versions(kind, o["id"]) else "", str(o.get("objective") or o.get("about") or "")[:120]) if x)
    def rows(kind): return "".join(f"""<div class="list-row row"><b>{C._esc(o.get("name") or o["id"])}</b><span class="chip">{C.AV.lib.origin(kind, o["id"])}</span><span class="cv-dim grow">{C._esc(info(kind, o))}</span>{C._btn("Open", "lib_open", face=c.face["id"], kind=kind, id=o["id"])}</div>""" for o in C.AV.lib.list(kind))
    kinds = "".join(f"""<details{" open" if len(c.spec["kinds"]) <= 3 else ""}><summary class="cv-dim"><b>{C._esc(_kind(k).get("name") or k)}</b> ({len(C.AV.lib.list(k))})</summary>{C._dim(C._esc(_kind(k).get("about", "")))}{rows(k) or C._dim("none yet")}<div class="row"><span class="grow"></span>{C._btn("New", "lib_open", face=c.face["id"], kind=k, id="")}</div></details>""" for k in c.spec["kinds"])
    return f"""{C._dim("What Corvid and Aviary keep, one object each. Shipped objects come with the software and are never changed; saving one makes it yours, and removing yours brings the shipped one back. Every save keeps the version before it.")}{kinds}<div id="cv-lib-edit"></div>"""

async def _h_lib_open(request, payload, imr):
    """One library object to change: as a form where its kind says which parts it has (the rest of it as JSON under Advanced), else, or when asked ("raw"), as the JSON it is."""
    kind, oid = payload["kind"], payload["id"]
    if payload.get("close"): return imr.oob("", "cv-lib-edit")
    obj, k = {k: v for k, v in C.AV.lib.get(kind, oid).items() if k not in ("modified", "by")} if oid else {"id": "", "name": ""}, _kind(kind)
    await C._offers()   # a kind may offer what the providers hold as choices
    as_form = bool(k.get("fields")) and not payload.get("raw")
    back = C._btn("Back to shipped", "lib_remove", face=payload["face"], kind=kind, id=oid, confirm="Remove your version? It is kept as an earlier version.") if oid and C.AV.lib.origin(kind, oid) == "mine" else ""
    turn = C._btn("As a form" if payload.get("raw") else "As JSON", "lib_open", face=payload["face"], kind=kind, id=oid, raw="" if payload.get("raw") else "1") if k.get("fields") else ""
    head = f"""<div class="row"><b>{C._esc(k.get("name") or kind)}</b><span class="mono grow">{C._esc(oid or "new")}</span>{C._btn("Save as mine", "lib_save", face=payload["face"], kind=kind, include="#cv-lib-f")}{turn}{back}{C._btn("Close", "lib_open", face=payload["face"], kind=kind, id=oid, close="1")}</div>"""
    if not as_form: return imr.oob(f"""<form class="cv-form" id="cv-lib-f" onsubmit="return false">{head}<textarea name="json" class="module-select mono cv-json" spellcheck="false">{C._esc(json.dumps(obj, indent=1, ensure_ascii=False))}</textarea></form>""", "cv-lib-edit")
    rest = C.BI.SettingField("_rest", "Its other parts, as JSON", "json", default={}, hint="Whatever this object holds beyond the fields here. Kept as it is unless changed.", advanced=True)
    new_id = "" if oid else """<div class="row"><input name="new_id" class="module-select mono grow" placeholder="its id (optional: left empty, made from the name)"></div>"""
    return imr.oob(f"""<form class="cv-form cv-lib-form" id="cv-lib-f" onsubmit="return false">{head}<input type="hidden" name="id" value="{C._esc(oid)}"><input type="hidden" name="as_form" value="1">{new_id}{C._group([*_kind_fields(k, obj), rest]).render({**{n: v for n, v in obj.items() if n in k["fields"] and v is not None}, "_rest": {n: v for n, v in obj.items() if n not in k["fields"] and n != "id"}}, name_prefix="o_")}</form>""", "cv-lib-edit")

async def _h_lib_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes the library.", True), "cv-msg")
    try:
        if payload.get("as_form"):
            fields, before = _kind_fields(_kind(payload["kind"])), C.AV.lib.get(payload["kind"], payload["id"]) if payload.get("id") else {}
            got = {n: v for n, v in C._group([*fields, C.BI.SettingField("_rest", "", "json", default={})]).parse(payload, "o_").items() if n == "_rest" or n in before or v not in ("", None, [], {})}   # a part the object did not have and the form left empty is not added to it
            obj = {**got.pop("_rest"), **got, "id": payload.get("id") or payload.get("new_id") or got.get("name", "")}
        else: obj = json.loads(payload["json"])
    except (ValueError, C.BI.SettingsError) as e: return imr.oob(C._note(f"Not saved, a part of it could not be read: {e}", True), "cv-msg")
    if not C._slug(str(obj.get("id", ""))): return imr.oob(C._note("Not saved: it needs a name or an id.", True), "cv-msg")
    obj = {**obj, "id": C._slug(str(obj["id"]))}
    if not payload.get("id") and payload.get("as_form") and C.AV.lib.has(payload["kind"], obj["id"]): return imr.oob(C._note(f"""Not saved: there is already a {payload["kind"]} with the id {obj["id"]}. Open that one to change it, or give this one another id."""), "cv-msg")
    if _kind(payload["kind"]).get("owned"): obj = {**obj, "owner": C._user(request), "may": C._may(request)}   # a kind that acts by itself (a schedule) acts as whoever saved it last, with the limits that person has
    C.AV.lib.save(payload["kind"], obj, by=C._user(request))
    C._recheck()
    return await C._refresh(request, imr, payload["face"], C._note(f"""Saved {payload["kind"]} {obj["id"]}."""))

async def _h_lib_remove(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes the library.", True), "cv-msg")
    C.AV.lib.remove(payload["kind"], payload["id"])
    return await C._refresh(request, imr, payload["face"], C._note("Removed yours."))

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_" + fn.__name__[3:]: [fn] for fn in (_h_bindings_save, _h_help, _h_lib_open, _h_lib_remove, _h_lib_save, _h_limits_save, _h_provider_check, _h_provider_del, _h_provider_form, _h_provider_save)})
