"""spread_view.py - resource pools (D-12 in claude/data/decisions.md, I-78 in claude/data/issues.md): one name, pool~<name>, standing for a set of models across the machines, with a work class and tags.
A pool is one portal object, the library kind "pool" (Aviary access.py), with "serve": true. The portal is where it is defined; every Magpie machine is sent its own copy (node setting pools.<name>, Magpie core/pools.py), written relative to that machine: its own members as its own models, the others through model sources to their machines. So a program on any machine (a knowledge server) is pointed at pool~<name> on its own Magpie, and that Magpie sends each request to whichever member has the fewest requests per slot - the program never learns which machine did the work.
Members are picked, never typed: a model on every machine that holds it ("*|<model>", which takes in a machine that gets the model later, once the pool is sent again), or on chosen machines. Requests at once per member are left empty unless set: the machine then serves the model with what it lists for it (its program's parallel slots); a number set here is what that machine's program serves the model with.
The same pool fills roles in pipelines too ({"pool": id}, Aviary roles.py), so one definition serves both.
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import re, asyncio

C = None
CLASSES = [("background", "background work"), ("normal", "normal work"), ("interactive", "interactive (goes first)")]
CLASS_HINT = "Background: runs while nothing else waits for the same program, within each machine's share (knowledge ingestion, sweeps). Normal: in turn. Interactive: goes first."
NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_spread_save": [_h_save], "corvid_spread_share": [_h_share], "corvid_spread_del": [_h_del], "corvid_spread_edit": [_h_edit], "corvid_spread_send": [_h_send], "corvid_spread_drop": [_h_drop], "corvid_spread_machine": [_h_machine]})

# --- Pools and what they hold now ---

def _served() -> list: return [p for p in C.AV.lib.list("pool") if p.get("serve")]
def _version(pool: dict) -> str: return str(round(pool.get("modified") or 0))
def _nodes(offers: list) -> list: return [o for o in offers if not o["p"].get("speaks") and not o["error"] and not o["down"]]   # Magpie machines answering: they hold a copy of each pool
def _hosts(offers: list) -> list: return [o for o in offers if not o["error"] and not o["down"]]   # machines whose models can be members (an Ollama too, reached through each Magpie's model sources)
def _src(p: dict) -> str: return re.sub(r"[^A-Za-z0-9_-]", "_", p["id"])[:40]   # the name a machine gives its model source to another machine of this portal (the same as assets._from_elsewhere)
def _mid(s: str) -> str: return re.sub(r"[^A-Za-z0-9]", "_", s)
def _models(o: dict) -> list: return [a for a in o["assets"] if {"chat", "embed"} & set(a.get("capabilities", [])) and "/" not in a["name"] and not a["name"].startswith("pool~")]
def _who(p: dict) -> str: return p.get("name") or p["id"]

def _members(pool: dict, offers: list) -> list:
    """(machine offer, asset) for every member the pool holds as the machines answer now: a "*|<model>" entry is that model on each machine holding it."""
    return [(o, a) for o in _hosts(offers) for a in _models(o) if C.AV.access.holds(pool, o["p"]["id"], a["name"])]

def _copy(pool: dict, node: dict, held: list) -> dict:
    """The pool as one machine keeps it: its own members as its models, every other member through the model source to that member's machine. A machine in the pool's "off" list keeps its members, switched off: no work is sent to them until it is switched on again."""
    cand = lambda o, a: {"source": "" if o["p"]["id"] == node["id"] else _src(o["p"]), "model": a["name"], "enabled": o["p"]["id"] not in (pool.get("off") or []), **({"slots": n} if (n := int((pool.get("slots") or {}).get(f"""{o["p"]["id"]}|{a["name"]}""") or 0)) else {})}
    return {"class": pool.get("class") or "background", "portal": _version(pool), "tags": pool.get("tags") or [], "candidates": [cand(o, a) for o, a in held]}

async def _send_one(pool: dict, o: dict, held: list) -> str:
    """Writes the pool to one machine (the model sources it needs first). Answers "" when written, else why not."""
    try:
        for q in {x["p"]["id"]: x["p"] for x, _ in held if x["p"]["id"] != o["p"]["id"]}.values(): await C.PROV.manage(o["p"], "PUT", "source", _src(q), {"url": q["url"], "key": q.get("key", ""), "enabled": True})
        await C.PROV.machine(o["p"], "PATCH", "/settings", {"path": f"""pools.{pool["id"]}""", "value": _copy(pool, o["p"], held), "source": "the portal's pools"}, timeout=30.0)
        return ""
    except C.PROV.ProviderError as e: return C.older(e, "keep pools")

async def _send(pool: dict) -> str:
    """The pool to every Magpie machine answering now, as one line saying where it went and where not."""
    offers = await C._offers()
    held, nodes = _members(pool, offers), _nodes(offers)
    if not held: return f"""pool~{pool["id"]} holds nothing any machine offers now: sent nowhere."""
    errs = await asyncio.gather(*(_send_one(pool, o, held) for o in nodes))
    for o in nodes: C._recheck(o["p"]["id"])
    ok, bad, away = [_who(o["p"]) for o, e in zip(nodes, errs) if not e], [f"""{_who(o["p"])}: {e}""" for o, e in zip(nodes, errs) if e], [_who(o["p"]) for o in offers if not o["p"].get("speaks") and o not in nodes]
    return f"""pool~{pool["id"]}: {len(held)} member(s) on {len({o["p"]["id"] for o, _ in held})} machine(s). Sent to {", ".join(ok) or "no machine"}.""" + (f""" Not written: {"; ".join(bad)}.""" if bad else "") + (f""" Not answering now (press Send again once they are): {", ".join(away)}.""" if away else "")

# --- One machine as it stands (drawn on its own, GET /spread_row: the page never waits on a machine) ---

def _state(n: str, v: dict) -> tuple:
    """How a pool kept on a machine stands against the portal's pools: (words, is it current)."""
    pool = next((p for p in _served() if p["id"] == n), None)
    if not pool: return ("made on this machine only, not one of the portal's pools", False)
    return ("current", True) if v.get("portal") == _version(pool) else ("an older copy: Send again", False)

