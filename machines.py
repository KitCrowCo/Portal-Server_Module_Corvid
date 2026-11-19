"""machines.py - Corvid's Machines panel, beside corvid.py: each provider's own programs as it lists them (what is active, installed, could be installed, and doing it), the programs it has running (stop, kill, start again, log), the node's restart, where it keeps things (a folder browser over the machine's own folders, and the same places given to other machines), and Magpie's own code (compared with the portal's copy, brought up to date, or back to the version before).
Everything shown is the machine's own answer; nothing here names a program.
C is a live view of corvid.py's globals, set when Corvid starts."""
import os, json, base64, asyncio, hashlib
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
        return f"""<div class="list-row"><div class="row"><b>{C._esc(m.get("label") or name)}</b><span class="chip {"cv-ok" if st_ == "active" else "cv-mid" if st_ in ("installed", "updating") else ""}">{C._esc(st_)}</span><span class="cv-dim grow">{C._esc(", ".join(m.get("provides") or []))}</span>{acts}</div>{err}{behind}<div id="cv-mod-{C._esc(pid)}-{C._esc(name)}">{live}</div></div>"""
    order = {"active": 0, "updating": 1, "installed": 1}
    rows = "".join(row(m) for m in sorted(d["modules"], key=lambda m: (order.get(m["state"], 2), m["name"])))
    on = sum(m["state"] == "active" for m in d["modules"])
    return f"""<details class="cv-machine"{" open" if opened else ""}><summary><b>{C._esc(pname)}</b> <span class="cv-dim">{C._esc(p["url"])} | {on} active, {sum(m["state"] == "installed" for m in d["modules"])} installed, {len(d["modules"])} known | </span>{age_chip(face_id, p["id"], mods[2])}</summary>{said}{await _code(face_id, p, src, admin)}{rows}{await _services(face_id, p)}{await _locations(face_id, p)}<div class="cv-role"><div class="row"><b class="grow">Its settings</b>{C._btn("Show", "knobs_form", face=face_id, pid=p["id"], title="Every value this machine lets a manager set, by program")}</div><div id="cv-knobs-{C._esc(p["id"])}"></div></div></details>"""

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
    if k.get("choices") or k["type"] == "boolean": return C.BI.SettingField(k["key"], k.get("label") or k["name"], "select", options=[("", _AUTO), *((json.dumps(c) if isinstance(c, bool) else str(c), "yes" if c is True else "no" if c is False else str(c)) for c in (k.get("choices") or [True, False]))], hint=said)
    return C.BI.SettingField(k["key"], k.get("label") or k["name"], "json" if k["type"] in ("list", "object") else "text", default=[] if k["type"] == "list" else {} if k["type"] == "object" else "", hint=said)

def _knob_value(k: dict, raw):
    """A form value as the setting's type; nothing given is None (the machine's own value)."""
    if raw in ("", None, [], {}): return None
    if k["type"] == "boolean": return raw in (True, "true")
    return int(float(raw)) if k["type"] == "integer" else float(raw) if k["type"] == "number" else raw

async def _h_knobs_form(request, payload, imr):
    p, el = C.AV.lib.get("provider", payload["pid"]), f"""cv-knobs-{payload["pid"]}"""
    if payload.get("close"): return imr.oob("", el)
    try: knobs = (await C.PROV.machine(p, "GET", "/knobs", timeout=10.0))["knobs"]
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "list its settings"), True), el)
    shown = lambda k: json.dumps(k["value"]) if isinstance(k["value"], bool) else k["value"]
    groups = "".join(f"""<details class="sec"><summary><b>{C._esc(m)}</b> <span class="cv-dim">{len(ks)} settings{", " + str(sum(1 for k in ks if k["value"] is not None)) + " set" if any(k["value"] is not None for k in ks) else ""}</span></summary>{C._group([_knob_field(k) for k in ks]).render({k["key"]: shown(k) for k in ks if k["value"] is not None}, name_prefix="k_")}</details>""" for m, ks in {m: [k for k in knobs if k["module"] == m] for m in dict.fromkeys(k["module"] for k in knobs)}.items())
    fid = f"""cv-knobs-f-{payload["pid"]}"""
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false">{C._dim("A value left empty is the machine's own. Only what you change is sent; the machine keeps the version before each change.")}{groups}<div class="row"><span class="grow"></span>{C._btn("Save what changed", "knobs_save", face=payload["face"], pid=p["id"], include="#" + fid)}{C._btn("Close", "knobs_form", pid=p["id"], close="1")}</div></form>""", el)

