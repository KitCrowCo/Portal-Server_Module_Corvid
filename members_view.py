"""members_view.py - an AI member as the person working with it sees it: who it works for, what it is granted, what it keeps in its own space, and where its projects stand.
The panel "member" goes beside a conversation whose pipeline takes a "profile" (the orchestrator): it shows the profile the conversation uses. Read only: the profile is changed in the library (kind agent), its proposals in the review panels."""
import json

C = None   # corvid.py's live view, given to init

def init(c):
    global C
    C = c

def _profile_id(c) -> str:
    conv, t = C._conv_spec(c.face), C._current(c.request, c.face, c.tab)
    pl = C.AV.lib.get("pipeline", C._pipe(conv, t)) if C.AV.lib.has("pipeline", C._pipe(conv, t)) else {}
    me = C._user(c.request)
    mine = [x["id"] for x in C.AV.lib.list("agent") if not x.get("owner") or me in (x["owner"], *(x.get("users") or []))]
    return str({**{k: v.get("default") for k, v in (pl.get("params") or {}).items()}, **C._base(conv, t), **t.get("inputs", {})}.get("profile") or (mine[0] if len(mine) == 1 else ""))   # none chosen: the one AI this person may work with (as the run decides it, agents.prepare)

def _space(name: str) -> str:
    """The files of its own space, newest first."""
    d = C.ENV["tools"]["aviary"].agent_loop.SPACES_DIR / name
    files = sorted((f for f in d.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True) if d.is_dir() else []
    return "".join(f"""<div class="row"><span class="mono grow">{C._esc(f.relative_to(d).as_posix())}</span><span class="cv-dim">{f.stat().st_size // 1024 + 1} kB</span></div>""" for f in files[:30]) or C._dim("empty so far")

def _issue_line(i: dict) -> str: return f"""<div class="cv-dim">{C._esc(i["id"])} {C._esc(i["cells"].get("title") or (list(i["cells"].values())[1:2] or [""])[0])[:90]}</div>"""   # its title column, else the column after the id

def _projects(aid: str, owner: str, granted) -> str:
    """Each project it may work on: its open issues as its mask shows them, and changes waiting for an answer."""
    mn = C.ENV["tools"].get("muninn")
    if not mn or not hasattr(mn, "projects"): return C._dim("Projects need the Muninn tool.")
    PJ, who = mn.projects, (f"agent:{aid}", owner)
    rows = []
    for p in PJ.projects(who):
        if granted is not True and p["slug"] not in (granted or []): continue
        open_ = [i for i in PJ.issues(p["slug"], who) if i["cells"].get("status", "").strip("* ").lower() not in ("done",)]
        listed = "".join(_issue_line(i) for i in open_[:8])
        rows.append(f"""<div class="list-row"><div class="row"><b class="grow">{C._esc(p["name"] or p["slug"])}</b><span class="chip">{len(open_)} open</span><span class="chip">{len(PJ.proposals(p["slug"]))} waiting</span></div>{listed}</div>""")
    return "".join(rows) or C._dim("No project shows it anything yet: give it a mask in a project's _project.json (agent:" + C._esc(aid) + ").")

async def p_member(c) -> str:
    aid = _profile_id(c)
    if not aid: return C._dim("Choose the AI (its profile) under This conversation.")
    if not C.AV.lib.has("agent", aid): return C._note(f"No AI profile {aid} in the library (kind agent).", True)
    pr, g = C.AV.lib.get("agent", aid), C.AV.lib.get("agent", aid).get("grants") or {}
    d = g.get("delegate")
    granted = "".join(f"""<div class="row"><span class="cv-dim" style="min-width:6rem">{C._esc(k)}</span><span class="mono" style="overflow-wrap:anywhere">{C._esc(json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v)}</span></div>""" for k, v in g.items() if k != "delegate")
    works = f"""Works for {C._esc(pr.get("owner") or "nobody")}{f" (and {C._esc(', '.join(pr['users']))})" if pr.get("users") else ""}"""
    hands = f"""May hand tasks to sub-agents: {d.get("most", 3)} per answer, {d.get("rounds", 30)} rounds each, with part of these grants.""" if d else "Does not hand tasks on."
    space = f"""<b>Its own space</b> <span class="cv-dim">{C._esc(g["space"])}: written without asking</span>{_space(g["space"])}""" if g.get("space") else ""
    projects = f"""<b>Projects</b>{_projects(aid, pr.get("owner") or C._user(c.request), g.get("projects"))}""" if g.get("projects") else ""
    return f"""<div class="row"><b class="grow">{C._esc(pr.get("name") or aid)}</b><span class="chip mono">agent:{C._esc(aid)}</span></div>{C._dim(works)}<details><summary class="cv-dim">Standing instructions</summary><div class="pre-wrap">{C._esc(pr.get("system") or "(none)")}</div></details><b>Granted</b>{granted or C._dim("nothing yet")}<div class="cv-dim">{hands}</div>{space}{projects}"""