def _member_row(c: dict) -> str: return f"""<div class="row cv-dim"><span class="mono grow">{C._esc(c["model"])}</span><span>{c["here"]} now, takes {c["slots"]}{" (as that machine serves it)" if c.get("auto") else ""}{"" if c["enabled"] else " (off)"}</span></div>"""

def _held_row(face_id: str, p: dict, n: str, v: dict) -> str:
    said, ok = _state(n, v)
    drop = "" if ok else C._btn("Remove from this machine", "spread_drop", "ui-btn cv-small cv-danger", face=face_id, pid=p["id"], name=n, confirm=f"""Remove pool~{n} from {_who(p)}? Work naming it there then fails until it is sent again.""")
    return f"""<details class="list-row"><summary class="row"><b class="mono">pool~{C._esc(n)}</b><span class="chip">{C._esc(v["class"])}</span><span class="{"cv-ok" if ok else "cv-mid"} grow">{C._esc(said)}</span><span class="cv-dim">a program there is told {v["advertised"]} at once</span>{drop}</summary>{"".join(_member_row(c) for c in v["candidates"])}</details>"""

async def row(face_id: str, pid: str) -> str: return f"""<div {C._tags(f"machine:{pid}", "pools", get=f"{C._P}/spread_row?face={C.quote(face_id)}&amp;pid={C.quote(pid)}")}>{await _row(face_id, pid)}</div>"""   # asks for itself again when the machine or the pools change (corvid _changed)

