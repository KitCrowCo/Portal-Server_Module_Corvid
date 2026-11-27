"""machines.py - Corvid's Machines panel, beside corvid.py: each provider's own programs as it lists them (what is active, installed, could be installed, and doing it), the programs it has running (stop, kill, start again, log), the node's restart, where it keeps things (a folder browser over the machine's own folders, and the same places given to other machines), and Magpie's own code (compared with the portal's copy, brought up to date, or back to the version before).
Everything shown is the machine's own answer; nothing here names a program.
C is a live view of corvid.py's globals, set when Corvid starts."""
import os, json, time, base64, asyncio, hashlib
from pathlib import Path
from urllib.parse import quote

C = None

# --- Panel: machines (each provider's own programs, as it lists them: what is active, installed, could be installed, and doing it) ---

OPEN = {}   # user -> the machine that person last did something to: its section is drawn open, so a change does not fold the page back up
INSTALLS = {}   # (provider id, module) -> {"lines", "done", "ok"}: an install going on, followed by the page while it lasts; the node's own log keeps it all

def install_view(pid: str, name: str) -> str:
    rec = INSTALLS[(pid, name)]
    poll = "" if rec["done"] else f"""hx-get="{C._P}/install?pid={C._esc(pid)}&amp;name={C._esc(name)}" hx-trigger="every 2s" hx-swap="outerHTML" """
    head = C._note("Installed." if rec["ok"] else "Did not finish; the last lines say why.", not rec["ok"]) if rec["done"] else C._dim("Installing - this goes on at the node if this page is closed.")
    hide = f"""<div class="row"><span class="grow"></span>{C._btn("Hide", "machine_seen", "ui-btn cv-small", pid=pid, name=name)}</div>""" if rec["done"] else ""
    return f"""<div {poll}>{head}<details{"" if rec["done"] and rec["ok"] else " open"}><summary class="cv-dim">its last lines</summary><div class="quote-block mono cv-log">{C._esc(chr(10).join(rec["lines"][-14:]))}</div></details>{hide}</div>"""

LOOK_S = 20.0   # what a machine said of itself is asked again in the background once this old; nothing here waits for it

async def _heard(p: dict, what: str, path: str) -> dict:
    """What the machine last answered to GET path, kept (Aviary's seen) and asked again in the background when older than LOOK_S. Right after a change made from here (C._recheck) the page waits up to 3 s for the new answer, so it shows the change."""
    key = f"""{p["id"]}:{what}"""
    return await C.AV.seen.fresh(key, lambda: C.PROV.machine(p, "GET", path, timeout=20.0), LOOK_S, 3.0 if (C.AV.seen.rows.get(key) or {}).get("asked") == 0.0 else 0.0)

# --- Telling open pages what changed: every answer a machine gives is kept centrally (Aviary seen); when one changes what a page would show, every part tagged with that machine asks for itself again ---

_GIST = {"code": lambda v: v.get("fingerprint"), "modules": lambda v: sorted((m.get("name"), m.get("state")) for m in v.get("modules") or []), "services": lambda v: sorted((x.get("name"), x.get("status"), x.get("model")) for x in v.get("services") or []), "assets": lambda v: sorted(str(a.get("name")) for a in v.get("models") or v.get("assets") or [] if isinstance(a, dict))}   # what of an answer a page shows that matters for redrawing it (figures that move with every ask, like uptime or idle time, do not)
_TELL: dict = {"tags": set(), "later": None}

def seen_said(key: str, before: dict, after: dict):
    """Aviary seen's listener: a machine's answer that came back, went missing, arrived for the first time or changed in what pages show says "machine:<id>" changed, once for all of them within half a second."""
    pid, _, what = key.partition(":")
    gist = _GIST.get(what.split(":")[0], lambda v: None)   # anything else: only whether it answers
    now_ok, was_ok = not after.get("error"), before["value"] is not None and not before["error"]
    if now_ok == was_ok and not (now_ok and gist(after.get("value") or {}) != gist(before["value"] or {})): return
    _TELL["tags"].add(f"machine:{pid}")
    if not _TELL["later"]: _TELL["later"] = asyncio.get_running_loop().call_later(0.5, lambda: asyncio.ensure_future(_tell()))

async def _tell():
    tags, _TELL["tags"], _TELL["later"] = sorted(_TELL["tags"]), set(), None
    for user in list(C.WS.active_connections): await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cv-changed", "detail": {"tags": tags}})

async def _look(p: dict) -> tuple:
    """What a machine last said of itself: its programs, what it is doing, its code - each (the answer or None, why the last ask failed, the kept entry)."""
    return p, *[(r["value"], r["error"], r) for r in [await _heard(p, w, path) for w, path in (("modules", "/modules"), ("status", "/control/status"), ("code", "/node/code"))]]

HEALTH = {"ok": ("cv-ok", "yes"), "missed": ("cv-mid", "may be down"), "never": ("cv-bad", "no"), "asking": ("", "...")}   # the chip for each state of a kept answer (Aviary's seen.health)

def _as_of(r: dict) -> str:
    """A kept answer's state in words: answering, or missed its last check(s) and shown as it was then (with why), or never reached."""
    state, words = C.SEEN.health(r)
    return C._esc(words) + (f""" ({C._esc(r["error"])})""" if state in ("missed", "never") else "")

def _grid(looks: list, src: dict) -> str:
    """Every machine on one line, then every program by machine: the state of each where it is known."""
    def code(node):
        if not node: return "older"
        if not src: return node["fingerprint"][:8]
        d = _differ(src, node)
        return "up to date" if not (d["changed"] or d["new"]) else f"""behind ({len(d["changed"]) + len(d["new"])})"""
    def line(p, mods, st, node):
        m = (st[0] or {}).get("memory") or {}
        busy = len([j for j in (st[0] or {}).get("requests") or [] if j["capability"] != "warm"])
        up = ", ".join(s["name"] for s in (st[0] or {}).get("services") or [] if s.get("pid")) or "-"
        state, words = C.SEEN.health(mods[2])
        reach = f"""<span class="chip {HEALTH[state][0]}" title="{C._esc(mods[1])}">{HEALTH[state][1]}</span> <span class="cv-dim">{C._esc(words)}</span>"""
        old = f""" style="font-style:italic;opacity:.6" title="As it was {C._esc(C.SEEN.age(mods[2]))}: this machine missed its last check, so this may no longer hold" """ if state == "missed" else ""   # what a machine said before it stopped answering stays shown, marked as possibly out of date
        return f"""<tr><td><b>{C._esc(p.get("name") or p["id"])}</b></td><td>{reach}</td><td{old}>{C._esc(code(node[0]))}</td><td{old}>{f'{m.get("ram_avail_gb")} / {m.get("ram_total_gb")} GB' if m else "-"}</td><td{old}>{busy} running, {len((st[0] or {}).get("queued") or [])} waiting</td><td class="cv-dim"{old}>{C._esc(up)}</td></tr>"""
    heads = "".join(f"""<th>{C._esc(p.get("name") or p["id"])}</th>""" for p, *_ in looks)
    states = {(p["id"], m["name"]): m["state"] for p, mods, *_ in looks for m in (mods[0] or {}).get("modules", [])}
    names = sorted({n for _, n in states}, key=lambda n: (-sum(states.get((p["id"], n)) == "active" for p, *_ in looks), n))
    chip = lambda st: f"""<span class="chip {"cv-ok" if st == "active" else "cv-mid" if st == "installed" else ""}">{C._esc(st)}</span>""" if st in ("active", "installed") else f"""<span class="cv-dim">{C._esc(st or "?")}</span>"""
    progs = "".join(f"""<tr><td>{C._esc(n)}</td>{"".join(f"<td>{chip(states.get((p['id'], n), ''))}</td>" for p, *_ in looks)}</tr>""" for n in names)
    return f"""<table class="cv-tbl"><tr><th>machine</th><th>reached</th><th>Magpie</th><th>memory free</th><th>work</th><th>programs up</th></tr>{"".join(line(*x) for x in looks)}</table><details><summary class="cv-dim">Programs by machine</summary><div class="scroll-pane"><table class="cv-tbl"><tr><th>program</th>{heads}</tr>{progs}</table></div></details>"""

