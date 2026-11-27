"""collab_view.py - Tessa's Collab: the AI account's one stream (right), the collab projects set before it (left) and the loaded project's workspace (middle).
The stream: one conversation per AI account (an identity names its account; none named: the portal's AI account, AI_USER or "aviary"), kept in <data>/streams/stream-<account>.json and never switched or emptied. To the chat interface it is a conversation like any other. What differs: every message says who it was with ("with") and what was being worked on ("project"); a turn is given the stream as the identity's recall says (recall_last: only that many of the latest messages, 0 or none: all, the pipeline fits them to its window; recall_within_partner, on unless set off: with someone who is not a primary user, only what was said with them); a message taken out is kept under "earlier"; asking again from an earlier point is refused once someone else has spoken since. A person who is not a primary user sees only their own part of a stream.
Who may talk with an AI account: the grant use on ai:<account> (scope service); a primary user may.
A collab project: a file <data>/projects/<user>/<id>.json of pointers, not copies: its tabs (each shows a chat, a run or another face's view, and may hold tabs of its own), what Tessa is told about it ("context"), how far Tessa may reach its chats ("tessa": none / see / take part / organize, asked as grants on conversation:<user>/<cid>, "tessa_reads": how many of each chat's latest messages it is given when it may see them) and other grants it asks for ("grants": [{on, act}]). Loading a project sets it before the AI: a sub-user <account>/collab-<id> is made for the load, bound by the account and by the person loading it, and given what the project asks; loading another ends it. Taking out a project or a tab removes the pointer only.
Every key is optional: a missing one leaves its part empty. Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import os, json, time, uuid

C = None
AI_USER = os.getenv("AI_USER", "aviary")   # the portal's AI account (made at start by the core, main.py)
REACH = {"none": "", "see": "see", "take part": "use", "organize": "edit"}   # how far Tessa may reach a project's chats -> the act asked on each
LOADED = {}   # (person, face) -> the sub-user made for the project loaded there

def init(c):
    global C
    C = c
    C.IM.scripts.update({f"corvid_proj_{n}": [fn] for n, fn in (("new", _h_new), ("load", _h_load), ("meta", _h_meta), ("meta_save", _h_meta_save), ("add", _h_add), ("untab", _h_untab))})

def S() -> dict: return C.ENV["services"]["scope"]

# --- The stream ---

def is_stream(cid: str) -> bool: return cid.startswith("stream-")
def path(cid: str): return C.DATA / "streams" / f"{cid}.json"
def _ident(iid: str) -> dict: return C.AV.lib.get("identity", iid) if iid and C.AV.lib.has("identity", iid) else {}
def account(iid: str) -> str: return _ident(iid).get("account") or AI_USER
def _spec(face: dict) -> dict: return next((sp for lay in (face.get("views") or [face]) for region in ("right", "main", "left") for sp in lay.get(region, []) if sp["panel"] == "stream"), {})
def may_use(user: str, acct: str) -> tuple: return S()["why"](user, f"ai:{acct}", "use")
def files(user: str) -> list: return [f for f in (C.DATA / "streams").glob("*.json") if may_use(user, f.stem[len("stream-"):])[0]]   # the streams this person may be in

def stream_of(face: dict):
    """The stream a face shows (the account of its stream panel's identity), made the first time it is asked for; None for a face without a stream panel."""
    if not (sp := _spec(face)): return None
    cid = f"""stream-{account(sp.get("identity", ""))}"""
    if path(cid).exists(): return json.loads(path(cid).read_text())
    t = {"id": cid, "face": face["id"], "identity": sp.get("identity", ""), "ai": account(sp.get("identity", "")), "title": _ident(sp.get("identity", "")).get("name") or cid, "messages": [], "pins": {}, "pending": "", "changed": time.time()}
    path(cid).parent.mkdir(parents=True, exist_ok=True)
    C.BI.write_json_atomic(path(cid), t)
    return t

def _all(t: dict, user: str) -> bool: return not is_stream(t["id"]) or S()["admin"](user)
def shown(t: dict, user: str) -> list:
    """What a person sees of a conversation: all of it; of a stream, only what was said with them unless they are a primary user, and only its latest part (identity "show_last", default 200 messages) - a stream never ends, and the page draws what it shows. The stream itself keeps everything; recall decides what a turn is given."""
    if not is_stream(t["id"]): return t["messages"]
    ms = t["messages"] if _all(t, user) else [m for m in t["messages"] if m.get("with") == user]
    return ms[-int(_ident(t.get("identity", "")).get("show_last") or 200):]
def recalled(t: dict, user: str) -> list:
    """The messages a turn is given: all of a conversation; of a stream, what the identity's recall says."""
    if not is_stream(t["id"]): return t["messages"]
    i = _ident(t.get("identity", ""))
    ms, last = t["messages"] if _all(t, user) or not i.get("recall_within_partner", True) else [m for m in t["messages"] if m.get("with") == user], int(i.get("recall_last") or 0)
    return ms[-last:] if last else ms

async def tags(request, t: dict) -> dict:
    """What a person's message in a stream carries: who said it and the project loaded where it was said."""
    if not is_stream(t["id"]): return {}
    return {"with": C._user(request), "project": (C._tabs(await C.TM._load(request))["tabs"].get(t["face"]) or {}).get("project", "")}
def answer_tags(t: dict) -> dict: return {k: v for k, v in next((m for m in reversed(t["messages"]) if m["role"] == "user"), {}).items() if k in ("with", "project")} if is_stream(t["id"]) else {}   # an answer carries what the message it answers carries
def cut_refused(t: dict, i: int, user: str) -> str: return "Someone else has spoken in this stream since then: say it again as a new message instead." if is_stream(t["id"]) and any(m.get("with", user) != user for m in t["messages"][i + 1:]) else ""

def with_project(t: dict, user: str, params: dict, inputs: dict) -> dict:
    """A stream turn's inputs with the project it is about added to its standing instructions ("system"): the project's title, what Tessa is told about it, and the latest messages of the chats Tessa may see there. Other turns, and pipelines without standing instructions, are left as they are."""
    if not (is_stream(t["id"]) and "system" in params and (p := _proj(user, answer_tags(t).get("project", "")))): return inputs
    seen = "".join(_seen_chat(user, t["ai"], p, cid) for cid in chats_of(p))
    return {**inputs, "system": f"""{inputs.get("system", "")}\n\nWhat we are working on now: {p.get("title", "")}\n{p.get("context", "")}{seen}""".strip()}

def _seen_chat(user: str, acct: str, p: dict, cid: str) -> str:
    """A project chat's latest messages for the AI, where its sub-user for the project may see the chat; else nothing."""
    if not ((C._talk_dir(user) / f"{cid}.json").exists() and S()["may"](f"""{acct}/collab-{p["id"]}""", f"conversation:{user}/{cid}", "see")): return ""
    t, n = C._talk(user, cid), int(p.get("tessa_reads") or 6)
    lines = "\n".join(f"""{m["role"]}: {m["content"]}""" for m in t["messages"][-n:] if m["role"] in ("user", "assistant"))
    return f"""\n\nThe project's chat "{t["title"]}", its latest messages:\n{lines}"""

async def p_stream(c) -> str:
    """The AI account's one stream, as the portal's chat interface: who it is, what is loaded before it, its messages (a person who is not a primary user: only their own part)."""
    t, user = stream_of(c.face), C._user(c.request)
    ok, how = may_use(user, t["ai"])
    if not ok: return C._note(f"""You may not talk with {t["title"]} here ({how}). Talking with it is the grant use on ai:{t["ai"]}, given in Settings > Users and scopes.""", True)
    head = f"""<b>{C._esc(t["title"])}</b> {C.BESIDE["status_view"].prepare(c.face["id"], t["id"])}<div class="cv-dim" id="cv-stream-on-{c.face["id"]}">{_on(_proj(user, c.tab.get("project", "")))}</div>"""
    return f"""<div class="cv-chat" style="height:80vh">{C._cm(c.face["id"]).shell(t["id"], C._acted({**t, "messages": shown(t, user)}), user=c.request.state.user, header_html=head, is_working=C._working(t), stop_intent=C._stop_vals(t["id"]), think=C._think_now(C._conv_spec(C.AV.lib.get("face", t["face"])), t) if C.AV.lib.has("face", t.get("face", "")) else None, extra_footer=C.MEDIA.attach_html(t["id"]))}</div>"""

def _on(p: dict) -> str: return f"""working on: {C._esc(p.get("title") or p["id"])}""" if p else "no project loaded: nothing in particular is set before it"   # the line under the stream's name

# --- Projects (files of pointers) ---

def _dir(user: str): return C.DATA / "projects" / user
def _proj(user: str, pid: str) -> dict: return json.loads(f.read_text()) if pid and (f := _dir(user) / f"{pid}.json").exists() else {}
def _save(user: str, p: dict): C.BI.write_json_atomic(_dir(user) / f"""{p["id"]}.json""", {**p, "changed": time.time()})
def _projects(user: str) -> list: return sorted((json.loads(f.read_text()) for f in _dir(user).glob("*.json")), key=lambda p: p.get("changed", 0), reverse=True)
def _walk(tabs: list):
    for tb in tabs or []:
        yield tb
        yield from _walk(tb.get("tabs"))
def chats_of(p: dict) -> list: return [tb["show"]["chat"] for tb in _walk(p.get("tabs")) if (tb.get("show") or {}).get("chat")]
def _asks(user: str, p: dict) -> list: return [(f"conversation:{user}/{cid}", REACH[p.get("tessa") or "none"]) for cid in chats_of(p) if REACH.get(p.get("tessa") or "none")] + [(g["on"], g["act"]) for g in p.get("grants") or [] if g.get("on") and g.get("act")]
def _acct(face_id: str) -> str: return (stream_of(C.AV.lib.get("face", face_id)) or {}).get("ai", AI_USER)
def _sid(acct: str, pid: str) -> str: return f"{acct}/collab-{pid}"

def load(user: str, face_id: str, p: dict) -> list:
    """The project set before the face's AI account: the sub-user of an earlier load here is ended, one is made for this project (bound by the account and by the person) and given what the project asks. Answers [(thing, act, why not)] for each ask the person could not give. An empty p only ends the earlier load."""
    sc, acct = S(), _acct(face_id)
    if (old := LOADED.pop((user, face_id), "")) and old in sc["subs"](): sc["end"](acct, old)
    if not p: return []
    sid = sc["spawn"](acct, f"""collab-{p["id"]}""", also=[user], note=f"""project {p.get("title", "")}""")
    LOADED[(user, face_id)] = sid
    refused = []
    for on, act in _asks(user, p):
        try: sc["grant"](user, sid, on, act, note=f"""project {p.get("title", "")}""")
        except PermissionError as e: refused.append((on, act, str(e)))
    return refused

def _ensure(user: str, face_id: str, p: dict):
    """The project shown is the one loaded (after a restart, live sub-users are gone: it is loaded again)."""
    if LOADED.get((user, face_id)) != _sid(_acct(face_id), p["id"]) or _sid(_acct(face_id), p["id"]) not in S()["subs"](): load(user, face_id, p)
def _reload(user: str, face_id: str, p: dict):
    if LOADED.get((user, face_id)) == _sid(_acct(face_id), p["id"]): load(user, face_id, p)   # what it asks changed: given again

async def _open(request, imr, face_id: str, pid: str, at: str = ""):
    """The face shown with the project loaded there and its tab at the path at ("0.2": the third tab under the first); the view that holds the workspace."""
    face = C.AV.lib.get("face", face_id)
    vid = next((v["id"] for v in face.get("views", []) if any(sp["panel"] == "workspace" for r in ("main", "left", "right") for sp in v.get(r, []))), "")
    return await C.IM.scripts["corvid_open_tab"][0](request, {"id": face_id, "project": pid, "ptab": at, **({"view": vid} if vid else {})}, imr)

async def p_projects(c) -> str:
    """The person's collab projects in folders, newest first, with a filter; a row loads its project, its &#x22EF; renames, moves, sets what Tessa is told and may reach, or takes it out."""
    user, cur = C._user(c.request), c.tab.get("project", "")
    ps = _projects(user)
    def row(p):
        info = C._dim(f"""{sum(1 for _ in _walk(p.get("tabs")))} tab(s) - Tessa: {p.get("tessa") or "none"} - {C._when(p.get("changed"))}""")
        return f"""<div class="list-row row cv-talk{" cv-on" if p["id"] == cur else ""}" id="cv-proj-row-{p["id"]}" data-find="{C._esc((p.get("title", "") + " " + p.get("folder", "")).lower())}"><span class="grow cv-link" {C._act("proj_load", face=c.host, pid=p["id"])}>{C._esc(p.get("title") or p["id"])}{info}</span>{C._btn("&#x22EF;", "proj_meta", "ui-btn cv-small", title="Rename, put in a folder, what Tessa is told and may reach, take out", face=c.host, pid=p["id"])}</div>"""
    folders = sorted({p["folder"] for p in ps if p.get("folder")}, key=str.lower)
    fold = lambda name: f"""<details class="cv-folder list-row" id="{C._elid("cv-pfold-" + name)}" {"open" if any(p["id"] == cur and p.get("folder") == name for p in ps) else ""}><summary class="row"><b class="grow">&#x1F4C1; {C._esc(name)}</b><span class="cv-dim">{sum(p.get("folder") == name for p in ps)}</span></summary>{"".join(row(p) for p in ps if p.get("folder") == name)}</details>"""
    unload = C._btn("Load none", "proj_load", "ui-btn cv-small", title="Nothing in particular set before Tessa", face=c.host, pid="") if cur else ""
    return f"""<div class="cv-talks"><div class="row">{C._btn("New project", "proj_new", face=c.host)}{unload}<input class="module-select grow" placeholder="find by title or folder" oninput="cvTalkFind(this)"></div>{"".join(fold(n) for n in folders)}{"".join(row(p) for p in ps if not p.get("folder"))}{C._dim("A project holds pointers to chats, runs and views, not copies: taking one out leaves what it pointed to.") if not ps else ""}</div>{C._FIND_JS}"""

def _label(user: str, show: dict) -> str:
    """A tab's name from what it shows: the chat's title, the run's pipeline, the face and view."""
    if show.get("chat"): return C._talk(user, show["chat"])["title"] if (C._talk_dir(user) / f"""{show["chat"]}.json""").exists() else "Chat"
    if show.get("run"): return (C.AV.director.runs[show["run"]].plan.get("name") or show["run"]) if show["run"] in C.AV.director.runs else "Run"
    f = C.AV.lib.get("face", show["face"]) if C.AV.lib.has("face", show.get("face", "")) else {}
    return " - ".join(x for x in (f.get("name") or show.get("face", ""), next((v.get("name") or v["id"] for v in C._views(f) if v["id"] == show.get("view")), "") if f else "") if x)

def _choices(request, host: str) -> list:
    """What a tab can show, all picked from lists: a new chat, a chat of this person (any face), one of their runs, a view of another face."""
    user = C._user(request)
    talks = sorted((json.loads(f.read_text()) for f in C._talk_dir(user).glob("*.json")), key=lambda t: t["changed"], reverse=True)
    fname = lambda fid: (C.AV.lib.get("face", fid).get("name") or fid) if C.AV.lib.has("face", fid) else fid
    runs = sorted((r for r in C.AV.director.runs.values() if not r.meta.get("parent") and (C._admin(request) or r.meta.get("owner") == user)), key=lambda r: r.meta["created"], reverse=True)[:30]
    views = [(f"""face:{f["id"]}:{v["id"]}""", f"""view: {f.get("name") or f["id"]}{" - " + (v.get("name") or v["id"]) if v["id"] else ""}""") for f in C._faces() if f["id"] != host for v in (C._views(f) or [{"id": ""}])]
    return [("chat_new", "a new chat"), *((f"""chat:{t["id"]}""", f"""chat ({fname(t["face"])}): {t["title"]}""") for t in talks), *((f"run:{r.id}", f"""run: {r.plan.get("name") or r.id} - {C._when(r.meta["created"])} {C._about(r)[:60]}""") for r in runs), *views]

async def p_workspace(c) -> str:
    """The loaded project: its rows of tabs (a tab may hold tabs of its own), what the open tab shows, how far Tessa reaches here, and adding a tab."""
    user, p = C._user(c.request), _proj(C._user(c.request), c.tab.get("project", ""))
    if not p: return C._dim("Pick a project on the left, or make one. Tessa (right) is here either way: the project loaded here is what it is told you are working on.")
    _ensure(user, c.host, p)
    want, at, level, node, rows = [int(x) for x in str(c.tab.get("ptab", "")).split(".") if x.isdigit()], [], p.get("tabs") or [], None, ""
    for depth in range(len(want) + 1):
        if not level: break
        on = want[depth] if depth < len(want) and want[depth] < len(level) else None
        rows += C._tab_row(f"cv-ptab-{depth}", c.host, [(tb.get("name") or f"Tab {n + 1}", n == on, {"ptab": ".".join(map(str, [*at, n]))}) for n, tb in enumerate(level)])
        if on is None: break
        at, node, level = [*at, on], level[on], level[on].get("tabs") or []
    here = ".".join(map(str, at))
    add = f"""<form id="cv-proj-add" class="row" onsubmit="return false"><select name="what" class="module-select grow" title="What the new tab shows">{C._options(_choices(c.request, c.host), "chat_new")}</select><label title="Inside the tab shown, as a tab of its own row"><input type="checkbox" name="under" value="1"{"" if node else " disabled"}> inside this tab</label>{C._btn("Add a tab", "proj_add", face=c.host, pid=p["id"], at=here, include="#cv-proj-add")}</form>"""
    body = await _content(c, user, p, node, here) if node else C._dim("No tab is open: pick one above, or add one.")
    return f"""<div class="row"><b class="grow">{C._esc(p.get("title") or p["id"])}</b></div>{rows}{body}<details class="list-row" id="cv-proj-more"><summary class="cv-dim">Add a tab, and how far Tessa reaches here</summary>{add}{_reach(user, p, c.host)}</details>"""

async def _content(c, user: str, p: dict, node: dict, here: str) -> str:
    """What a tab shows: a chat in the portal's chat interface (its own settings stay in its face), a run, or the workspace of another face's view; and taking the tab out."""
    sh, out = node.get("show") or {}, C._btn("Take this tab out", "proj_untab", "ui-btn cv-small", face=c.host, pid=p["id"], at=here, confirm="Take this tab (and the tabs inside it) out of the project? What it shows stays.")
    if cid := sh.get("chat"):
        if not (C._talk_dir(user) / f"{cid}.json").exists(): return C._note("The chat this tab pointed to is no longer there.", True) + out
        t = C._talk(user, cid)
        head = f"""<b id="cv-talk-title-{t["id"]}">{C._esc(t["title"])}</b> {C._btn("Its settings", "open_tab", "ui-btn cv-small", title="Open it in its own face, with what answers there and its values", id=t["face"], **{C._cid_key(t["face"]): t["id"]})} {out}"""
        return f"""<div class="cv-chat" style="height:70vh">{C._cm(t["face"]).shell(t["id"], C._acted(t), user=c.request.state.user, header_html=head, is_working=C._working(t), stop_intent=C._stop_vals(t["id"]), think=C._think_now(C._conv_spec(C.AV.lib.get("face", t["face"])), t) if C.AV.lib.has("face", t.get("face", "")) else None, extra_footer=C.MEDIA.attach_html(t["id"]))}</div>"""
    if rid := sh.get("run"): return (C._run_view(C._run(c.request, rid), c.request) if rid in C.AV.director.runs else C._note("The run this tab pointed to is no longer kept.", True)) + out
    if not C.AV.lib.has("face", sh.get("face", "")): return C._note(f"""The face "{sh.get("face", "")}" this tab pointed to is no longer there.""", True) + out
    f = C.AV.lib.get("face", sh["face"])
    lay = C._layout(f, {"view": sh.get("view", "")})
    vid = lay["id"] if C._views(f) else ""
    return "".join(C._sec(spec.get("title", ""), C._later(f["id"], vid, "main", n, c.host)) for n, spec in enumerate(lay.get("main", []))) + out

def _reach(user: str, p: dict, host: str) -> str:
    """How far Tessa reaches in this project, each ask with the answer and its reason: the project asks, the person gives, and the AI account's own scope bounds it."""
    sid, asks = _sid(_acct(host), p["id"]), _asks(user, p)
    if not asks: return C._dim(f"""Tessa is told what this project is (its title and what to tell it) and may not reach its chats. It acts here as {sid}. How far it may reach is in the project's &#x22EF;.""")
    return C._dim(f"Tessa acts here as {sid}:") + "".join(C._dim(f"""{C._esc(act)} {C._esc(on)}: {"yes" if ok else "no"} - {C._esc(how)}""") for on, act in asks for ok, how in [S()["why"](sid, on, act)])

# --- Intents ---

async def _h_new(request, payload, imr):
    user, p = C._user(request), {"id": uuid.uuid4().hex[:10], "title": "New project", "tabs": []}
    _dir(user).mkdir(parents=True, exist_ok=True)
    _save(user, p)
    load(user, payload["face"], p)
    return await _open(request, imr, payload["face"], p["id"])

async def _h_load(request, payload, imr):
    user = C._user(request)
    refused = load(user, payload["face"], _proj(user, payload.get("pid", "")))
    imr = await _open(request, imr, payload["face"], payload.get("pid", ""))
    return imr.oob(C._note("; ".join(f"{act} {on}: {why}" for on, act, why in refused), True), "cv-msg") if refused else imr

async def _h_meta(request, payload, imr):
    """A project's row turned into its small form: title, folder, what Tessa is told about it, how far it may reach the project's chats, take it out."""
    user = C._user(request)
    p, fid = _proj(user, payload["pid"]), f"""cv-pm-{payload["pid"]}"""
    folders = C._option("", "(no folder)", p.get("folder", "")) + "".join(C._option(f, f, p.get("folder", "")) for f in sorted({x["folder"] for x in _projects(user) if x.get("folder")}, key=str.lower))
    form = f"""<form id="{fid}" class="cv-form" style="width:100%" onsubmit="return false"><input name="title" class="module-select" style="width:100%" value="{C._esc(p.get("title", ""))}" title="Its title"><div class="row"><select name="folder" class="module-select grow" title="The folder it is in">{folders}</select><input name="new_folder" class="module-select grow" placeholder="or a new folder"></div><textarea name="context" class="cm-input" rows="4" style="width:100%" placeholder="What Tessa is told about this project while it is loaded (with its title)">{C._esc(p.get("context", ""))}</textarea><div class="row"><span title="How far Tessa may reach this project's chats: see (it is given their latest messages), take part, organize - asked as grants, bounded by what its own account may">Tessa and its chats</span><select name="tessa" class="module-select grow">{C._options([(k, k) for k in REACH], p.get("tessa") or "none")}</select><input name="tessa_reads" type="number" min="1" style="width:5em" value="{C._esc(p.get("tessa_reads") or 6)}" title="How many of each chat's latest messages Tessa is given, where it may see them"></div>{C._dim("Take part and organize are kept as grants; Tessa joining a chat, and organizing chats, are not built yet.")}<div class="row">{C._btn("Save", "proj_meta_save", face=payload["face"], pid=p["id"], include="#" + fid)}<span class="grow"></span>{C._btn("Take out", "proj_meta_save", "ui-btn cv-small cv-danger", face=payload["face"], pid=p["id"], drop="1", confirm="Take this project out? Only the project goes: its chats, runs and views stay.")}{C._btn("Cancel", "proj_meta_save", "ui-btn cv-small", face=payload["face"], pid=p["id"], cancel="1")}</div></form>"""
    return imr.oob(form, f"""cv-proj-row-{p["id"]}""")

async def _h_meta_save(request, payload, imr):
    user, face_id = C._user(request), payload["face"]
    p = _proj(user, payload["pid"])
    if payload.get("drop"):
        if LOADED.get((user, face_id)) == _sid(_acct(face_id), p["id"]): load(user, face_id, {})
        (_dir(user) / f"""{p["id"]}.json""").unlink()
        return await _open(request, imr, face_id, "")
    if not payload.get("cancel"):
        _save(user, p := {**p, "title": (payload.get("title") or "").strip() or p.get("title", ""), "folder": (payload.get("new_folder") or "").strip() or payload.get("folder") or "", "context": payload.get("context", ""), "tessa": payload.get("tessa") if payload.get("tessa") in REACH else "none", "tessa_reads": int(payload.get("tessa_reads") or 6)})
        _reload(user, face_id, p)
        if LOADED.get((user, face_id)) == _sid(_acct(face_id), p["id"]): imr.oob(_on(p), f"cv-stream-on-{face_id}")   # the stream's line too, without redrawing what is being written there
    return await C._refresh(request, imr, face_id, regions=("left", "main"))

async def _h_add(request, payload, imr):
    """A tab added to the project, beside the one shown or inside it, showing what was picked."""
    user, face_id = C._user(request), payload["face"]
    p, (kind, _, ref) = _proj(user, payload["pid"]), payload.get("what", "chat_new").partition(":")
    if kind == "chat_new": kind, ref = "chat", C._talk_new(user, "chat")["id"]
    show = {"chat": ref} if kind == "chat" else {"run": ref} if kind == "run" else {"face": ref.partition(":")[0], "view": ref.partition(":")[2]}
    at = [int(x) for x in str(payload.get("at", "")).split(".") if x.isdigit()]
    base, level = at if payload.get("under") else at[:-1], p.setdefault("tabs", [])
    for n in base: level = level[n].setdefault("tabs", [])
    level.append({"name": _label(user, show), "show": show})
    _save(user, p)
    _reload(user, face_id, p)
    return await _open(request, imr, face_id, p["id"], ".".join(map(str, [*base, len(level) - 1])))

async def _h_untab(request, payload, imr):
    user, face_id = C._user(request), payload["face"]
    p, at = _proj(user, payload["pid"]), [int(x) for x in str(payload.get("at", "")).split(".") if x.isdigit()]
    level = p.get("tabs") or []
    for n in at[:-1]: level = level[n].get("tabs") or []
    if at and at[-1] < len(level): level.pop(at[-1])
    _save(user, p)
    _reload(user, face_id, p)
    return await _open(request, imr, face_id, p["id"], ".".join(map(str, at[:-1])))