async def _row(face_id: str, pid: str) -> str:
    p = C.AV.lib.get("provider", pid)
    try: st, knobs = await C.PROV.machine(p, "GET", "/control/status", timeout=6.0), (await C.PROV.machine(p, "GET", "/knobs", timeout=6.0))["knobs"]
    except C.PROV.ProviderError as e: return f"""<div class="list-row"><b>{C._esc(_who(p))}</b>{C._note(C.older(e, "say how its work is spread"), True)}</div>"""
    if "pools" not in st: return f"""<div class="list-row"><b>{C._esc(_who(p))}</b>{C._dim("Its Magpie is older than pools: update it (Settings, Machines, Update).")}</div>"""
    share = next((k["current"] for k in knobs if k["key"] == "scheduler.background_share"), 1.0)
    form = f"""<form id="cv-share-{pid}" class="row" onsubmit="return false"><span class="cv-dim">background work may use</span><input name="share" type="number" min="0" max="1" step="0.05" value="{share}" class="module-select" style="width:5em"><span class="cv-dim grow">of each program's slots (1 all idle capacity, 0 paused)</span>{C._btn("Set", "spread_share", "ui-btn cv-small", face=face_id, pid=pid, include=f"#cv-share-{pid}")}</form>"""
    paused = [x["id"] for x in _served() if pid in (x.get("off") or [])]
    pause = C._btn("Take pool work again" if paused else "Pause pool work here", "spread_machine", "ui-btn cv-small", face=face_id, pid=pid, off="" if paused else "1", title=f"""Switched off in: {", ".join(paused)}. Press to switch it on in every pool again.""" if paused else "Switch this machine off in every pool: its members stay, no pool work is sent to it (a machine overheating, or wanted for something else). Its own programs still answer requests made to it directly.")
    return f"""<div class="list-row"><div class="row"><b class="grow">{C._esc(_who(p))}</b>{pause}</div>{form}{"".join(_held_row(face_id, p, n, v) for n, v in st["pools"].items()) or C._dim("Holds no pool yet.")}</div>"""

# --- The form: make or change a pool ---

def _model_rows(offers: list, pool: dict) -> str:
    """One row per model name, ticked for every machine holding it or opened for chosen machines; each machine with its requests at once (empty: as that machine serves it)."""
    by = {}
    for o in _hosts(offers):
        for a in _models(o): by.setdefault(a["name"], []).append((o, a))
    members, slots = pool.get("members") or [], pool.get("slots") or {}
    def machine(name, o, a):
        k, listed = f"""{o["p"]["id"]}|{name}""", a.get("slots") or 1
        return f"""<span class="row chip" style="cursor:default"><label><input type="checkbox" name="m_{_mid(k)}" value="1" {"checked" if k in members else ""}> {C._esc(_who(o["p"]))}</label><input name="s_{_mid(k)}" type="number" min="1" value="{slots.get(k, "")}" placeholder="{listed}" class="module-select" style="width:3.5em" title="Requests it takes at once. Empty: as that machine serves this model now ({listed}); a number here is what its program serves the model with."></span>"""
    def one(name, rows):
        caps, every = ", ".join(sorted({x for _, a in rows for x in a.get("capabilities", []) if x in ("chat", "embed")})), f"*|{name}" in members
        on = every or any(f"""{o["p"]["id"]}|{name}""" in members for o, _ in rows)
        return f"""<details class="list-row cv-pool-model" data-name="{C._esc(name.lower())}" data-caps="{caps}" {"open" if on and not every else ""}><summary class="row"><label class="row" title="Every machine holding this model, a machine that gets it later included (once the pool is sent again)"><input type="checkbox" name="a_{_mid(name)}" value="1" {"checked" if every else ""}> all</label><span class="mono grow">{C._esc(name)}</span><span class="cv-dim">{caps} - {len(rows)} machine(s)</span></summary><div class="row">{C._dim("or only:")}{"".join(machine(name, o, a) for o, a in rows)}</div></details>"""
    return "".join(one(n, by[n]) for n in sorted(by, key=str.lower))

_FILTER_JS = """<script>window.cvPoolFilter = window.cvPoolFilter || function(f){var t=(f.querySelector('[name=find]').value||'').toLowerCase(), c=f.querySelector('[name=cap]').value, on=f.querySelector('[name=ticked]').checked; f.querySelectorAll('.cv-pool-model').forEach(function(d){var tick=!!d.querySelector('input[type=checkbox]:checked'); d.style.display=(d.dataset.name.indexOf(t)>=0 && (!c || d.dataset.caps.indexOf(c)>=0) && (!on || tick)) ? '' : 'none';});};</script>"""