async def p_machines(c) -> str:
    src, shown, admin = _source(), OPEN.get(C._user(c.request), ""), C._admin(c.request)
    offers = C._offers_now()
    looks = [await _look(o["p"]) for o in offers if not o["p"].get("speaks")]
    for skip in {json.dumps(node[0]["skip"], sort_keys=True) for *_, node in looks if src and node[0]}: await asyncio.to_thread(_code_files, src["folder"], json.loads(skip))   # hashed off the event loop (once per change), so the comparisons below only read it
    speaking = "".join(C._dim(f"""{C._esc(o["p"].get("name") or o["p"]["id"])} speaks {C._esc(o["p"]["speaks"])}: its programs are managed where it runs.""") for o in offers if o["p"].get("speaks"))
    out = speaking + "".join([await section(c.face["id"], admin, look, src, look[0]["id"] == shown) for look in looks])
    return f"""{grid_box(c.face["id"], looks, src)}{C._dim("Below, each machine in full: its programs, as it lists them. Installed means present; active means offered. Installing shows the program's options and what it needs from the system before anything is done; it is done by the machine itself, which downloads what the program names. Each shows what it last said, and how long ago; one that is away holds up nothing else.")}{_source_row(c.face["id"], src) if admin else ""}{_all_row(c.face["id"]) if admin and src else ""}{updates_html()}{out or C._dim("no provider yet")}"""

def grid_box(face_id: str, looks: list, src: dict) -> str:
    """Every machine on one line, as last heard; while any is being asked it draws itself again every 3 s (GET /machines_grid), and stops once all have answered."""
    poll = f"""hx-get="{C._P}/machines_grid?face={C.quote(face_id)}" hx-trigger="every 3s" hx-swap="outerHTML" """ if any(x[2]["asking"] for _, *parts in looks for x in parts) else ""
    return f"""<div id="cv-mgrid" {poll}>{_grid(looks, src)}</div>"""

async def section(face_id: str, admin: bool, look: tuple, src: dict, opened: bool = False) -> str:
    """One machine in full, from what it last said. Never heard from yet: a placeholder that asks for itself until it has an answer (GET /machine_section). Heard from: its programs, code, running programs and folders, with how old that is; a newer answer coming in is offered (Show newer) rather than drawn over what is open."""
    p, mods, st, node = look
    pname = p.get("name") or p["id"]
    if mods[0] is None and not mods[1]: return f"""<details class="cv-machine" hx-get="{C._P}/machine_section?face={C.quote(face_id)}&amp;pid={C.quote(p["id"])}" hx-trigger="every 2s" hx-swap="outerHTML"><summary><b>{C._esc(pname)}</b> <span class="chip">being asked ...</span></summary></details>"""
    d, said = (mods[0], "") if mods[0] else ({"modules": []}, C._note(C.older(C.PROV.ProviderError(mods[1]), "list its programs"), True))   # the rest of what the machine answered (running programs, where it keeps things) is still shown
    def row(m):
        st_, pid, name = m["state"], p["id"], m["name"]
        acts = (C._btn("Deactivate", "machine_act", face=face_id, pid=pid, name=name, verb="deactivate", confirm="Stop offering what it does, now? Its files stay.") if st_ == "active"
                else C._btn("Activate", "machine_act", face=face_id, pid=pid, name=name, verb="activate") if st_ == "installed" else "")
        acts += C._btn("Install" if st_ not in ("active", "installed") else "Install again", "machine_form", pid=pid, name=name) if m.get("plan") else ""
        acts += C._btn("Remove", "machine_act", "ui-btn cv-danger", face=face_id, pid=pid, name=name, verb="remove", confirm="Remove its installed program and environment from that machine? Models and results stay.") if m.get("installed") and st_ != "active" else ""
        live = install_view(pid, name) if (pid, name) in INSTALLS else ""
        err = C._note(m["error"], True) if m.get("error") else ""
        behind = C._dim(C._esc("Its install changed since it was installed, in ways only installing again takes: " + "; ".join(m["installed"]["behind"]))) if (m.get("installed") or {}).get("behind") else ""
        behind += C._dim(C._esc("Built from " + ", ".join(f"{k} {v}" for k, v in m["installed"]["sources"].items()) + " - Install again brings these to the ref it asks for (master: the newest) and builds again")) if (m.get("installed") or {}).get("sources") else ""
        return f"""<div class="list-row"><div class="row"><b>{C._esc(m.get("label") or name)}</b><span class="chip {"cv-ok" if st_ == "active" else "cv-mid" if st_ in ("installed", "updating") else ""}">{C._esc(st_)}</span><span class="cv-dim grow">{C._esc(", ".join(m.get("provides") or []))}</span>{acts}</div>{err}{behind}<div id="cv-mod-{C._esc(pid)}-{C._esc(name)}">{live}</div></div>"""
    order = {"active": 0, "updating": 1, "installed": 1}
    rows = "".join(row(m) for m in sorted(d["modules"], key=lambda m: (order.get(m["state"], 2), m["name"])))
    rows += f"""<div class="row"><span class="grow"></span>{C._btn("Update its programs", "programs_update", face=face_id, pid=p["id"], title="Each program it built from source (" + ", ".join(m.get("label") or m["name"] for m in src_mods) + ") brought to the newest and built again, one after another, with the driver and options it has. Running programs keep their build until they next start.", confirm="Build these programs again from their newest source? It takes a while and uses the machine's memory while it builds.")}</div>""" if admin and (src_mods := _from_source(d["modules"])) else ""
    on = sum(m["state"] == "active" for m in d["modules"])
    again = C._tags("machine:" + p["id"], get=f"""{C._P}/machine_section?face={C.quote(face_id)}&amp;pid={C.quote(p["id"])}""")   # asks for itself again when the machine changes (corvid _changed)
    return f"""<details class="cv-machine" id="{C._elid("cv-mach-" + p["id"])}" {again}{" open" if opened else ""}><summary><b>{C._esc(pname)}</b> <span class="cv-dim">{C._esc(p["url"])} | {on} active, {sum(m["state"] == "installed" for m in d["modules"])} installed, {len(d["modules"])} known | </span>{age_chip(face_id, p["id"], mods[2])}</summary>{said}{await _code(face_id, p, src, admin)}{rows}{await _services(face_id, p)}{await _locations(face_id, p)}<div class="cv-role"><div class="row"><b class="grow">Its settings</b>{C._btn("Show", "knobs_form", face=face_id, pid=p["id"], title="Every value this machine lets a manager set, by program")}</div><div id="cv-knobs-{C._esc(p["id"])}"></div></div></details>"""

def age_chip(face_id: str, pid: str, drawn: dict) -> str:
    """How old the drawn answer is. While the machine is asked again it asks for itself (GET /machine_age); when a newer answer is in, it offers to show it."""
    r = C.AV.seen.rows.get(f"{pid}:modules") or drawn
    if r["t"] > drawn["t"] + 0.5: return f"""<button class="ui-btn cv-small" hx-get="{C._P}/machine_section?face={C.quote(face_id)}&amp;pid={C.quote(pid)}&amp;open=1" hx-target="closest details" hx-swap="outerHTML" title="It answered again; this shows that answer here (anything open in this section closes)">newer answer: show</button>"""
    asking = C.AV.seen.asking(f"{pid}:modules")
    poll = f"""hx-get="{C._P}/machine_age?face={C.quote(face_id)}&amp;pid={C.quote(pid)}&amp;t={drawn["t"]}" hx-trigger="every 2s" hx-swap="outerHTML" """ if asking else ""
    return f"""<span class="cv-dim" {poll}>{_as_of(drawn)}{" - asking again ..." if asking else ""}</span>"""

# --- A machine's settings: every value it lets a manager set, as it lists them (its /knobs), changed one by one (PATCH /settings) ---

_AUTO = "(as it decides)"
def _knob_field(k: dict):
    """One setting as a form field. Left empty (or on the first choice) it is the machine's own value again."""
    said = " ".join(x for x in (k.get("effect", ""), f"""Now: {C._shown(k["current"])}.""" if k.get("current") not in (None, "") else "", f"""Set by {k["set_by"]}.""" if k.get("set_by") not in (None, "", "auto") else "", "Takes effect at the program's next start." if k.get("when") not in (None, "now") else "") if x)
    if k.get("choices") or k["type"] == "boolean": return C.BI.SettingField(k["key"], k.get("label") or k["name"], "select", options=[("", _AUTO), *((json.dumps(c) if isinstance(c, bool) else str(c), "yes" if c is True else "no" if c is False else str(c)) for c in (k.get("choices") or [True, False]))], hint=said, advanced=bool(k.get("advanced")))
    return C.BI.SettingField(k["key"], k.get("label") or k["name"], "json" if k["type"] in ("list", "object") else "text", default=[] if k["type"] == "list" else {} if k["type"] == "object" else "", hint=said, advanced=bool(k.get("advanced")))   # "advanced": in the form's Advanced part

def _knob_value(k: dict, raw):
    """A form value as the setting's type; nothing given is None (the machine's own value)."""
    if raw in ("", None, [], {}): return None
    if k["type"] == "boolean": return raw in (True, "true")
    return int(float(raw)) if k["type"] == "integer" else float(raw) if k["type"] == "number" else raw

