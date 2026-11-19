"""needs_view.py - what each pipeline needs and what would do it now (decision D-01): placement over everything available is the start; a default or a limit only narrows it.
For every pipeline in the library, each of its roles (the name the pipeline gives one need): the capabilities it needs, what placement would take right now and why (fits as things stand, already running, measured or estimated speed), what else could, and the default or limit set for it, if any.
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""

C = None
NOW_S = 15.0     # a need's placement, for showing, is placed again in the background once this old

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_needs_again": [_h_again]})

# --- Placement asked, as it would be for a run started now ---

async def now(pl_id: str, role: str, need: dict, owner: str, profiles: list) -> dict:
    """What placement gives this role, for showing: {"provider", "asset", "will", "running", "speed", "chosen_from", "passed", "default"} or {"error", "default"}, or {"pending": True} before it was ever placed; with "age" and "asking". It is the last placement, kept (Aviary's seen), placed again in the background once older than NOW_S, so no page waits on a machine. A run places for itself, as things stand when it starts. default: the candidates a profile sets for the role ([] = none: placed)."""
    cands = C._cands(role, profiles)
    async def place():
        try: return {**await C.ROLES.place(C.AV.lib, role, need, cands, None, {}, owner), "default": cands}
        except ValueError as e: return {"error": str(e), "default": cands}
    r = C.AV.seen.get(f"""place:{pl_id}:{role}:{owner}:{",".join(profiles)}""", place, NOW_S)
    return {**(r["value"] or {"pending": True, "default": cands}), "age": C.SEEN.age(r), "asking": r["asking"]}

def line(got: dict) -> str:
    """One placement in words: what, where, and why that one."""
    if got.get("pending"): return """<span class="chip">being placed ...</span>"""
    if got.get("error"): return f"""<span class="cv-bad" title="{C._esc(got["error"])}">nothing can do it now (hover: why)</span> <span class="cv-dim">{C._esc(got.get("age", ""))}</span>"""
    p = C.AV.lib.get("provider", got["provider"]) if C.AV.lib.has("provider", got["provider"]) else {"name": got["provider"]}
    why = ", ".join(x for x in ("already running" if got.get("running") else "", f"""{got["speed"]:.1f} t/s measured or estimated""" if got.get("speed") else "", f"""{got["fit_count"]} fit, of {len(got.get("chosen_from") or [])} able""" if got.get("chosen_from") else "", "set as the default" if got.get("default") else "placed: no default") if x)
    return f"""<b class="mono">{C._esc(got["asset"])}</b> on {C._esc(p.get("name") or got["provider"])} <span class="cv-dim">({C._esc(why)})</span>{f'<div class="cv-dim">{C._esc(got["will"])}</div>' if got.get("will") else ""}{f'<div class="cv-dim">placed {C._esc(got["age"])}</div>' if got.get("age") not in (None, "now") else ""}"""   # will: what the machine says it would do for it now (load it, make way, wait), from its own plan

def default_text(got: dict) -> str:
    d = got.get("default") or []
    return "; ".join((x.get("asset") or ("any of " + ("everything" if x.get("pool") == "*" else "the pool " + x.get("pool", "?")))) + (" when " + x["when"] if x.get("when") else "") for x in d) if d else "-"

# --- Panel ---

async def p_needs(c) -> str:
    """Every pipeline's needs and what would do each now, grouped as the library groups pipelines."""
    owner, profiles = C._user(c.request), c.spec.get("profiles") or [c.spec.get("profile", "default")]
    pls = sorted(C.AV.lib.list("pipeline"), key=lambda p: (p.get("group", ""), p.get("name") or p["id"]))
    if not pls: return C._no_pipelines()
    rows = [(pl, r, need) for pl in pls for r, need in (pl.get("roles") or {}).items()]
    got = [await now(pl["id"], r, need, owner, profiles) for pl, r, need in rows]
    def row(pl, r, need, g, first):
        name = f"""<td rowspan="{len(pl["roles"])}"><b>{C._esc(pl.get("name") or pl["id"])}</b><br><span class="cv-dim mono">{C._esc(pl["id"])}</span></td>""" if first else ""
        return f"""<tr>{name}<td><b>{C._esc(r)}</b><br><span class="cv-dim">{C._esc(need.get("about", ""))}</span></td><td class="mono">{C._esc(", ".join(need.get("needs") or []) or "-")}</td><td>{line(g)}</td><td class="cv-dim">{C._esc(default_text(g))}</td></tr>"""
    seen, body, group = set(), "", None
    for (pl, r, need), g in zip(rows, got):
        if pl.get("group", "") != group:
            group = pl.get("group", "")
            body += f"""<tr><th colspan="5">{C._esc(group or "other")}</th></tr>"""
        body += row(pl, r, need, g, pl["id"] not in seen)
        seen.add(pl["id"])
    head = """<tr><th>pipeline</th><th>need (its name there)</th><th>capabilities</th><th>would use now, and why</th><th title="optional: set under Defaults and limits">default or limit</th></tr>"""
    top = f"""<div class="row">{C._btn("Ask again", "needs_again", face=c.face["id"], title="Placement is asked again for every need (otherwise at most every 15 s)")}{C._btn("Defaults and limits", "open_tab", id=c.face["id"], view="defaults", title="Optional: narrow what a need may use (a default model, a pool, a case)")}<span class="grow"></span></div>"""
    again = C.BESIDE["status_view"]._again(c, 2) if any(g.get("asking") or g.get("pending") for g in got) else ""   # while any is being placed, the panel draws itself again
    return f"""<div {again}>{top}{C._dim("Nothing here has to be set. When work starts, each need is placed over everything that can do it, as things stand then: what fits, one already running first, then the faster as measured. A default or limit only narrows that. This is what placement would answer now, for you.")}{C._unreached(await C._offers())}<div class="scroll-pane"><table class="cv-tbl">{head}{body}</table></div></div>"""

async def _h_again(request, payload, imr):
    C.PROV.forget()
    C._recheck()   # what every machine offers, and every placement ("place:"), asked again now
    return await C._refresh(request, imr, payload["face"])