async def _h_knobs_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes a machine's settings.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try:
        knobs = (await C.PROV.machine(p, "GET", "/knobs", timeout=10.0))["knobs"]
        got = C._group([_knob_field(k) for k in knobs]).parse(payload, "k_")
        changed = {k["key"]: v for k in knobs if f"""k_{k["key"]}""" in payload and (v := _knob_value(k, got[k["key"]])) != (None if k["value"] in ("", [], {}) else k["value"])}   # an empty value that stays empty is no change
        for key, v in changed.items(): await C.PROV.machine(p, "PATCH", "/settings", {"path": key, "value": v, "source": f"{C._user(request)} from the portal"}, timeout=30.0)
    except (C.PROV.ProviderError, C.BI.SettingsError, ValueError) as e: return imr.oob(C._note(f"Not all saved: {e}", True), "cv-msg")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""{p.get("name") or p["id"]}: """ + (", ".join(f"{k} = {C._shown(v) if v is not None else 'its own again'}" for k, v in changed.items()) if changed else "nothing was changed") + "."))

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
    return imr.oob(f"""<form class="cv-form" id="{fid}" onsubmit="return false">{route}{lst("replaced", d["changed"])}{lst("new", d["new"])}{lst("only on this machine", d["only_there"])}{extra}{C._dim("The machine applies it to a copy first; it is refused, with nothing changed, if that copy does not compile and start. Then it keeps what it had and starts again with the new code.")}<div class="row"><span class="grow"></span>{C._btn("Update", "code_update", face=payload["face"], pid=p["id"], include="#" + fid, confirm="Bring this machine's Magpie up to date now? Work under way on it ends; it starts again by itself.")}{C._btn("Close", "code_form", pid=p["id"], close="1")}</div></form>""", el)

async def _update_one(p: dict, src: dict, remove: bool, who: str) -> tuple:
    """One machine's Magpie brought to the source: what differs is sent, the machine checks a copy and starts again with it. Answers (what was done, the fingerprint it will run with - "" when nothing was sent or it does not start again by itself); raises ProviderError when the machine refuses or cannot be reached (nothing changed there then)."""
    d = await asyncio.to_thread(_differ, src, await C.PROV.machine(p, "GET", "/node/code", timeout=20.0))
    if not (d["changed"] or d["new"] or (remove and d["only_there"])): return f"""{p.get("name") or p["id"]}: already the same as the source.""", ""
    files = {r: base64.b64encode((src["folder"] / r).read_bytes()).decode() for r in [*d["changed"], *d["new"]]}
    got = await C.PROV.machine(p, "PUT", "/node/code", {"files": files, "remove": d["only_there"] if remove else [], "from": f"""{src["tool"]} ({src.get("git") or "uploaded"}), by {who} from the portal"""}, timeout=1900.0)
    return f"""{p.get("name") or p["id"]}: {len(got["replaced"])} replaced, {len(got["added"])} new, {len(got["removed"])} removed ({got["before"]} -> {got["after"]}). """ + (f"""It is starting again ({got["by"]}).""" if got["restarting"] else got.get("note", "")) + (f""" {got["requirements"]}.""" if got.get("requirements") else ""), got["after"] if got["restarting"] else ""

async def _h_code_update(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin updates a machine's Magpie.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try: said, _ = await _update_one(p, _source(), bool(payload.get("remove")), C._user(request))
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "take its own code"), True), f"""cv-code-{p["id"]}""")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(said))