async def _h_knobs_form(request, payload, imr):
    """The machine's settings form, drawn into payload "into" (default its section in Machines); "only": the comma-separated keys to show (the loading rules), else every setting by module."""
    p, el = C.AV.lib.get("provider", payload["pid"]), payload.get("into") or f"""cv-knobs-{payload["pid"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: knobs = (await C.PROV.machine(p, "GET", "/knobs", timeout=10.0))["knobs"]
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "list its settings"), True), el)
    knobs = [k for k in knobs if k["key"] in payload["only"].split(",")] if payload.get("only") else knobs
    shown = lambda k: json.dumps(k["value"]) if isinstance(k["value"], bool) else k["value"]
    groups = "".join(f"""<details class="sec" {"open" if payload.get("only") else ""}><summary><b>{C._esc(m)}</b> <span class="cv-dim">{len(ks)} settings{", " + str(sum(1 for k in ks if k["value"] is not None)) + " set" if any(k["value"] is not None for k in ks) else ""}</span></summary>{C._group([_knob_field(k) for k in ks]).render({k["key"]: shown(k) for k in ks if k["value"] is not None}, name_prefix="k_")}</details>""" for m, ks in {m: [k for k in knobs if k["module"] == m] for m in dict.fromkeys(k["module"] for k in knobs)}.items())
    fid = f"""cv-knobs-f-{payload["pid"]}"""
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false">{C._dim("A value left empty is the machine's own. Only what you change is sent; the machine keeps the version before each change.")}{groups}<div class="row"><span class="grow"></span>{C._btn("Save what changed", "knobs_save", face=payload.get("face", ""), pid=p["id"], into=el, only=payload.get("only", ""), include="#" + fid)}{C._btn("Close", "knobs_form", pid=p["id"], into=el, close="1")}</div></form>""", el)

async def _h_knobs_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes a machine's settings.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try:
        knobs = (await C.PROV.machine(p, "GET", "/knobs", timeout=10.0))["knobs"]
        knobs = [k for k in knobs if k["key"] in payload["only"].split(",")] if payload.get("only") else knobs
        got = C._group([_knob_field(k) for k in knobs]).parse(payload, "k_")
        changed = {k["key"]: v for k in knobs if f"""k_{k["key"]}""" in payload and (v := _knob_value(k, got[k["key"]])) != (None if k["value"] in ("", [], {}) else k["value"])}   # an empty value that stays empty is no change
        for key, v in changed.items(): await C.PROV.machine(p, "PATCH", "/settings", {"path": key, "value": v, "source": f"{C._user(request)} from the portal"}, timeout=30.0)
    except (C.PROV.ProviderError, C.BI.SettingsError, ValueError) as e: return imr.oob(C._note(f"Not all saved: {e}", True), "cv-msg")
    C._recheck(p["id"])
    imr.oob(C._note(f"""{p.get("name") or p["id"]}: """ + (", ".join(f"""{k} = {C._shown(v) if v is not None else "its own again"}""" for k, v in changed.items()) if changed else "nothing was changed") + "."), "cv-msg")
    C._changed(imr, f"""machine:{p["id"]}""")   # every part showing this machine asks for itself again; the rest of the page stays
    return imr.oob("", payload.get("into") or f"""cv-knobs-{p["id"]}""")   # the form closes; the rest of the page stays as it was

# --- Magpie's own code: the portal's copy (a Tool Library folder, kept from git or uploaded) against each machine's ---

def _library(): return C.ENV["services"].get("tools_library")   # the Tool Library module, when installed: the folders a source can be
def _source() -> dict:
    """The copy of Magpie the machines are compared with: {"tool": a Tool Library folder name, "folder", "git", "branch", "changed"}, empty when none is chosen or the folder is gone."""
    rec, lib = C.AV.lib.get("code", "magpie") if C.AV.lib.has("code", "magpie") else {}, _library()
    t = next((t for t in lib["list"]() if t["name"] == rec.get("tool")), None) if lib and rec.get("tool") else None
    return {**t, "tool": t["name"], "folder": lib["folder"](t["name"])} if t else {}

_HASHED: dict = {}   # (folder, skip rule) -> (signature, {path: sha256}): files are hashed again only when one of them changed (newest change time and count), not on every page

def _code_files(folder: Path, skip: dict) -> dict:
    """{relative path: sha256} of the code files in folder, by the rule the machine itself answers with (which folders, names and endings are not code). Skipped folders are not walked into."""
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip["dirs"]]
        files += [Path(root) / n for n in names if n not in skip["names"] and Path(n).suffix not in skip["suffixes"] and not (Path(root) / n).is_symlink()]
    key, sig = (str(folder), json.dumps(skip, sort_keys=True)), (len(files), max((f.stat().st_mtime for f in files), default=0))
    if key not in _HASHED or _HASHED[key][0] != sig: _HASHED[key] = (sig, {f.relative_to(folder).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(files)})
    return _HASHED[key][1]

def _differ(src: dict, node: dict) -> dict:
    """What updating would do: files that differ, files only the source has, files only the machine has."""
    have = node["files"]
    mine = _code_files(src["folder"], node["skip"])
    return {"changed": sorted(r for r in mine if r in have and mine[r] != have[r]), "new": sorted(r for r in mine if r not in have), "only_there": sorted(r for r in have if r not in mine)}

def _source_row(face_id: str, src: dict) -> str:
    lib = _library()
    if not lib: return C._note("Machines are brought up to date from a copy of Magpie in the Tool Library module, which is not installed here.", True)
    tools = lib["list"]()
    pick = f"""<select name="tool" class="module-select">{C._options([(t["name"], t.get("label") or t["name"]) for t in tools], src.get("tool", ""))}</select>""" if tools else C._dim("The Tool Library holds nothing yet: add Magpie there (from your Gitea, or a zip of it).")
    said = (f"""from git: {C._esc(src["git"])}{"@" + C._esc(src["branch"]) if src.get("branch") else ""}, last change {src["changed"]}""" if src.get("git") else f"""uploaded, last change {src["changed"]}""") if src else "none chosen yet"
    pull = C._btn("Pull it now", "code_pull", face=face_id, title="Fast-forward only: a folder changed here reports the conflict instead of being overwritten") if src.get("git") else ""
    return f"""<form class="cv-role row" id="cv-code-src" style="flex-wrap:wrap" onsubmit="return false"><b>Magpie's source</b>{pick}{C._btn("Use it", "code_source", face=face_id, include="#cv-code-src") if tools else ""}<span class="cv-dim grow">{said}</span>{pull}</form>"""

async def _code(face_id: str, p: dict, src: dict, admin: bool) -> str:
    """The machine's Magpie compared with the source, with the way to bring it up to date and back."""
    if (node := (r := await _heard(p, "code", "/node/code"))["value"]) is None: return C._note(C.older(C.PROV.ProviderError(r["error"]), "show or take its own code") + " Bring it up to date once by hand; from then on it is done from here.", True) if r["error"] else C._dim("its code: being asked ...")
    back = C._btn("Back to the version before", "code_rollback", "ui-btn cv-danger", face=face_id, pid=p["id"], confirm=f"""Put back the code this machine had before its last update ({node["kept"][0]["before"]})? It starts again with it.""") if node["kept"] and admin else ""
    if not src: return f"""<div class="row cv-role"><b>Magpie</b><span class="cv-dim grow">its code is {C._esc(node["fingerprint"])}. To compare and update it from here, choose "Magpie's source" at the top of this panel first.</span>{back}</div>"""
    d = await asyncio.to_thread(_differ, src, node)
    same = not (d["changed"] or d["new"])
    said = "the same as the source" + (f""" ({len(d["only_there"])} files there that the source does not have)""" if d["only_there"] else "") if same else f"""{len(d["changed"])} files differ, {len(d["new"])} new in the source"""
    up = "" if same else C._btn("Update Magpie", "code_form", face=face_id, pid=p["id"])
    return f"""<div class="cv-role"><div class="row"><b>Magpie</b><span class="chip {"cv-ok" if same else "cv-mid"}">{"up to date" if same else "behind the source"}</span><span class="cv-dim grow">{C._esc(said)} | {C._esc(node["fingerprint"])}{"" if node.get("supervised") else " | started by hand: it will need starting again after an update"}</span>{up}{back}</div><div id="cv-code-{C._esc(p["id"])}"></div></div>"""