def _form(face_id: str, offers: list, pool: dict = None) -> str:
    pool = pool or {}
    klass = "".join(f"""<option value="{v}" {"selected" if v == (pool.get("class") or "background") else ""}>{C._esc(l)}</option>""" for v, l in CLASSES)
    name = f"""<input type="hidden" name="orig" value="{C._esc(pool["id"])}"><b class="mono">pool~{C._esc(pool["id"])}</b><input type="hidden" name="name" value="{C._esc(pool["id"])}">""" if pool.get("id") else """<span class="cv-dim">pool~</span><input name="name" class="module-select" placeholder="ingest" required title="Letters, digits, _ and -: work names it pool~<name>">"""
    rows = _model_rows(offers, pool)
    find = """<div class="row" oninput="cvPoolFilter(this.closest('form'))" onchange="cvPoolFilter(this.closest('form'))"><input name="find" class="module-select grow" placeholder="find a model"><select name="cap" class="module-select"><option value="">chat and embedding</option><option value="chat">chat</option><option value="embed">embedding</option></select><label class="cv-dim"><input type="checkbox" name="ticked" value="1"> ticked only</label></div>"""
    close = C._btn("New pool instead", "spread_edit", "ui-btn cv-small", face=face_id) if pool.get("id") else ""
    return f"""<form id="cv-spread-f" class="cv-form" onsubmit="return false"><div class="row"><b class="grow">{"Change a pool" if pool.get("id") else "Make a pool"}</b>{close}</div>
               <div class="row">{name}<select name="klass" class="module-select" title="{CLASS_HINT}">{klass}</select></div>
               <div class="row"><input name="tags" class="module-select grow" value="{C._esc(", ".join(pool.get("tags") or []))}" placeholder="tags, comma separated (optional): what it is for, to find and filter it"></div>
               <div class="row"><input name="about" class="module-select grow" value="{C._esc(pool.get("about", ""))}" placeholder="what it is for (optional)"></div>
               {C._dim("Members: tick all for a model on every machine holding it, or open a model and tick machines. Requests at once: empty leaves it to each machine (the grey number is what it serves the model with now).")}{find}<div class="scroll-pane" style="max-height:50vh">{rows or C._dim("No machine offers a chat or embedding model yet.")}</div>
               <div class="row"><span class="grow"></span>{C._btn("Save and send to every machine", "spread_save", face=face_id, include="#cv-spread-f")}</div></form>{_FILTER_JS}"""

def _pool_row(face_id: str, pool: dict, offers: list) -> str:
    held = _members(pool, offers)
    where = ", ".join(sorted({_who(o["p"]) for o, _ in held})) or "nothing offered now"
    tags = "".join(f"""<span class="chip">{C._esc(t)}</span>""" for t in pool.get("tags") or [])
    acts = C._btn("Change", "spread_edit", "ui-btn cv-small", face=face_id, id=pool["id"]) + C._btn("Send again", "spread_send", "ui-btn cv-small", face=face_id, id=pool["id"], title="Writes this pool to every Magpie machine answering now (a machine that was off, or got a member model since)") + C._btn("Remove", "spread_del", "ui-btn cv-small cv-danger", face=face_id, id=pool["id"], confirm=f"""Remove pool~{pool["id"]} from the portal and from every machine answering? Work naming it then fails. The portal keeps it as an earlier version in the library.""")
    names, off = ", ".join(sorted({a["name"] for _, a in held})), pool.get("off") or []
    machines = "".join(C._btn(f"""{"&#x23F8; " if o["p"]["id"] in off else "&#x2713; "}{C._esc(_who(o["p"]))}""", "spread_machine", f"""ui-btn cv-small{" cv-dim" if o["p"]["id"] in off else ""}""", face=face_id, id=pool["id"], pid=o["p"]["id"], off="" if o["p"]["id"] in off else "1", title="Switched off: its members stay in the pool, and no work is sent to them (a machine overheating, or busy with something else). Press to switch it on again." if o["p"]["id"] in off else "Press to send this machine no more work from this pool (its members stay in the pool)") for o in {o["p"]["id"]: o for o, _ in held}.values()) + "".join(C._btn(f"""&#x23F8; {C._esc(_who(C.AV.lib.get("provider", x)) if C.AV.lib.has("provider", x) else x)}""", "spread_machine", "ui-btn cv-small cv-dim", face=face_id, id=pool["id"], pid=x, off="", title="Switched off, and not answering now: press to switch it on again (it takes work once it answers and the pool is sent again)") for x in off if x not in {o["p"]["id"] for o, _ in held})
    return f"""<div class="list-row"><div class="row"><b class="mono">pool~{C._esc(pool["id"])}</b><span class="chip">{C._esc(pool.get("class") or "background")}</span>{tags}<span class="grow"></span>{acts}</div>{C._dim(C._esc(pool.get("about", "")))}{C._dim(f"{len(held)} member(s): {C._esc(names)} - on {C._esc(where)}")}<div class="row" style="flex-wrap:wrap">{C._dim("machines:")}{machines}</div></div>"""

