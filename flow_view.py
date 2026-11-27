"""flow_view.py - a pipeline drawn from its data alone: no editor, no stored positions.
Order comes only from what each step needs and what each gives (the engine's own rule); waves are worked out here for the picture and never stored.
A step that is itself a pipeline is drawn as one node and can be opened beneath. The same picture colours a run's steps by where they stand.
Drawn as SVG in relative units (viewBox), so it scales to the panel on a phone or a desktop; two arrangements: down (waves as rows) and across (waves as columns).
The designer is one panel ("flow") in parts, so a face puts each where it belongs: "list" (the pipelines to pick from and the arrangement, a toolbar), "picture" (the workspace: a step is picked by clicking it), "step" (what the picked step is: needs, gives, roles, and its form - change, add after, remove - saved as your copy of the pipeline after the check; a toolbar). Without "part" the panel is all of them in one, as before."""
import json

C = None   # corvid.py's live view, given to init
SEL: dict = {}   # (user, face) -> pipeline id shown on the picture panel
STEP: dict = {}   # (user, face) -> (pipeline id, path of the step picked: "a" or "a/b" for step b inside step a's pipeline, "@inputs" for what a run is given)
DRAFT: dict = {}   # (user, face) -> {"path", "fields", "error"}: a step form that did not pass the check, shown again as typed with what was wrong
LAYOUT: dict = {}   # user -> "down" | "across"
W, H, GX, GY, ROW = 190, 50, 26, 46, 2   # node size and gaps in picture units; ROW: nodes side by side in one row of the down arrangement before it wraps (two keep the text readable at phone width)
FILL = {"done": "#00ffa222", "running": "#ffcc0033", "next": "#ffcc0018", "unreached": "#88888818", "failed": "#ff6b6b33", "held": "#ff6b6b33"}
EDGE = {"done": "#00ffa2", "running": "#ffcc00"}

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_flow_pick": [_h_pick], "corvid_flow_layout": [_h_layout], "corvid_flow_step": [_h_step], "corvid_flow_save": [_h_save], "corvid_flow_add": [_h_add], "corvid_flow_drop": [_h_drop], "corvid_flow_revert": [_h_revert]})

# --- The plan as a graph ---

def waves(plan: dict) -> dict:
    """{step id: wave}: 0 for a step that needs nothing another step gives, else one more than the latest step that gives what it needs. A step caught in a loop of needs is put at the wave its loop was entered from."""
    steps = {s["id"]: s for s in plan.get("steps", [])}
    giver = {g: s["id"] for s in steps.values() for g in s.get("gives", [])}
    out, seen = {}, set()
    def wave(sid):
        if sid in out: return out[sid]
        if sid in seen: return 0
        seen.add(sid)
        out[sid] = 1 + max((wave(giver[n]) for n in steps[sid].get("needs", []) if n in giver and giver[n] != sid), default=-1)
        return out[sid]
    for sid in steps: wave(sid)
    return out

def links(plan: dict) -> dict:
    """{(from, to): [keys]}: what passes between steps; "" as from is the pipeline's own inputs (its params and data)."""
    giver, start, out = {g: s["id"] for s in plan.get("steps", []) for g in s.get("gives", [])}, set(plan.get("params") or {}) | set(plan.get("data") or {}), {}
    for s in plan.get("steps", []):
        for n in s.get("needs", []):
            if n in giver and giver[n] != s["id"]: out.setdefault((giver[n], s["id"]), []).append(n)
            elif n in start: out.setdefault(("", s["id"]), []).append(n)
    return out

def _what(s: dict) -> str:
    """A step's second line: what kind of work it is (its role and capability, the pipeline it runs, or its type)."""
    cfg = s.get("config") or {}
    if s["type"] == "capability": return f"""{cfg.get("role", "")} - {cfg.get("capability", "")}"""
    if s["type"] == "pipeline": return f"""pipeline{" for each " + str(cfg["each"]) if cfg.get("each") else ""}"""
    if s["type"] == "turns": return f"""turns: {", ".join(str(x.get("role")) for x in [*(cfg.get("speakers") or []), *([cfg["judge"]] if cfg.get("judge") else [])])}"""   # who takes turns, the judge last
    return s["type"]