async def _h_code_source(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin chooses Magpie's source.", True), "cv-msg")
    C.AV.lib.save("code", {"id": "magpie", "name": "Magpie", "tool": payload["tool"]}, by=C._user(request))
    return await C._refresh(request, imr, payload["face"], C._note(f"""Machines are now compared with {payload["tool"]} in the Tool Library."""))

async def _h_code_pull(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin pulls Magpie's source.", True), "cv-msg")
    ok, out = await asyncio.to_thread(_library()["pull"], _source()["tool"])
    return await C._refresh(request, imr, payload["face"], C._note(("Pulled: " if ok else "Not pulled: ") + out[-500:], not ok))

async def _h_code_form(request, payload, imr):
    """What an update of this machine would do, before it is done: the files, and the files only the machine has (removed only when ticked; each is kept on the machine to come back)."""
    p, el = C.AV.lib.get("provider", payload["pid"]), f"""cv-code-{payload["pid"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: src, node = _source(), await C.PROV.machine(p, "GET", "/node/code", timeout=20.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "show its own code"), True), el)
    d = await asyncio.to_thread(_differ, src, node)
    route = C._dim(f"""From: the Tool Library's copy "{C._esc(src["tool"])}" on this portal ({C._esc(src["folder"])}). To: {C._esc(p.get("name") or p["id"])} at {C._esc(p["url"])}, into the folder its Magpie runs from ({C._esc(node.get("home") or "it does not say which")}). Only the files listed below are sent; its data, settings, keys and environments are never touched.""")
    lst = lambda title, rows: f"""<details><summary class="cv-dim">{title}: {len(rows)}</summary><div class="mono cv-log">{C._esc(chr(10).join(rows))}</div></details>""" if rows else ""
    extra = f"""<label class="row"><input type="checkbox" name="remove" value="1"> also remove the {len(d["only_there"])} files there that the source does not have (kept on the machine, so the version before brings them back)</label>""" if d["only_there"] else ""
    fid = f"""cv-code-f-{payload["pid"]}"""
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false">{route}{lst("replaced", d["changed"])}{lst("new", d["new"])}{lst("only on this machine", d["only_there"])}{extra}<div class="row">{_work_pick()}</div>{C._dim("The machine applies it to a copy first; it is refused, with nothing changed, if that copy does not compile and start. Then it keeps what it had and starts again with the new code.")}<div class="row"><span class="grow"></span>{C._btn("Update", "code_update", face=payload["face"], pid=p["id"], include="#" + fid, confirm="Bring this machine's Magpie up to date now? It starts again by itself, after its work under way as chosen.")}{C._btn("Close", "code_form", pid=p["id"], close="1")}</div></form>""", el)

WORK = [("finish", "let it finish first (up to 10 min), then start again"), ("stop", "stop it now and start again")]   # what an update does with work under way on a machine (Magpie PUT /node/code "work")
def _work_pick(name: str = "work") -> str: return f"""<label class="cv-dim" title="Work under way on the machine (a chat, an ingestion, a picture) when the new code is in: let it end before the machine starts again, or end it at once. Until it starts again the machine runs its old code.">work under way: <select name="{name}" class="module-select">{C._options(WORK, "finish")}</select></label>"""

async def _update_one(p: dict, src: dict, remove: bool, who: str, work: str = "finish") -> tuple:
    """One machine's Magpie brought to the source: what differs is sent, the machine checks a copy and starts again with it. Answers (what was done, the fingerprint it will run with - "" when nothing was sent or it does not start again by itself); raises ProviderError when the machine refuses or cannot be reached (nothing changed there then)."""
    d = await asyncio.to_thread(_differ, src, await C.PROV.machine(p, "GET", "/node/code", timeout=20.0))
    if not (d["changed"] or d["new"] or (remove and d["only_there"])): return f"""{p.get("name") or p["id"]}: already the same as the source.""", ""
    files = {r: base64.b64encode((src["folder"] / r).read_bytes()).decode() for r in [*d["changed"], *d["new"]]}
    got = await C.PROV.machine(p, "PUT", "/node/code", {"files": files, "remove": d["only_there"] if remove else [], "from": f"""{src["tool"]} ({src.get("git") or "uploaded"}), by {who} from the portal""", "work": work}, timeout=1900.0)
    return f"""{p.get("name") or p["id"]}: {len(got["replaced"])} replaced, {len(got["added"])} new, {len(got["removed"])} removed ({got["before"]} -> {got["after"]}). """ + (f"""It is starting again ({got["by"]}).""" if got["restarting"] else got.get("note", "")) + (f""" {got["requirements"]}.""" if got.get("requirements") else ""), got["after"] if got["restarting"] else ""

async def _h_code_update(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin updates a machine's Magpie.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try: said, _ = await _update_one(p, _source(), bool(payload.get("remove")), C._user(request), payload.get("work") or "finish")
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "take its own code"), True), f"""cv-code-{p["id"]}""")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(said))

UPDATES: dict = {}   # the last "Update every machine": {"running", "notes"}, shown on Settings > Machines while it runs and after
_TASKS = set()   # its task: the event loop holds tasks only weakly

async def _back(p: dict, after: str, wait_s: float = 240.0) -> str:
    """"" once the machine answers again running the new code (its fingerprint is after); otherwise what it last said instead (an error, or the fingerprint it answered with) once wait_s has passed with nothing to wait for. While the old process says it is still finishing its work before starting again (Magpie "restart"), the wait runs from when that ends. Asked even while it is marked down (TRY_ANYWAY: a restart is expected to miss a few asks), each ask up to 30 s. The phase on the list (UPDATES["phase"]) follows it."""
    C.PROV.TRY_ANYWAY.set(True)   # this task only
    last, t0, ph = "no answer yet", time.time(), UPDATES.setdefault("phase", {})
    while time.time() - t0 < wait_s:
        await asyncio.sleep(5)
        try: got = await C.PROV.machine(p, "GET", "/node/code", timeout=30.0)
        except C.PROV.ProviderError as e: got, last, ph[p["id"]] = None, str(e), "starting again (not answering yet)"
        if got is None: continue
        if got.get("fingerprint") == after: return ""
        last, r = f"""it answered running {got.get("fingerprint")} instead""", got.get("restart") or {}
        if r.get("jobs") and r.get("work") == "finish":
            t0, ph[p["id"]] = time.time(), f"""letting {r["jobs"]} job(s) under way finish (up to {max(0, int(r.get("until", 0) - time.time()))} s more)"""
        else: ph[p["id"]] = "ending its work and programs, then starting again"
    return last

async def _update_noted(p: dict, src: dict, who: str) -> str:
    """One machine of an update of every machine, its outcome noted on the list: "same" (already the source), "updated" (answering again with the new code), "refused" (it refused or could not be reached before anything changed there: safe to go on with the others), "lost" (it took the new code and has not answered with it for 4 minutes)."""
    name, ph = p.get("name") or p["id"], UPDATES.setdefault("phase", {})
    ph[p["id"]] = "sending the changed files (the machine checks a copy)"
    try: said, after = await _update_one(p, src, False, who, UPDATES.get("work") or "finish")
    except C.PROV.ProviderError as e:
        UPDATES["notes"].append(f"""{name}: not updated, nothing changed there - {e}""")
        return "refused"
    UPDATES["notes"].append(said)
    if after and (why := await _back(p, after)):
        UPDATES["notes"].append(f"""{name}: took the new code and has not answered with it for 4 minutes (last: {why}). Its earlier code is kept on it (Back to the version before).""")
        return "lost"
    if UPDATES.get("programs"):   # then its programs built from source, one after another
        ph[p["id"]] = "running the new code; now building its programs from source (Install again)"
        await programs_update(p)
    return "updated" if after else "same"

def _picked(v) -> list: return [x for x in (v if isinstance(v, list) else [v]) if x] if v else []   # a checkbox group arrives as a list, one ticked as a string

async def _waited(p: dict, src: dict, who: str) -> str:
    """One machine's update as a task of its own (UPDATES["doing"]), so the person can stop waiting for it: then "skipped" (it may still take the code - its own page says)."""
    t = asyncio.create_task(_update_noted(p, src, who))
    UPDATES["doing"][p["id"]] = (p.get("name") or p["id"], t)
    try: return await t
    except asyncio.CancelledError:
        if p["id"] in UPDATES["skip"]:   # the person stopped waiting for this one; a stop of the whole update is not caught here
            UPDATES["notes"].append(f"""{p.get("name") or p["id"]}: stopped waiting for it. If it had taken the new code it runs it once it starts again; Back to the version before is on its own page.""")
            return "skipped"
        raise
    finally:
        UPDATES["doing"].pop(p["id"], None)
        UPDATES.get("phase", {}).pop(p["id"], None)
        C.PROV.forget(p["id"])   # however it ended (back, lost, not waited for): its down mark from the restart goes, and what is kept of it is asked again
        C._recheck(p["id"])
        UPDATES.setdefault("changed", []).append(p["id"])   # said to the page by the next poll of the list (updates_html): that machine's parts ask for themselves again