UPDATES: dict = {}   # the last "Update every machine": {"running", "notes"}, shown on Settings > Machines while it runs and after
_TASKS = set()   # its task: the event loop holds tasks only weakly

async def _back(p: dict, after: str, wait_s: float = 240.0) -> bool:
    """True once the machine answers again running the new code (its fingerprint is after); False if it has not within wait_s. The old process may still answer for a moment, so an answer alone is not enough."""
    for _ in range(int(wait_s / 5)):
        await asyncio.sleep(5)
        try:
            if (await C.PROV.machine(p, "GET", "/node/code", timeout=5.0)).get("fingerprint") == after: return True
        except C.PROV.ProviderError: pass
    return False

async def _update_noted(p: dict, src: dict, who: str) -> str:
    """One machine of an update of every machine, its outcome noted on the list: "same" (already the source), "updated" (answering again with the new code), "refused" (it refused or could not be reached before anything changed there: safe to go on with the others), "lost" (it took the new code and has not answered with it for 4 minutes)."""
    name = p.get("name") or p["id"]
    try: said, after = await _update_one(p, src, False, who)
    except C.PROV.ProviderError as e:
        UPDATES["notes"].append(f"""{name}: not updated, nothing changed there - {e}""")
        return "refused"
    UPDATES["notes"].append(said)
    if after and not await _back(p, after):
        UPDATES["notes"].append(f"""{name}: took the new code and has not answered with it for 4 minutes. Its earlier code is kept on it (Back to the version before).""")
        return "lost"
    C._recheck(p["id"])
    return "updated" if after else "same"