def sub_plan(s: dict) -> dict:
    """The plan a pipeline step runs: written inside it, or named from the library."""
    p = (s.get("config") or {}).get("plan")
    return p if isinstance(p, dict) else C.AV.lib.get("pipeline", p) if isinstance(p, str) and C.AV.lib.has("pipeline", p) else {}

# --- Drawing ---

def svg(plan: dict, states: dict = None, layout: str = "down", act=None, chosen: str = "") -> str:
    """The picture: an inputs node, then each wave of steps; lines carry the keys passed (named on hover), drawn first so every box lies over them. states: {step id: "done" | "running" | ...} to colour a run. act: fn(step id or "@inputs") -> attributes that pick it when clicked (the designer); chosen: the step shown picked."""
    states, wv = states or {}, waves(plan)
    order = sorted(plan.get("steps", []), key=lambda s: (wv[s["id"]], plan["steps"].index(s)))
    rows = [[s for s in order if wv[s["id"]] == w] for w in sorted(set(wv.values()))]
    pos, y = {"": (0, 0)}, H + GY
    if layout == "across":
        for col, row in enumerate(rows):
            for i, s in enumerate(row): pos[s["id"]] = ((col + 1) * (W + GX), i * (H + GY // 2))
        pos[""] = (0, 0)
    else:
        for row in rows:
            for i in range(0, len(row), ROW):
                for j, s in enumerate(row[i:i + ROW]): pos[s["id"]] = (j * (W + GX), y)
                y += H + GY // 2
            y += GY // 2
    vw, vh = max(x for x, _ in pos.values()) + W + 4, max(y for _, y in pos.values()) + H + 4
    def edge(a, b, keys):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        p = f"M{x1 + W} {y1 + H / 2} C{x1 + W + GX} {y1 + H / 2} {x2 - GX} {y2 + H / 2} {x2} {y2 + H / 2}" if layout == "across" else f"M{x1 + W / 2} {y1 + H} C{x1 + W / 2} {y1 + H + GY / 2} {x2 + W / 2} {y2 - GY / 2} {x2 + W / 2} {y2}"
        faint = ' stroke-dasharray="2 4" opacity=".35"' if a == "" else ""   # what a run is given reaches many steps: drawn faint so the steps' own links stay readable
        return f"""<path d="{p}" fill="none" stroke="{EDGE.get(states.get(a), "var(--border)")}" stroke-width="1.5"{faint} marker-end="url(#cv-fl-arrow)"><title>{C._esc(", ".join(keys))}</title></path>"""
    def node(s):
        x, y = pos[s["id"]]
        sub = "pipeline" == s["type"]
        tip = f"""{s["id"]} ({s["type"]})\nneeds: {", ".join(s.get("needs", [])) or "-"}\ngives: {", ".join(s.get("gives", [])) or "-"}""" + (f"""\nstate: {states[s["id"]]}""" if s["id"] in states else "")
        on = s["id"] == chosen
        return f"""<g {act(s["id"]) if act else ""} style="{"cursor:pointer" if act else ""}"><title>{C._esc(tip)}</title><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="7" fill="var(--bg_panel)"/><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="7" fill="{FILL.get(states.get(s["id"]), "var(--bg_panel)")}" stroke="{"var(--accent)" if sub or on else "var(--border)"}" stroke-width="{3 if on else 1}" stroke-dasharray="{"5 3" if sub and not on else "none"}"/><text x="{x + 10}" y="{y + 20}" font-size="14" fill="var(--text)">{"&#x25B8; " if sub else ""}{C._esc(s["id"][:24])}</text><text x="{x + 10}" y="{y + 38}" font-size="11" fill="var(--text_muted)">{C._esc(_what(s)[:30])}</text></g>"""
    ins = f"""<g {act("@inputs") if act else ""} style="{"cursor:pointer" if act else ""}"><title>{C._esc("inputs: " + ", ".join(list(plan.get("params") or {}) + list(plan.get("data") or {})))}</title><rect x="0" y="0" width="{W}" height="{H}" rx="7" fill="var(--bg_panel)" stroke="{"var(--accent)" if chosen == "@inputs" else "var(--text_muted)"}" stroke-width="{3 if chosen == "@inputs" else 1}"/><text x="10" y="20" font-size="14" fill="var(--text)">inputs</text><text x="10" y="38" font-size="11" fill="var(--text_muted)">{len(plan.get("params") or {})} given to a run</text></g>"""
    return f"""<svg viewBox="-2 -2 {vw} {vh}" style="width:100%;max-width:{vw / 16:.1f}rem;height:auto;font-family:var(--font-main)" role="img" aria-label="{C._esc(plan.get("name") or plan.get("id", "pipeline"))}"><defs><marker id="cv-fl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--text_muted)"/></marker></defs>{"".join(edge(a, b, k) for (a, b), k in links(plan).items())}{ins}{"".join(node(s) for s in order)}</svg>"""

def picture(plan: dict, states: dict = None, layout: str = "down", runs_of=None, depth: int = 0, act=None, chosen: str = "") -> str:
    """The picture with each step that is a pipeline openable beneath it, as deep as they go. runs_of: fn(step id) -> states of that step's own run, when a run is shown. act / chosen as in svg, with paths ("a/b") for steps inside; a pipeline holding the chosen step is shown open."""
    subs = [s for s in plan.get("steps", []) if s["type"] == "pipeline" and sub_plan(s)]
    def inside(s):
        mine = chosen.split("/", 1)[1] if chosen.startswith(s["id"] + "/") else ""
        return f"""<details class="cv-fl-sub" style="margin:.3rem 0 .3rem {min(depth + 1, 3) * .6}rem"{" open" if mine else ""}><summary class="cv-dim">inside <b>{C._esc(s["id"])}</b>: {C._esc(sub_plan(s).get("name") or "")}</summary>{picture(sub_plan(s), runs_of(s["id"]) if runs_of else None, layout, None, depth + 1, (lambda sid, pre=s["id"]: act(f"{pre}/{sid}")) if act else None, mine)}</details>"""
    inner = "".join(inside(s) for s in subs) if depth < 6 else ""
    return f"""<div class="scroll-pane" style="overflow-x:auto">{svg(plan, states, layout, act, chosen)}</div>{inner}"""

def legend(states: bool) -> str: return C._dim("A box is a step, a line what it passes on (hover for the keys), dashed: a step that runs a pipeline of its own. Order comes only from what each step needs." + (" Green: done, yellow: working or next, red: failed or held, grey: not reached." if states else ""))

# --- Panel and intents ---

def _pipelines(c) -> list:
    """The pipelines a designer offers: a project's own (a face under another: those its panels name, by id or by group), else the whole library; by group and name."""
    pls = C.AV.lib.list("pipeline")
    if c.face.get("under"):
        specs = [sp for v in C._views(c.face) for r in ("left", "main", "right") for sp in v.get(r, [])]
        ids, groups = {i for sp in specs for i in [sp.get("pipeline"), *(sp.get("pipelines") or [])] if i}, {g for sp in specs for g in sp.get("groups") or []}
        pls = [p for p in pls if p["id"] in ids or p.get("group") in groups]
    return sorted(pls, key=lambda p: (p.get("group", ""), p.get("name") or p["id"]))

def _current(c, pls: list) -> str:
    me = (C._user(c.request), c.face["id"])
    return c.spec.get("pipeline") or next((p["id"] for p in pls if p["id"] == SEL.get(me)), pls[0]["id"] if pls else "")

def step_at(plan: dict, path: str):
    """The step a path names ("a", or "a/b" for step b in step a's pipeline), or None."""
    head, _, rest = path.partition("/")
    s = next((x for x in plan.get("steps", []) if x["id"] == head), None)
    return step_at(sub_plan(s), rest) if s and rest else s

def _act_step(face_id: str, pid: str):
    return lambda path: f"""hx-post="/im/in" hx-vals='{json.dumps({"type": "corvid_flow_step", "face": face_id, "pid": pid, "path": path})}' hx-trigger="click" hx-swap="none" """

def _list(c, pls: list, pid: str) -> str:
    lay = LAYOUT.get(C._user(c.request), "down")
    rows = "".join(f"""<div class="list-row row{" cv-on" if p["id"] == pid else ""}" style="cursor:pointer" {C._act("flow_pick", face=c.face["id"], pid=p["id"])}><span class="grow">{"&#x25B8; " if p["id"] == pid else ""}{C._esc(p.get("name") or p["id"])}</span><span class="cv-dim">{C._esc(p.get("group", ""))}</span></div>""" for p in pls)
    lays = "".join(C._btn(n, "flow_layout", "ui-btn cv-small" + (" cv-on" if lay == k else ""), face=c.face["id"], layout=k) for k, n in (("down", "Down"), ("across", "Across")))
    return f"""{rows or C._dim("No pipeline here yet.")}<div class="row" style="flex-wrap:wrap"><span class="cv-dim">Arrange</span>{lays}</div>{legend(False)}{C._dim("Pick a step in the picture to see and change it beside it. Saving keeps a copy of yours; the shipped pipeline stays, and each saved version is kept.")}"""

def _picture(c, pid: str) -> str:
    pl, me = C.AV.lib.get("pipeline", pid), (C._user(c.request), c.face["id"])
    chosen = STEP[me][1] if STEP.get(me, ("", ""))[0] == pid else ""
    return f"""<div class="row"><b>{C._esc(pl.get("name") or pid)}</b><span class="cv-dim grow">{C._esc(pid)}</span></div>{C._dim(pl.get("objective", ""))}{picture(pl, None, LAYOUT.get(me[0], "down"), act=_act_step(c.face["id"], pid), chosen=chosen)}"""

def _chips(keys) -> str: return " ".join(f"""<span class="chip mono">{C._esc(k)}</span>""" for k in keys) or C._dim("-")

def _owner_of(plan: dict, path: str):
    """The plan that holds the step at path (the pipeline itself, or the inline pipeline of the step before the last /), or None when that inner pipeline is a library pipeline of its own (edited on its own)."""
    if "/" not in path: return plan
    s = step_at(plan, path.rsplit("/", 1)[0])
    return (s.get("config") or {}).get("plan") if s and isinstance((s.get("config") or {}).get("plan"), dict) else None

def _keys(text) -> list: return [k.strip() for k in str(text or "").replace("\n", ",").split(",") if k.strip()]

def _form(c, pid: str, path: str, s: dict, draft: dict) -> str:
    """A step's form: id, type, needs, gives, kept, once, and its settings as JSON; what was typed comes back with the reason when the check refused it."""
    f = draft.get("fields") or {"s_id": s["id"], "s_type": s["type"], "s_needs": ", ".join(s.get("needs", [])), "s_gives": ", ".join(s.get("gives", [])), "s_keep": "1" if s.get("keep") else "", "s_once": "1" if s.get("once") else "", "s_config": json.dumps(s.get("config") or {}, indent=1, ensure_ascii=False)}
    types = "".join(f"""<option{" selected" if k == f["s_type"] else ""}>{C._esc(k)}</option>""" for k in sorted(C.AV.types))
    box = lambda n, label: f"""<label class="row"><input type="checkbox" name="{n}" value="1"{" checked" if f.get(n) else ""}> {label}</label>"""
    err = C._note(draft["error"], True) if draft.get("error") else ""
    return f"""{err}<form id="cv-fl-edit" onsubmit="return false"><label>id <input class="module-input mono" name="s_id" value="{C._esc(f["s_id"])}" style="width:100%"></label><label>type <select class="module-select" name="s_type">{types}</select></label><label>needs <input class="module-input mono" name="s_needs" value="{C._esc(f["s_needs"])}" style="width:100%" title="keys, comma separated"></label><label>gives <input class="module-input mono" name="s_gives" value="{C._esc(f["s_gives"])}" style="width:100%" title="keys, comma separated"></label><div class="row" style="flex-wrap:wrap">{box("s_keep", "kept (a stop goes on from it)")}{box("s_once", "once (asks before running again)")}</div><label>settings (JSON)<textarea class="module-input mono" name="s_config" rows="14" style="width:100%">{C._esc(f["s_config"])}</textarea></label></form><div class="row" style="flex-wrap:wrap">{C._btn("Save", "flow_save", include="#cv-fl-edit", face=c.face["id"], pid=pid, path=path)}{C._btn("Add a step after", "flow_add", face=c.face["id"], pid=pid, path=path)}{C._btn("Remove", "flow_drop", confirm=f"Remove step {path} from the pipeline? The saved version before it is kept.", face=c.face["id"], pid=pid, path=path)}</div>"""

def _step(c, pid: str) -> str:
    """The picked step: kind, what it needs and gives (and which step gives each need), its roles, and its form; for the inputs node, the pipeline's inputs. Saving keeps the pipeline as yours (the shipped one stays, and every saved version before is kept)."""
    me, pl = (C._user(c.request), c.face["id"]), C.AV.lib.get("pipeline", pid)
    got, path = STEP.get(me, ("", ""))
    mine = C.AV.lib.origin("pipeline", pid) == "mine"
    head = f"""<div class="row"><span class="cv-dim grow">{"your copy" if mine else "as shipped: saving keeps a copy of yours"}</span>{C._btn("Back to shipped", "flow_revert", "ui-btn cv-small", confirm="Use the shipped pipeline again? Your copy is kept as a saved version.", face=c.face["id"], pid=pid) if mine and any((r / "pipeline" / f"{pid}.json").exists() for r in C.AV.lib.shipped) else ""}</div>"""
    if got != pid or not path: return head + C._dim("Pick a step (or the inputs box) in the picture.") + C._btn("Add a step", "flow_add", face=c.face["id"], pid=pid, path="")
    if path.endswith("@inputs"):
        inner = sub_plan(step_at(pl, path.rsplit("/", 1)[0])) if "/" in path else pl
        rows = "".join(f"""<div class="list-row"><b class="mono">{C._esc(k)}</b> <span class="cv-dim">{C._esc(v.get("label") or "")}{" (advanced)" if v.get("advanced") else ""}</span><div class="cv-dim mono pre-wrap">{C._esc(json.dumps(v.get("default"), ensure_ascii=False)[:300]) if "default" in v else "(no default: must be given)"}</div></div>""" for k, v in (inner.get("params") or {}).items())
        return f"""{head}<b>What a run is given</b>{rows or C._dim("nothing")}{C._dim("Inputs are changed in the library editor for now.")}"""
    s, owner = step_at(pl, path), _owner_of(pl, path)
    if not s: return head + C._dim("That step is no longer in the pipeline.")
    giver = {g: x["id"] for x in (owner or sub_plan(step_at(pl, path.rsplit("/", 1)[0]))).get("steps", []) for g in x.get("gives", [])}
    params = (owner or {}).get("params") or {}
    from_ = "".join(f"""<div class="row"><span class="chip mono">{C._esc(n)}</span><span class="cv-dim">{C._esc("from " + giver[n] if n in giver else "given to the run" if n in params else "nothing gives it")}</span></div>""" for n in s.get("needs", []))
    roles = sorted(C.AVP.roles_of(owner or {"roles": {}}, s))
    edit = _form(c, pid, path, s, DRAFT.get(me, {}) if DRAFT.get(me, {}).get("path") == path else {}) if owner is not None else C._dim("It lies in a library pipeline of its own: pick that one in the list to change it.")
    return f"""{head}<div class="row"><b class="mono">{C._esc(path)}</b><span class="chip">{C._esc(s["type"])}</span></div>{C._dim(_what(s))}<div><b>Needs</b>{from_ or C._dim("-")}</div><div><b>Gives</b> {_chips(s.get("gives", []))}</div>{f"<div><b>Roles</b> {_chips(roles)}</div>" if roles else ""}{edit}{C._dim("It runs a pipeline of its own: open it beneath the picture.") if s["type"] == "pipeline" else ""}"""

def _checked(plan: dict) -> str:
    """What the check before saving says: the engine's refusals (ids twice, a need nothing gives, an unknown type) raise; what is only odd comes back as a note (a key given that nothing uses, steps that can never start)."""
    C.AVP.check(plan, C.AV.types)
    used = {k for s in plan["steps"] for k in C.AVP.needs(s)}
    idle = sorted({k for s in plan["steps"] for k in s.get("gives", []) if k not in used})
    never = C.AVP.unreached(plan, C.AVP.given(plan))
    return "; ".join(x for x in (f"""given but used by no step (fine for results a run ends with): {", ".join(idle)}""" if idle else "", f"""can never start: {", ".join(never)}""" if never else "") if x)

def _store(request, pid: str, pl: dict, inner_check: dict = None) -> str:
    """The pipeline saved as yours after the check (the inner pipeline changed, then the whole); the note the check had, if any."""
    if inner_check is not None and inner_check is not pl: _checked(inner_check)
    note = _checked(pl)
    C.AV.lib.save("pipeline", {k: v for k, v in pl.items() if k not in ("modified", "by")}, by=C._user(request))
    return note

async def p_flow(c) -> str:
    """The designer, whole or in its parts (spec "part": list / picture / step). A face may fix the pipeline ("pipeline" in its spec)."""
    pls = _pipelines(c)
    pid = _current(c, pls)
    if not pid or not C.AV.lib.has("pipeline", pid): return C._dim("No pipeline in the library yet." if not pls else f"No pipeline {pid} in the library.")
    part = c.spec.get("part", "")
    if part == "list": return _list(c, pls, pid)
    if part == "picture": return _picture(c, pid)
    if part == "step": return _step(c, pid)
    return f"""{_list(c, pls, pid) if not c.spec.get("pipeline") else ""}{_picture(c, pid)}<details><summary class="cv-dim">The picked step</summary>{_step(c, pid)}</details>"""

def run_picture(request, r) -> str:
    """A run's pipeline as a picture coloured by where each step stands; a step's own sub-run colours what is inside it."""
    sub = lambda sid: next((C._step_states(c) for c in sorted(C.AV.director.runs.values(), key=lambda c: c.meta["created"]) if c.meta.get("parent") == r.id and (c.id == f"{r.id}~{sid}" or c.id.startswith(f"{r.id}~{sid}~"))), None)   # a step's sub-run is <run>~<step>, or <run>~<step>~<n> for each item: the first is shown
    return f"""<details open><summary class="cv-dim">Picture</summary>{legend(True)}{picture(r.plan, C._step_states(r), LAYOUT.get(C._user(request), "down"), sub)}</details>"""

async def _h_pick(request, payload, imr):
    SEL[(C._user(request), payload["face"])] = payload.get("pid", "")
    return await C._refresh(request, imr, payload["face"])

def _copy(pid: str) -> dict: return json.loads(json.dumps(C.AV.lib.get("pipeline", pid)))   # a deep copy to change, so a refused change leaves nothing behind

async def _h_save(request, payload, imr):
    me, pid, path = (C._user(request), payload["face"]), payload["pid"], payload["path"]
    fields = {k: payload.get(k, "") for k in ("s_id", "s_type", "s_needs", "s_gives", "s_keep", "s_once", "s_config")}
    pl = _copy(pid)
    owner = _owner_of(pl, path)
    try:
        cfg = json.loads(fields["s_config"] or "{}")
        if not isinstance(cfg, dict): raise ValueError("settings must be a JSON object ({...})")
        i = next(n for n, s in enumerate(owner["steps"]) if s["id"] == path.rsplit("/", 1)[-1])
        new = {k: v for k, v in owner["steps"][i].items() if k not in ("keep", "once")}
        new.update(id=fields["s_id"].strip() or new["id"], type=fields["s_type"], needs=_keys(fields["s_needs"]), gives=_keys(fields["s_gives"]), config=cfg, **({"keep": True} if fields["s_keep"] else {}), **({"once": True} if fields["s_once"] else {}))
        owner["steps"][i] = new
        note = _store(request, pid, pl, owner)
    except (ValueError, StopIteration) as e:   # JSON that does not read, or what the check refused: the form comes back as typed, with the reason
        DRAFT[me] = {"path": path, "fields": fields, "error": str(e) or "that step is no longer there"}
        return await C._refresh(request, imr, payload["face"])
    DRAFT.pop(me, None)
    STEP[me] = (pid, path.rsplit("/", 1)[0] + "/" + new["id"] if "/" in path else new["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""Saved as your copy of {pid}.{" Note: " + note if note else ""}"""))

async def _h_add(request, payload, imr):
    """A new step after the picked one (or at the end), at the picked step's level: an expression giving nothing yet, to fill in its form."""
    me, pid, path = (C._user(request), payload["face"]), payload["pid"], payload.get("path", "")
    pl = _copy(pid)
    owner = _owner_of(pl, path) if path else pl
    if owner is None: return imr.oob(C._note("That step lies in a library pipeline of its own: pick that one to add to it.", True), "cv-msg")
    ids = {s["id"] for s in owner["steps"]}
    sid = next(f"step{n}" for n in range(1, 1000) if f"step{n}" not in ids)
    at = next((n + 1 for n, s in enumerate(owner["steps"]) if s["id"] == path.rsplit("/", 1)[-1]), len(owner["steps"]))
    owner["steps"].insert(at, {"id": sid, "type": "expr", "needs": [], "gives": [], "config": {"expr": "None", "give": "value"}})
    C.AV.lib.save("pipeline", {k: v for k, v in pl.items() if k not in ("modified", "by")}, by=me[0])   # an unfinished step is allowed while it gives and needs nothing; the check runs at its first Save
    STEP[me] = (pid, (path.rsplit("/", 1)[0] + "/" if "/" in path else "") + sid)
    DRAFT.pop(me, None)
    return await C._refresh(request, imr, payload["face"], C._note(f"Added {sid}: fill in its form and Save."))

async def _h_drop(request, payload, imr):
    me, pid, path = (C._user(request), payload["face"]), payload["pid"], payload["path"]
    pl = _copy(pid)
    owner = _owner_of(pl, path)
    owner["steps"] = [s for s in owner["steps"] if s["id"] != path.rsplit("/", 1)[-1]]
    try: note = _store(request, pid, pl, owner)
    except ValueError as e: return imr.oob(C._note(f"Not removed: without it {e}", True), "cv-msg")
    STEP[me] = (pid, "")
    return await C._refresh(request, imr, payload["face"], C._note(f"""Removed {path}.{" Note: " + note if note else ""}"""))

async def _h_revert(request, payload, imr):
    C.AV.lib.remove("pipeline", payload["pid"])
    STEP[(C._user(request), payload["face"])] = (payload["pid"], "")
    return await C._refresh(request, imr, payload["face"], C._note("The shipped pipeline is in use again; your copy is kept as a saved version."))

async def _h_step(request, payload, imr):
    STEP[(C._user(request), payload["face"])] = (payload.get("pid", ""), payload.get("path", ""))
    DRAFT.pop((C._user(request), payload["face"]), None)
    return await C._refresh(request, imr, payload["face"])

async def _h_layout(request, payload, imr):
    LAYOUT[C._user(request)] = "across" if payload.get("layout") == "across" else "down"
    return await C._refresh(request, imr, payload["face"])