async def _h_code_update_all(request, payload, imr):
    """The chosen Magpie machines brought to the source in the background. With "test first": the chosen first machine alone, then (once it answers again with the new code, or already runs it) the others at once; a first that refuses, is out of reach or is skipped by the person hands "first" to the next in line. Without: all at once. A machine that refuses or cannot be reached changes nothing and does not stop the others; one that takes the new code and does not come back stops the update while it is the first (the source itself may be at fault). Each machine can be stopped waiting for, and the whole update stopped (UPDATES["task"]); what a machine already took stays (its page: Back to the version before)."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin updates the machines' Magpie.", True), "cv-msg")
    if UPDATES.get("running"): return imr.oob(C._note("An update of every machine is already under way: see its list on this page.", True), "cv-msg")
    every = {p["id"]: p for p in C.AV.lib.list("provider") if not p.get("speaks")}
    chosen = [every[i] for i in _picked(payload.get("upd_m")) if i in every]
    if not chosen: return imr.oob(C._note("Tick the machines to update.", True), "cv-msg")
    first = next((p for p in chosen if p["id"] == payload.get("upd_first")), chosen[0])
    src, who, test = _source(), C._user(request), str(payload.get("upd_test") or "") in ("1", "on", "true")
    UPDATES.clear()
    UPDATES.update(running=True, doing={}, phase={}, skip=set(), work=payload.get("upd_work") or "finish", programs=str(payload.get("upd_programs") or "") in ("1", "on", "true"), notes=[f"""{len(chosen)} machine(s) from {src["tool"]}: {f"{first.get('name') or first['id']} first, then the rest together" if test else "all at once"}"""])
    async def all_at_once(ps):
        outcomes = await asyncio.gather(*(_waited(q, src, who) for q in ps))
        UPDATES["notes"].append(f"""done{f", {outcomes.count('refused')} refused or out of reach (nothing changed on them: update them again later)" if outcomes.count("refused") else ""}{f", {outcomes.count('lost')} did not come back" if outcomes.count("lost") else ""}{f", {outcomes.count('skipped')} not waited for" if outcomes.count("skipped") else ""}""")
    async def go():
        try:
            if not test: return await all_at_once(chosen)
            left = [first, *(p for p in chosen if p is not first)]
            while left:
                got = await _waited(left.pop(0), src, who)
                if got == "lost": return UPDATES["notes"].append(f"""Stopped: the first machine to take this code did not come back with it. The {len(left)} not reached were left as they were.""")
                if got in ("updated", "same"):
                    if left: UPDATES["notes"].append(f"""The source starts: the other {len(left)} together now.""")
                    return await all_at_once(left)
                if left: UPDATES["notes"].append(f"""{left[0].get("name") or left[0]["id"]} goes first now.""")
            UPDATES["notes"].append("done: no machine could be tried first (each refused, was out of reach or was not waited for; nothing changed on those that refused)")
        except asyncio.CancelledError: UPDATES["notes"].append("Stopped by hand: machines not reached yet were left as they were; one that had already taken the code keeps it.")
        finally: UPDATES["running"] = False
    _TASKS.add(task := asyncio.create_task(go()))
    UPDATES["task"] = task
    task.add_done_callback(_TASKS.discard)
    return await C._refresh(request, imr, payload["face"], C._note("Updating the machines: the list on this page follows it."))

async def _h_code_update_stop(request, payload, imr):
    """Stop waiting for one machine of the update (pid), or stop the whole update (no pid)."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin stops an update.", True), "cv-msg")
    if payload.get("pid") and (d := (UPDATES.get("doing") or {}).get(payload["pid"])):
        UPDATES["skip"].add(payload["pid"])
        d[1].cancel()
    elif not payload.get("pid") and UPDATES.get("task"): UPDATES["task"].cancel()
    return imr.oob(updates_html(), "cv-code-all", swap="outerHTML")

def _all_row(face_id: str) -> str:
    """The update of every machine, set up: which machines (all ticked), which goes first, whether one goes first at all."""
    if UPDATES.get("running"): return ""
    ps = [p for p in C.AV.lib.list("provider") if not p.get("speaks")]
    ticks = "".join(f"""<label class="chip"><input type="checkbox" name="upd_m" value="{C._esc(p["id"])}" checked> {C._esc(p.get("name") or p["id"])}</label>""" for p in ps)
    return f"""<div id="cv-upd-f" class="cv-sec"><div class="row" style="flex-wrap:wrap">{ticks}</div><div class="row" style="flex-wrap:wrap"><label><input type="checkbox" name="upd_test" value="1" checked> one goes first:</label><select name="upd_first" class="module-select">{C._options([(p["id"], p.get("name") or p["id"]) for p in ps], "")}</select><label title="After its Magpie answers again: each program it built from source (llama.cpp and the like) brought to the ref it asks for (master: the newest) and built again, one after another, as Install again does. Running programs keep the build they started with until they next start."><input type="checkbox" name="upd_programs" value="1"> then their programs built from source</label>{_work_pick("upd_work")}{C._btn("Update these machines", "code_update_all", face=face_id, include="#cv-upd-f", confirm="Bring the ticked machines' Magpie to the source? A machine that refuses or is out of reach is skipped with nothing changed on it; you can stop waiting for any machine, or stop the update.")}<span class="cv-dim grow">In the background: leave this page if you like. Files only on a machine are kept there (removing them is done per machine).</span></div></div>"""

def updates_html(seen: int = 0) -> str:
    """The list of the last update of every machine (GET /code_updates), with a stop for each machine being waited for and for the whole update; it stops asking once the update has ended. Machines finished since the last poll (seen: how many it had been told of) are said to the page as changed, so their own parts (Magpie: up to date or behind) draw themselves again."""
    done = UPDATES.get("changed") or []
    told = f"""<script>window.cvChanged && cvChanged({json.dumps([f"machine:{i}" for i in done[seen:]])})</script>""" if done[seen:] else ""
    poll = f"""hx-get="{C._P}/code_updates?seen={len(done)}" hx-trigger="every 3s" hx-swap="outerHTML" """ if UPDATES.get("running") else ""
    doing = "".join(f"""<div class="row"><span class="chip">{C._esc(n)}</span><span class="cv-dim grow">{C._esc((UPDATES.get("phase") or {}).get(pid, ""))}</span>{C._btn("stop waiting", "code_update_stop", "ui-btn cv-small", pid=pid, title="Go on without it: with one-first, the next machine goes first")}</div>""" for pid, (n, _) in (UPDATES.get("doing") or {}).items())
    stop = C._btn("Stop the update", "code_update_stop", "ui-btn cv-danger", confirm="Stop the update? Machines not reached yet are left as they are.") if UPDATES.get("running") else ""
    return f"""<div id="cv-code-all" class="cv-sec" {poll}><div class="row"><b class="grow">Update of the machines{" - under way" if UPDATES.get("running") else ""}</b>{stop}</div>{f'<div class="cv-dim">working on:</div>{doing}' if doing else ""}<div class="mono cv-log pre-wrap">{C._esc(chr(10).join(UPDATES.get("notes", [])))}</div>{told}</div>""" if UPDATES else ""

async def _h_code_rollback(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin puts a machine's Magpie back.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try: got = await C.PROV.machine(p, "POST", "/node/code/rollback", {}, timeout=1900.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""{p.get("name") or p["id"]} is back to {got["back_to"]}""" + (f""", starting again ({got["by"]}).""" if got["restarting"] else ": start it again for that code to run.")))

async def _services(face_id: str, p: dict) -> str:
    """The programs the machine has running or has run (its services), each stopped, killed or started again from here, with its log; and the node itself restarted."""
    if (got := (r := await _heard(p, "services", "/services"))["value"]) is None: return C._dim(f"""its running programs: {C._esc(r["error"]) or "being asked ..."}""")
    svcs = got["services"]
    def row(sv):
        kw = {"face": face_id, "pid": p["id"], "asset": sv["name"], "svc": sv["name"]}
        up = sv["status"] not in ("stopped",) and not sv["status"].startswith("exited")
        said = " | ".join(x for x in (f"""{sv["rss_gb"]} GB""" if sv.get("rss_gb") else "", f"""{sv["active"]} working""" if sv.get("active") else "", f"""idle {sv["idle_s"]} s""" if up and sv.get("idle_s") is not None else "", C._esc(sv.get("detail", ""))[:120]) if x)
        acts = (C._btn("Stop", "program", verb="stop", title="Finishes what it is doing, then stops", **kw) + C._btn("Kill", "program", "ui-btn cv-danger", verb="kill", confirm=f"""Kill {sv["name"]} at once? Work under way is lost.""", **kw) if up else "") + C._btn("Restart" if up else "Start", "program", verb="restart" if up else "start", **kw) + C._btn("Log", "svc_log", pid=p["id"], svc=sv["name"])
        return f"""<div class="list-row"><div class="row"><span class="mono cv-key">{C._esc(sv["name"])}</span><span class="chip {"cv-ok" if sv["status"] == "up" else "cv-bad" if "fail" in sv["status"] or "exit" in sv["status"] else ""}">{C._esc(sv["status"])}</span><span class="cv-dim grow">{said}</span>{acts}</div><div id="cv-log-{C._esc(p["id"])}-{C._elid(sv["name"])}"></div></div>"""
    restart = C._btn("Restart the node", "program", "ui-btn cv-danger", face=face_id, pid=p["id"], asset="the node", node="1", confirm="Restart this machine's node? Work under way ends; what supervises it starts it again with its current settings and programs.")
    learned = C._btn("What llama learned", "learned", pid=p["id"], title="The limits the llama planner learned from failed starts, its launch and crash log, and its rules: each can be cleared from here") if any(sv["name"].startswith("llama") for sv in svcs) else ""
    return f"""<div class="cv-role"><div class="row"><b class="grow">Running programs</b><span class="cv-dim">{_as_of(r)}</span>{learned}{restart}</div>{"".join(row(sv) for sv in svcs) or C._dim("none has run since the node started")}<div id="cv-learn-{C._esc(p["id"])}"></div></div>"""

async def _h_svc_log(request, payload, imr):
    el = f"""cv-log-{payload["pid"]}-{C._elid(payload["svc"])}"""
    if payload.get("close"): return imr.oob("", el)
    try: tail = (await C.PROV.machine(C.AV.lib.get("provider", payload["pid"]), "GET", f"""/services/{quote(payload["svc"])}/log?n=60""", timeout=8.0))["tail"]
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), el)
    return imr.oob(f"""<div class="quote-block mono cv-log">{C._esc(chr(10).join(tail)) or "(empty)"}</div>{C._btn("Close", "svc_log", pid=payload["pid"], svc=payload["svc"], close="1")}""", el)