async def _h_code_update_all(request, payload, imr):
    """Every Magpie machine brought to the source in the background. First one machine at a time until one answers again with the new code (or already runs it): that shows the source starts. Then all the others at once. A machine that refuses or cannot be reached changes nothing and does not stop the others; one that takes the new code and does not come back stops the update while it is still the first (the source itself may be at fault), and is only noted once the source has been shown to start."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin updates the machines' Magpie.", True), "cv-msg")
    if UPDATES.get("running"): return imr.oob(C._note("An update of every machine is already under way: see its list on this page.", True), "cv-msg")
    src, who, ps = _source(), C._user(request), [p for p in C.AV.lib.list("provider") if not p.get("speaks")]
    UPDATES.clear()
    UPDATES.update(running=True, notes=[f"""{len(ps)} machine(s) from {src["tool"]}: one first, then the rest together"""])
    async def go():
        left = list(ps)
        while left:
            got = await _update_noted(left.pop(0), src, who)
            if got == "lost":
                UPDATES["notes"].append(f"""Stopped: the first machine to take this code did not come back with it. The {len(left)} not reached were left as they were.""")
                break
            if got in ("updated", "same"):
                if left: UPDATES["notes"].append(f"""The source starts: the other {len(left)} together now.""")
                outcomes = await asyncio.gather(*(_update_noted(q, src, who) for q in left))
                refused, lost = outcomes.count("refused"), outcomes.count("lost")
                UPDATES["notes"].append(f"""done{f", {refused} refused or out of reach (nothing changed on them: update them again later)" if refused else ""}{f", {lost} did not come back" if lost else ""}""")
                break
        else: UPDATES["notes"].append("done: no machine could be updated (each refused or was out of reach; nothing changed on any)")
        UPDATES["running"] = False
    _TASKS.add(task := asyncio.create_task(go()))
    task.add_done_callback(_TASKS.discard)
    return await C._refresh(request, imr, payload["face"], C._note("Updating every machine: the list on this page follows it."))

def _all_row(face_id: str) -> str: return f"""<div class="row">{C._btn("Update every machine", "code_update_all", face=face_id, confirm="Bring every machine's Magpie to the source? One goes first; once it answers with the new code the others go together. A machine that refuses or is out of reach is skipped with nothing changed on it.") if not UPDATES.get("running") else ""}<span class="cv-dim grow">In the background: leave this page if you like. Files only on a machine are kept there (removing them is done per machine).</span></div>"""

def updates_html() -> str:
    """The list of the last update of every machine (GET /code_updates); it stops asking once the update has ended."""
    poll = f"""hx-get="{C._P}/code_updates" hx-trigger="every 3s" hx-swap="outerHTML" """ if UPDATES.get("running") else ""
    return f"""<div id="cv-code-all" class="cv-sec" {poll}><b>Update of every machine{" - under way" if UPDATES.get("running") else ""}</b><div class="mono cv-log pre-wrap">{C._esc(chr(10).join(UPDATES.get("notes", [])))}</div></div>""" if UPDATES else ""

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
    return f"""<div class="cv-role"><div class="row"><b class="grow">Running programs</b><span class="cv-dim">{_as_of(r)}</span>{restart}</div>{"".join(row(sv) for sv in svcs) or C._dim("none has run since the node started")}</div>"""

async def _h_svc_log(request, payload, imr):
    el = f"""cv-log-{payload["pid"]}-{C._elid(payload["svc"])}"""
    if payload.get("close"): return imr.oob("", el)
    try: tail = (await C.PROV.machine(C.AV.lib.get("provider", payload["pid"]), "GET", f"""/services/{quote(payload["svc"])}/log?n=60""", timeout=8.0))["tail"]
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), el)
    return imr.oob(f"""<div class="quote-block mono cv-log">{C._esc(chr(10).join(tail)) or "(empty)"}</div>{C._btn("Close", "svc_log", pid=payload["pid"], svc=payload["svc"], close="1")}""", el)

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
    sysnote = C._note(f"""Needs {", ".join(ns["missing"])}: {ns["manager"] or "no package manager"} would install {" ".join(ns["packages"]) or "nothing known"}. """ + ("The machine's owner allows system packages." if ns["allowed"] else "Not allowed on that machine: install them there by hand, or allow system packages in its node.json."), not ns["allowed"]) if ns and ns.get("missing") else ""
    blocks = C._note("Blocked here: " + "; ".join(b["block"] for b in d["blocks"]), True) if d.get("blocks") else ""
    values = {"driver": d["driver"], **{"opt_" + k: o.get("default", "") for k, o in d.get("options", {}).items()}}
    return imr.oob(f"""<form class="cv-form" id="cv-mf-{C._esc(name)}" onsubmit="return false"><input type="hidden" name="pid" value="{C._esc(p["id"])}"><input type="hidden" name="name" value="{C._esc(name)}">{C._group([pick, *opts]).render(values)}{sysnote}{blocks}<div class="row"><span class="grow"></span>{C._btn("Install", "machine_install", pid=p["id"], name=name, include="#cv-mf-" + name)}{C._btn("Cancel", "machine_form", pid=p["id"], name=name, close="1")}</div></form>""", el)

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
        asyncio.create_task(_install_task(p, name, {"driver": payload.get("driver", ""), "options": {k[4:]: v for k, v in payload.items() if k.startswith("opt_") and v != ""}}))
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
    C.IM.scripts.update({f"corvid_{k}": [_opens(fn)] for k, fn in {"machine_seen": _h_machine_seen, "machine_form": _h_machine_form, "machine_install": _h_machine_install, "machine_act": _h_machine_act, "svc_log": _h_svc_log, "loc_form": _h_loc_form, "loc_save": _h_loc_save, "loc_copy_form": _h_loc_copy_form, "loc_copy": _h_loc_copy, "code_source": _h_code_source, "code_update_all": _h_code_update_all, "code_pull": _h_code_pull, "code_form": _h_code_form, "code_update": _h_code_update, "code_rollback": _h_code_rollback, "knobs_form": _h_knobs_form, "knobs_save": _h_knobs_save}.items()})   # corvid.py routes /install (an install's progress, polled) to install_view above