# --- Panel ---

async def _body(face_id: str, edit: dict = None) -> str:
    offers = await C._offers()
    pools = "".join(_pool_row(face_id, p, offers) for p in sorted(_served(), key=lambda p: p["id"])) or C._dim("No pools yet: make one below.")
    rows = "".join(f"""<div hx-get="{C._P}/spread_row?face={C.quote(face_id)}&amp;pid={C.quote(o["p"]["id"])}" hx-trigger="load" hx-swap="outerHTML">{C._dim(C._esc(_who(o["p"])) + ": asking ...")}</div>""" for o in offers if not o["p"].get("speaks"))
    about = f"""<details><summary class="cv-dim">How pools work</summary>{C._dim("A pool is a name, pool~<name>, that stands for a set of models across the machines. Every Magpie machine keeps a copy, so a program on any of them (a knowledge group's chat or embedding model, a role's binding) is pointed at pool~<name> there, and that machine sends each request to the member with the fewest requests per slot - its own models or another machine's. Background work waits while anything else wants the same program, and uses at most each machine's share (below). A knowledge server whose model is a pool is told the pool's whole capacity when it starts, so restart a group after its pool grows. A pool may hold chat and embedding models together (an ingestion pool): each request goes to a member that does what it asks, so a knowledge group can be given the one pool for both. Its embedding members must be copies of one model file: vectors from different files do not mix.")}</details>"""
    machines = f"""<details><summary><b>Each machine: the pools it holds, and its share for background work</b></summary>{rows or C._dim("No Magpie machine yet (Settings, Machines).")}</details>"""
    return f"""{about}<div class="cv-sec"><b>Pools</b>{pools}</div><div id="cv-spread-form">{_form(face_id, offers, edit)}</div>{machines}"""

async def p_spread(c) -> str: return f"""<div id="cv-spread">{await _body(c.face["id"])}</div>"""

async def _redraw(imr, face_id: str, msg: str, bad: bool = False, edit: dict = None):
    """The pools panel alone, with the message above it: the rest of the page stays as it is."""
    imr.oob(C._note(msg, bad), "cv-msg")
    return imr.oob(await _body(face_id, edit), "cv-spread")

# --- Intents ---

def _refuse(imr, text: str): return imr.oob(C._note(text, True), "cv-msg")

async def _h_edit(request, payload, imr): return imr.oob(_form(payload["face"], await C._offers(), C.AV.lib.get("pool", payload["id"]) if payload.get("id") else None), "cv-spread-form")

async def _h_save(request, payload, imr):
    if not C._admin(request): return _refuse(imr, "Only a portal admin makes pools.")
    name, orig = (payload.get("name") or "").strip(), payload.get("orig") or ""
    if not NAME.fullmatch(name): return _refuse(imr, "A pool's name: letters, digits, _ and - (up to 40); work names it pool~<name>.")
    if name != orig and C.AV.lib.has("pool", name): return _refuse(imr, f"""A pool named {name} exists already: press Change beside it, or pick another name.""")
    offers = await C._offers()
    by = {a["name"]: a for o in _hosts(offers) for a in _models(o)}
    every = [f"*|{n}" for n in by if payload.get(f"a_{_mid(n)}")]
    picked = [k for o in _hosts(offers) for a in _models(o) if (k := f"""{o["p"]["id"]}|{a["name"]}""") and payload.get(f"m_{_mid(k)}") and f"""*|{a["name"]}""" not in every]
    if not every + picked: return _refuse(imr, "Tick at least one member.")
    names = {m.split("|", 1)[1] for m in every + picked}
    if len(embeds := {n for n in names if "chat" not in by[n].get("capabilities", [])}) > 1: return _refuse(imr, f"""A pool's embedding members must be copies of one model file (vectors from different files do not mix): ticked {", ".join(sorted(embeds))}.""")
    slots = {k: int(v) for o in _hosts(offers) for a in _models(o) if (k := f"""{o["p"]["id"]}|{a["name"]}""") and str(v := payload.get(f"s_{_mid(k)}") or "").strip().isdigit() and int(v) > 0}
    old = C.AV.lib.get("pool", orig) if orig and C.AV.lib.has("pool", orig) else {}
    pool = C.AV.lib.save("pool", {**old, "id": name, "name": name, "about": (payload.get("about") or "").strip(), "members": every + picked, "slots": slots, "class": payload.get("klass") or "background", "tags": [t.strip() for t in (payload.get("tags") or "").split(",") if t.strip()], "serve": True, "users": old.get("users", []), "prefer": old.get("prefer", "running")}, by=C._user(request))
    return await _redraw(imr, payload["face"], await _send(pool))