def _crash_html(c: dict) -> str:
    """The node's last llama-server crash in full: when, which model, how it ended and why (with the hint), what was planned and learned from it, and its last lines."""
    head = f"""<b>Last crash</b> {C._esc(c.get("t", ""))} - {C._esc(c.get("model", ""))} - {C._esc(c.get("kind", ""))} (exit {C._esc(c.get("returncode"))}){" - " + C._esc(c["hint"]) if c.get("hint") else ""}"""
    facts = "".join(f"""<div class="mono cv-dim pre-wrap" style="overflow-wrap:anywhere">{k}: {C._esc(json.dumps(c[k], ensure_ascii=False))}</div>""" for k in ("mode", "params", "est", "notes", "learned", "experiments", "env") if c.get(k) not in (None, "", [], {}))
    return f"""<div class="list-row">{head}{facts}<details><summary class="cv-dim">its last {len(c.get("tail") or [])} lines</summary><pre class="mono pre-wrap scroll-pane" style="max-height:50vh">{C._esc(chr(10).join(c.get("tail") or []))}</pre></details></div>"""

# --- Memory on one machine, from where a start was refused for it (a conversation's failed answer) ---

async def _free_html(p: dict, cid: str) -> str:
    """What holds a machine's memory now and what can be done about it, as shown inside a conversation: its memory (total, available, kept for the system, free to promise), each running program with what it holds and a Stop, memory reserved by programs being started, and the two settings that decide how far over a load may go (resources.reserve_gb, llama.overcommit_gb)."""
    el, b, sv = f"""cv-free-{C._elid(p["id"])}""", await C.PROV.machine(p, "GET", "/budget", timeout=10.0), (await C.PROV.machine(p, "GET", "/services", timeout=10.0))["services"]
    up = [x for x in sv if x["status"] not in ("stopped",) and not x["status"].startswith("exited")]
    rows = "".join(f"""<div class="row"><span class="mono grow">{C._esc(x["name"])} <span class="cv-dim">{C._esc(x.get("model") or "")} {(b["leases"].get(x["name"]) or {}).get("ram_gb", x.get("rss_gb") or 0):.1f} GB{", working" if x.get("active") else ""}</span></span>{C._btn("Stop", "free_memory", pid=p["id"], cid=cid, svc=x["name"], title="Finishes what it is doing, then stops and gives its memory back")}</div>""" for x in up)
    coming = "".join(f"""<div class="cv-dim">{C._esc(n)}: {l["ram_gb"]:.1f} GB reserved while it starts</div>""" for n, l in b["leases"].items() if not l.get("measured") and n not in {x["name"] for x in up})
    knobs = f"""cv-knobs-free-{C._elid(p["id"])}"""
    return f"""<div id='{el}' class="cv-sec"><div class="row"><b class="grow">Memory on {C._esc(p.get("name") or p["id"])}</b>{C._btn("Ask again", "free_memory", pid=p["id"], cid=cid, again="1")}{C._btn("Close", "free_memory", pid=p["id"], cid=cid, close="1")}</div><div class="cv-dim">{b["ram_total_gb"]} GB in all, {b["ram_avail_gb"]} GB available now, {b["reserve_gb"]} GB kept for the system, {b["free_to_promise_gb"]} GB free to promise to a program.</div>{rows or C._dim("No program of this node is running.")}{coming}<div class="row">{C._btn("How far over a load may go", "knobs_form", pid=p["id"], into=knobs, only="llama.overcommit_gb,resources.reserve_gb", title="llama.overcommit_gb: how many GB an estimate may be over the system-RAM budget before a start is refused (default 1). resources.reserve_gb: memory kept for the system (default 2.5).")}<span class="cv-dim grow">Then send your message again (its edit button, then Save and send again).</span></div><div id="{knobs}"></div></div>"""

async def _h_free_memory(request, payload, imr):
    """Memory on a machine, shown in a conversation below a refused start: drawn ("pid", "cid"), redrawn after a program is stopped ("svc"), or closed ("close")."""
    p, el = C.AV.lib.get("provider", payload["pid"]), f"""cv-free-{C._elid(payload["pid"])}"""
    if payload.get("close"): return imr.oob("", el, swap="delete")
    try:
        if payload.get("svc"):
            if not C._admin(request): return imr.oob(C._note("Only a portal admin stops a machine's programs.", True), "cv-msg")
            await C.PROV.machine(p, "POST", f"""/services/{quote(payload["svc"])}/stop""", {}, timeout=300.0)
            C._recheck(p["id"])
        html = await _free_html(p, payload["cid"])
    except C.PROV.ProviderError as e: html = f"""<div id='{el}'>{C._note(C.older(e, "say what holds its memory"), True)}</div>"""
    return imr.raw(html.replace(f"<div id='{el}'", f"<div id='{el}' hx-swap-oob='true'", 1)) if payload.get("svc") or payload.get("again") else imr.raw(f"""<div id="cm-msgs-{C._esc(payload["cid"])}" hx-swap-oob="beforeend">{html}</div>""")

async def _h_learned(request, payload, imr):
    """The llama planner's learned limits per model, its launch log and its rules (Magpie /api/optimizer/learned); forget one model's, all, or empty the log (asked first)."""
    el, p = f"""cv-learn-{payload["pid"]}""", C.AV.lib.get("provider", payload["pid"])
    if payload.get("close"): return imr.oob("", el)
    try:
        if payload.get("verb") == "forget": await C.PROV.machine(p, "POST", f"""/api/optimizer/forget?model={quote(payload.get("model") or "")}""", {}, timeout=10.0)
        if payload.get("verb") == "clear_log": await C.PROV.machine(p, "POST", "/api/optimizer/clear_log", {"confirm": True}, timeout=10.0)
        got = await C.PROV.machine(p, "GET", "/api/optimizer/learned", timeout=10.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "say what its planner learned"), True), el)
    kw = {"pid": payload["pid"]}
    rows = "".join(f"""<tr><td class="mono">{C._esc(m)}</td><td class="mono cv-dim pre-wrap" style="overflow-wrap:anywhere">{C._esc(json.dumps(v, ensure_ascii=False, indent=1))}</td><td>{C._btn("Forget", "learned", "ui-btn cv-small", verb="forget", model=m, confirm=f"Forget what was learned for {m}? Its next start is planned as for a model never started here.", **kw) if C._admin(request) else ""}</td></tr>""" for m, v in sorted(got["learned"].items()))
    crash = got.get("last_crash") or {}
    rules = f"""Rules: {C._esc(got["rules"])} ({C._esc(got["rules_from"])}) - learned limits reset by themselves when the rules or the machine change. Launch log: {C._esc(got["launch_log"])}, {got["launches"]} launch(es)."""
    acts = (C._btn("Forget all", "learned", "ui-btn cv-danger", verb="forget", confirm="Forget everything the planner learned on this machine (every model)?", **kw) + C._btn(f"""Empty the launch log ({got["launches"]})""", "learned", "ui-btn cv-danger", verb="clear_log", confirm="Empty this machine's launch and crash log? What was learned stays.", **kw)) if C._admin(request) else ""
    return imr.oob(f"""<div class="quote-block"><table class="cv-tbl"><tr><th>model</th><th>what it learned (budgets capped by earlier failures, faults, corrections)</th><th></th></tr>{rows or '<tr><td colspan="3" class="cv-dim">nothing learned: no start has failed since the machine or the rules last changed</td></tr>'}</table>{_crash_html(crash) if crash else ""}{C._dim(rules)}<div class="row">{acts}{C._btn("Close", "learned", close="1", **kw)}</div></div>""", el)

KINDS = ("text_models", "image_models", "audio_models", "loras")   # the kinds of model: folders inside models unless set on their own (the node's DIVISIONS)
ORDER = ("models",) + KINDS

async def _locations(face_id: str, p: dict) -> str:
    """Where the machine keeps each kind of thing (models, results, logs...), as it lists them, each changeable from here."""
    if (got := (r := await _heard(p, "locations", "/locations"))["value"]) is None: return C._dim(f"""where it keeps things: {C._esc(C.older(C.PROV.ProviderError(r["error"]), "list where it keeps things")) if r["error"] else "being asked ..."}""")
    locs = got["locations"]
    def row(l):
        free = f"""{l["disk"]["free_gb"]} of {l["disk"]["total_gb"]} GB free""" if l.get("disk") else ""
        inside = f"""inside {l["follows"]} (set it on its own with Change)""" if l.get("follows") else "set on its own" if l["name"] in KINDS else ""
        return f"""<div class="list-row" style="{"margin-left:1.5em" if l["name"] in KINDS else ""}"><div class="row" style="flex-wrap:wrap"><b class="cv-key">{C._esc(l["name"])}</b><span class="mono grow" style="overflow-wrap:anywhere">{C._esc(l["path"])}</span><span class="cv-dim">{C._esc(" | ".join(x for x in (inside, l.get("kind", ""), free, "" if l.get("exists") else "missing") if x))}</span>{C._btn("Change", "loc_form", face=face_id, pid=p["id"], name=l["name"], at=l["path"])}</div>{C._dim(C._esc(l["about"])) if l.get("about") else ""}<div id="cv-loc-{C._esc(p["id"])}-{C._esc(l["name"])}"></div></div>"""
    locs = sorted(locs, key=lambda l: (0, ORDER.index(l["name"])) if l["name"] in ORDER else (1, l["name"]))   # models, then its kinds under it, then the rest
    same = C._btn("Same places on other machines", "loc_copy_form", face=face_id, pid=p["id"], title="Gives other machines these places; under this machine's home folder means under each machine's own home")
    return f"""<div class="cv-role"><div class="row"><b class="grow">Where it keeps things</b>{same}</div>{C._dim("models is the one folder for every kind of model; each kind under it is a folder inside it unless set to a place of its own. A program sees a changed place at its next start. Moving takes what is there along, and waits for no work to be running.")}{"".join(row(l) for l in locs)}<div id="cv-locc-{C._esc(p["id"])}"></div></div>"""

def _portable(path: str, home: str) -> str: return "~" + path[len(home):] if home and (path == home or path.startswith(home.rstrip("/") + "/")) else path   # a place under the machine's home, written for any machine's home

async def _h_loc_copy_form(request, payload, imr):
    """Which places of this machine to give which other machines. Nothing is moved: the other machines only look there from now on."""
    p, el = C.AV.lib.get("provider", payload["pid"]), f"""cv-locc-{payload["pid"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: got = await C.PROV.machine(p, "GET", "/locations", timeout=8.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "list where it keeps things"), True), el)
    others = [o["p"] for o in await C._offers() if o["p"]["id"] != p["id"] and not o["p"].get("speaks")]
    tick = lambda name, v, label, on: f"""<label class="row"><input type="checkbox" name="{name}" value="{C._esc(v)}"{" checked" if on else ""}> {label}</label>"""
    locs = "".join(tick("loc", l["name"], f"""<b class="cv-key">{C._esc(l["name"])}</b> <span class="mono">{C._esc(_portable(l["path"], got.get("home", "")))}</span>""", True) for l in got["locations"])
    machines = "".join(tick("to", o["id"], C._esc(o.get("name") or o["id"]), False) for o in others) or C._dim("no other machine speaks the node contract")
    fid = f"""cv-locc-f-{payload["pid"]}"""
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false"><b>These places</b>{locs}<b>On these machines</b>{machines}{C._dim("~ is each machine's own home folder. Nothing is moved or deleted; a machine that kept something elsewhere still has it there.")}<div class="row"><span class="grow"></span>{C._btn("Use these places there", "loc_copy", face=payload["face"], pid=p["id"], include="#" + fid, confirm="Give the ticked machines these places?")}{C._btn("Close", "loc_copy_form", pid=p["id"], close="1")}</div></form>""", el)