async def _h_send(request, payload, imr):
    if not C._admin(request): return _refuse(imr, "Only a portal admin sends pools to the machines.")
    return await _redraw(imr, payload["face"], await _send(C.AV.lib.get("pool", payload["id"])))

async def _h_machine(request, payload, imr):
    """A machine switched off (off=1) or on in one pool (id), or in every pool (no id); each changed pool is saved and sent to the machines again."""
    if not C._admin(request): return _refuse(imr, "Only a portal admin changes pools.")
    pid, off, said = payload["pid"], bool(payload.get("off")), []
    for pool in [C.AV.lib.get("pool", payload["id"])] if payload.get("id") else _served():
        have = [x for x in pool.get("off") or [] if x != pid] + ([pid] if off else [])
        if have != (pool.get("off") or []): said.append(await _send(C.AV.lib.save("pool", {**pool, "off": have}, by=C._user(request))))
    who = _who(C.AV.lib.get("provider", pid)) if C.AV.lib.has("provider", pid) else pid
    return await _redraw(imr, payload["face"], f"""{who} switched {"off" if off else "on"}{" in pool~" + payload["id"] if payload.get("id") else " in every pool"}. """ + (" ".join(said) or "No pool changed."))

async def _h_del(request, payload, imr):
    if not C._admin(request): return _refuse(imr, "Only a portal admin removes pools.")
    offers, pid = await C._offers(), payload["id"]
    async def drop(o):
        try: await C.PROV.machine(o["p"], "PATCH", "/settings", {"path": f"pools.{pid}", "value": None, "source": "the portal's pools"}, timeout=30.0)
        except C.PROV.ProviderError as e: return f"""{_who(o["p"])}: {e}"""
        return ""
    bad = [e for e in await asyncio.gather(*(drop(o) for o in _nodes(offers))) if e]
    C.AV.lib.remove("pool", pid)
    return await _redraw(imr, payload["face"], f"""pool~{pid} removed from the portal (kept as an earlier version in the library) and from the machines answering.""" + (f""" Not removed: {"; ".join(bad)}.""" if bad else ""), bool(bad))

async def _h_drop(request, payload, imr):
    if not C._admin(request): return _refuse(imr, "Only a portal admin changes a machine's settings.")
    p = C.AV.lib.get("provider", payload["pid"])
    try: await C.PROV.machine(p, "PATCH", "/settings", {"path": f"""pools.{payload["name"]}""", "value": None, "source": f"{C._user(request)} from the portal"}, timeout=30.0)
    except C.PROV.ProviderError as e: return _refuse(imr, f"Not removed: {e}")
    return await _redraw(imr, payload["face"], f"""pool~{payload["name"]} removed from {_who(p)}; the machine keeps its settings as they were before the change.""")

async def _h_share(request, payload, imr):
    if not C._admin(request): return _refuse(imr, "Only a portal admin changes a machine's settings.")
    p = C.AV.lib.get("provider", payload["pid"])
    try: await C.PROV.machine(p, "PATCH", "/settings", {"path": "scheduler.background_share", "value": min(1.0, max(0.0, float(payload.get("share") or 0))), "source": f"{C._user(request)} from the portal"}, timeout=30.0)
    except (C.PROV.ProviderError, ValueError) as e: return _refuse(imr, f"Not set: {e}")
    C._changed(imr, f"""machine:{p["id"]}""")
    return imr.oob(C._note(f"""{_who(p)}: background work may use {payload.get("share")} of each program's slots."""), "cv-msg")