async def _h_loc_copy(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes where machines keep things.", True), "cv-msg")
    listed = lambda k: [v for v in (payload.get(k) if isinstance(payload.get(k), list) else [payload[k]] if payload.get(k) else []) if v]
    try: got = await C.PROV.machine(C.AV.lib.get("provider", payload["pid"]), "GET", "/locations", timeout=8.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    places = {l["name"]: _portable(l["path"], got.get("home", "")) for l in got["locations"] if l["name"] in listed("loc")}
    if not (places and listed("to")): return imr.oob(C._note("Tick at least one place and one machine.", True), "cv-msg")
    done = []
    for pid in listed("to"):
        o = C.AV.lib.get("provider", pid)
        try: done.append(f"""{o.get("name") or pid}: """ + ", ".join([(await C.PROV.machine(o, "PUT", f"/locations/{n}", {"path": at}, timeout=60.0))["name"] for n, at in places.items()]))
        except C.PROV.ProviderError as e: done.append(f"""{o.get("name") or pid}: {C.older(e, "take a place given from here")}""")
    C._recheck()
    return await C._refresh(request, imr, payload["face"], C._note("Given: " + " | ".join(done)))

async def _h_loc_form(request, payload, imr):
    """A folder browser over the machine's own folders: each folder opens, "Use this folder" takes the one shown. Typing a path is possible, never needed."""
    p, name, el = C.AV.lib.get("provider", payload["pid"]), payload["name"], f"""cv-loc-{payload["pid"]}-{payload["name"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: b = await C.PROV.machine(p, "GET", "/browse?path=" + quote(payload.get("at") or ""), timeout=8.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "browse its folders"), True) + _typed(payload, p, name), el)
    go = lambda label, at: f"""<span class="chip cv-link" {C._act("loc_form", face=payload["face"], pid=p["id"], name=name, at=at)}>{label}</span>"""
    dirs = "".join(go(f"&#x1F4C1; {C._esc(d)}", b["path"].rstrip("/") + "/" + d) for d in b["folders"]) or C._dim("no folders inside")
    up = go("&#x2B06; up", b["parent"]) if b["parent"] else ""
    fid = f"cv-locf-{p['id']}-{name}"
    asked = C._dim(f"""{C._esc(b["asked"])} does not exist yet: shown from the nearest folder above it. "Use this folder" with the path below makes it.""") if b.get("asked") else ""
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false">{asked}<div class="row"><b class="mono grow">{C._esc(b["path"])}</b><span class="cv-dim">{b["disk"]["free_gb"]} GB free</span></div><div class="row" style="flex-wrap:wrap">{up}{dirs}</div><div class="row"><input name="path" class="module-select mono grow" value="{C._esc(b.get("asked") or b["path"])}" title="the folder shown; a path typed here is used instead"></div><label class="row" title="Merged into the new place. A file that is in both: the newer one is used and the older kept beside it under _replaced; nothing is deleted."><input type="checkbox" name="move" value="1"> take what is there now along (merged with what the new place holds)</label><div class="row"><span class="grow"></span>{C._btn("Use this folder", "loc_save", face=payload["face"], pid=p["id"], name=name, include="#" + fid, confirm="Change where this machine keeps " + name + "?")}{C._btn("Cancel", "loc_form", pid=p["id"], name=name, close="1")}</div></form>""", el)

def _typed(payload: dict, p: dict, name: str) -> str:
    """Where a machine cannot show its folders: the place typed instead, with the same choices as the browser."""
    fid = f"cv-locf-{p['id']}-{name}"
    return f"""<form class="cv-form" id="{fid}" onsubmit="return false"><div class="row"><input name="path" class="module-select mono grow" value="{C._esc(payload.get("at") or "")}" title="the folder on that machine"></div><label class="row" title="Merged into the new place. A file that is in both: the newer one is used and the older kept beside it under _replaced; nothing is deleted."><input type="checkbox" name="move" value="1"> take what is there now along (merged with what the new place holds)</label><div class="row"><span class="grow"></span>{C._btn("Use this folder", "loc_save", face=payload["face"], pid=p["id"], name=name, include="#" + fid, confirm="Change where this machine keeps it?")}{C._btn("Close", "loc_form", pid=p["id"], name=name, close="1")}</div></form>"""

async def _h_loc_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes where a machine keeps things.", True), "cv-msg")
    try: got = await C.PROV.machine(C.AV.lib.get("provider", payload["pid"]), "PUT", f"""/locations/{payload["name"]}""", {"path": payload["path"].strip(), "move": bool(payload.get("move"))}, timeout=3600.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    C._recheck(payload["pid"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""{payload["name"]} is now kept in {got["path"]}""" + (f""" ({got["moved"]} moved along""" + (f""", {got["same"]} already there""" if got.get("same") else "") + (f""", {got["replaced"]} differed: the newer is in place, the older kept in {got["kept_in"]}""" if got.get("replaced") else "") + ")" if "moved" in got else "") + ". Programs that use it see it at their next start."))

async def _h_machine_form(request, payload, imr):
    p, name = C.AV.lib.get("provider", payload["pid"]), payload["name"]
    m, el = await C.PROV.machine(p, "GET", f"/modules/{name}"), f"""cv-mod-{payload["pid"]}-{name}"""
    if payload.get("close"): return imr.oob("", el)
    plan = m["plan"]
    d = next((x for x in plan["drivers"] if x["driver"] == (payload.get("driver") or plan["driver"])), None)
    if not d: return imr.oob(C._note("No way to install it fits this machine: " + "; ".join(b["block"] for x in plan["drivers"] for b in x.get("blocks", [])), True), el)
    pick = C.BI.SettingField("driver", "How", "select", options=[(x["driver"], x["driver"] + (" - blocked here" if x.get("blocks") else "" if x.get("ok") else " - needs system packages")) for x in plan["drivers"]], hx_intent="corvid_machine_form", hx_target="none")
    opts = [C.BI.SettingField("opt_" + k, k, "select" if o.get("choices") else "text", options=[(str(ch), str(ch)) for ch in o.get("choices") or []] or None, hint=o.get("hint", "") + (" (has to be decided)" if k in d.get("decide", []) else "")) for k, o in d.get("options", {}).items()]
    ns = d.get("needs_system")
    sysnote = (C._note(f"""Needs {", ".join(ns["missing"])}: {ns["manager"] or "no package manager"} would install {" ".join(ns["packages"]) or "nothing known"}. """ + ("The machine allows system packages always (its node.json)." if ns["allowed"] else "Allow it for this install below, or install them there by hand."), False) + """<div class="row" style="flex-wrap:wrap"><label><input type="checkbox" name="sys_allow" value="1" checked> Let it install these system packages</label><input type="password" name="sys_pw" class="module-input" autocomplete="off" placeholder="administrator (sudo) password, if it asks" title="Given to sudo on that machine for this install only; never kept or logged. It travels to the machine as this request does: use the machine's TLS address (node.json bind tls_cert) on a network you do not trust."></div>""") if ns and ns.get("missing") else ""   # the portal admin manages the machines for their owner: allowed from here, per install
    blocks = C._note("Blocked here: " + "; ".join(b["block"] for b in d["blocks"]), True) if d.get("blocks") else ""
    values = {"driver": d["driver"], **{"opt_" + k: o.get("default", "") for k, o in d.get("options", {}).items()}}
    return imr.oob(f"""<form class="cv-form" id="cv-mf-{C._esc(name)}" onsubmit="return false"><input type="hidden" name="pid" value="{C._esc(p["id"])}"><input type="hidden" name="name" value="{C._esc(name)}">{C._group([pick, *opts]).render(values)}{sysnote}{blocks}<div class="row"><span class="grow"></span>{C._btn("Install", "machine_install", pid=p["id"], name=name, include="#cv-mf-" + name)}{C._btn("Cancel", "machine_form", pid=p["id"], name=name, close="1")}</div></form>""", el)

def _from_source(mods: list) -> list: return [m for m in mods if (m.get("installed") or {}).get("sources")]   # programs a machine built from source trees: what "update its programs" builds again

async def programs_update(p: dict) -> list:
    """Every program the machine built from source, installed again with the driver and options it has (the source brought to its ref and built again), one after another so two builds never share the machine's memory; each followed under its own row as Install again is. Answers the programs it started on; a machine that cannot be asked answers none, said in the update's notes when one is under way."""
    try: mods = _from_source((await C.PROV.machine(p, "GET", "/modules", timeout=20.0)).get("modules") or [])
    except C.PROV.ProviderError as e:
        if UPDATES.get("running"): UPDATES["notes"].append(f"""{p.get("name") or p["id"]}: its programs were not updated - {e}""")
        return []
    for m in mods:
        if (p["id"], m["name"]) in INSTALLS and not INSTALLS[(p["id"], m["name"])]["done"]: continue   # one already being installed is left to finish
        INSTALLS[(p["id"], m["name"])] = {"lines": [], "done": False, "ok": False}
        await _install_task(p, m["name"], {"driver": m["installed"].get("driver") or "", "options": m["installed"].get("options") or {}, "system": {"allow": True}})   # asked by a portal admin: system packages a rebuild newly needs may be added (a machine whose sudo asks for a password says so; Install again on its row takes one)
        if UPDATES.get("running"): UPDATES["notes"].append(f"""{p.get("name") or p["id"]}: {m.get("label") or m["name"]} {"built again from " + ", ".join(m["installed"]["sources"]) if INSTALLS[(p["id"], m["name"])]["ok"] else "could not be built again - its row on the machine's page has the lines"}""")
    return [m["name"] for m in mods]

async def _h_programs_update(request, payload, imr):
    """One machine's programs built from source, installed again in the background (programs_update)."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin installs on a machine.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    _TASKS.add(t := asyncio.create_task(programs_update(p)))
    t.add_done_callback(_TASKS.discard)
    await asyncio.sleep(1.5)   # the first install has begun: its row shows it
    return await C._refresh(request, imr, payload["face"], C._note(f"""{p.get("name") or p["id"]}: its programs built from source are being installed again, one after another - each row below follows its own."""))

async def _install_task(p: dict, name: str, body: dict):
    rec = INSTALLS[(p["id"], name)]
    try:
        async for ln in C.PROV.machine_lines(p, f"/modules/{name}/install", body):
            rec["lines"].append(ln.get("line") or ln.get("status") or ln.get("error") or json.dumps(ln))
            rec["ok"] = rec["ok"] or ln.get("status") in ("active", "success")   # "success": the install went through (a module already active is not activated again); "active": it was also turned on
    except C.PROV.ProviderError as e: rec["lines"].append(str(e))
    rec["done"] = True
    C._recheck(p["id"])

async def _h_machine_seen(request, payload, imr):
    """A finished install's lines put away."""
    INSTALLS.pop((payload["pid"], payload["name"]), None)
    return imr.oob("", f"""cv-mod-{payload["pid"]}-{payload["name"]}""")

def _opens(fn):
    """A handler that also notes which machine the person is working on."""
    async def go(request, payload, imr):
        if payload.get("pid"): OPEN[C._user(request)] = payload["pid"]
        return await fn(request, payload, imr)
    return go

async def _h_machine_install(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin installs on a machine.", True), "cv-msg")
    p, name = C.AV.lib.get("provider", payload["pid"]), payload["name"]
    if not ((p["id"], name) in INSTALLS and not INSTALLS[(p["id"], name)]["done"]):
        INSTALLS[(p["id"], name)] = {"lines": [], "done": False, "ok": False}
        asyncio.create_task(_install_task(p, name, {"driver": payload.get("driver", ""), "options": {k[4:]: v for k, v in payload.items() if k.startswith("opt_") and v != ""}, **({"system": {"allow": True, "password": payload.get("sys_pw", "")}} if payload.get("sys_allow") else {})}))
    return imr.oob(install_view(p["id"], name), f"cv-mod-{p['id']}-{name}")

async def _h_machine_act(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes what a machine runs.", True), "cv-msg")
    p, name, verb = C.AV.lib.get("provider", payload["pid"]), payload["name"], payload["verb"]
    try: await (C.PROV.machine(p, "DELETE", f"/modules/{name}?confirm=1") if verb == "remove" else C.PROV.machine(p, "POST", f"/modules/{name}/{verb}"))
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"{name}: {verb} done."))

def init(c):
    global C
    C = c
    C.AV.seen.listeners.append(seen_said)
    C.IM.scripts.update({f"corvid_{k}": [_opens(fn)] for k, fn in {"machine_seen": _h_machine_seen, "machine_form": _h_machine_form, "machine_install": _h_machine_install, "machine_act": _h_machine_act, "svc_log": _h_svc_log, "learned": _h_learned, "loc_form": _h_loc_form, "loc_save": _h_loc_save, "loc_copy_form": _h_loc_copy_form, "loc_copy": _h_loc_copy, "code_source": _h_code_source, "code_update_all": _h_code_update_all, "code_update_stop": _h_code_update_stop, "code_pull": _h_code_pull, "code_form": _h_code_form, "code_update": _h_code_update, "code_rollback": _h_code_rollback, "programs_update": _h_programs_update, "knobs_form": _h_knobs_form, "knobs_save": _h_knobs_save, "free_memory": _h_free_memory}.items()})   # corvid.py routes /install (an install's progress, polled) to install_view above
