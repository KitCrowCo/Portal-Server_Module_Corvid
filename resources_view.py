"""resources_view.py - Asio's view of the resources (Aviary's resources.py): every machine's parts and the path to it, every distinct model with where its copies are, and each figure as stated beside measured. Tests run from here (the characterizer) and fill the measured side.
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import asyncio

C = None
PULLS = set()   # pulls under way: the event loop holds its tasks only weakly
TESTS = {}   # provider id -> {"running": bool, "notes": [...], "result": {...}}: what a test started from this page is doing

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_res_sync": [_h_sync], "corvid_res_test": [_h_test], "corvid_res_test_all": [_h_test_all], "corvid_res_copy": [_h_copy], "corvid_res_remove": [_h_remove], "corvid_res_pull": [_h_pull]})

# --- Figures as text ---

def _disks(places: list) -> str:
    """Each disk once: its free and total space, how much is used, and the places on it. Places share a disk when the machine says so (dev); a machine that does not say is grouped by equal free and total space."""
    disks = {}
    for p in places: disks.setdefault(p["attrs"].get("dev") or (p["attrs"].get("free_gb"), p["attrs"].get("total_gb")), []).append(p)
    one = lambda ps: f"""<div title="{C._esc(chr(10).join(f'{p["name"]}: {p["attrs"].get("path", "")}' for p in ps))}"><b>{_num(ps[0]["attrs"].get("free_gb"))}</b> free of {_num(ps[0]["attrs"].get("total_gb"))} GB ({_num(round((ps[0]["attrs"].get("total_gb") or 0) - (ps[0]["attrs"].get("free_gb") or 0), 1))} used) <span class="cv-dim">{C._esc(", ".join(p["name"] for p in ps))}</span></div>"""
    return "".join(one(ps) for ps in disks.values()) or '<span class="cv-dim">not read yet</span>'

def _num(v, unit: str = "") -> str: return "-" if v is None else f"""{v:,.1f}{" " + unit if unit else ""}""" if isinstance(v, float) else f"""{v:,}{" " + unit if unit else ""}"""

def _fig(f: dict, unit: str = "") -> str:
    """One figure: what it was measured to be (how many tests, how sure), beside what it says it is."""
    if not f: return '<span class="cv-dim">-</span>'
    st, me = f.get("stated"), f.get("measured")
    meas = f"""<b>{_num(me, unit)}</b> <span class="cv-dim" title="{f["n"]} test(s); confidence {f["conf"]}">({f["n"]})</span>""" if me is not None else ""
    said = f"""<span class="cv-dim" title="{C._esc(f.get("source") or "")}">says {_num(st, unit)}</span>""" if st is not None else ""
    return f"""{meas} {said}""".strip()

# --- Network: each machine's interfaces and the lanes between machines ---

SHAPING = ("tbf", "htb", "hfsc", "cake", "cbq", "netem")   # queues that limit or delay what an interface sends

def _net_notes(n: dict, mates: list = ()) -> list:
    """What about one interface usually explains a slow path: a link that negotiated below gigabit, half duplex, a shaping queue, errors or drops counted since boot; with the machine's other interfaces (mates): a connected wired link with no address, or the default route going out a slower link than another that is up."""
    sp, out = n.get("speed_mbit"), []
    if n.get("default_route") and sp and (fast := max((m for m in mates if m is not n and m.get("state") == "up" and (m.get("speed_mbit") or 0) > sp), key=lambda m: m["speed_mbit"], default=None)): out.append(f"""default route goes out here at {sp} Mbit/s while {fast["name"]} is up at {fast["speed_mbit"]}""")
    if n.get("kind") == "ethernet" and n.get("state") == "up" and not n.get("addrs"): out.append("connected but has no address: nothing is sent through it")
    if n.get("kind") == "ethernet" and sp and sp < 1000: out.append(f"link at {sp} Mbit/s (a cable, port or setting holding it below gigabit)")
    if n.get("duplex") == "half": out.append("half duplex (a mismatch with the other end slows one direction most)")
    if n.get("qdisc") in SHAPING: out.append(f"""sends through a {n["qdisc"]} queue (it limits or delays what leaves)""")
    if (e := n.get("rx_errors", 0) + n.get("tx_errors", 0)): out.append(f"{e} errors since boot")
    if (d := n.get("tx_dropped", 0)): out.append(f"{d} sends dropped since boot")
    return out

def net_html(R, machines: list, figs: dict) -> str:
    """Interfaces per machine (as each reported at the last read), then each lane measured between two machines."""
    def irow(g, n):
        a = n["attrs"]
        notes = _net_notes(a, [x["attrs"] for x in R.parts(g["id"]) if x["kind"] == "net"])
        sp = f"""{a["speed_mbit"]} Mbit/s""" if a.get("speed_mbit") else ("-" if a.get("state") == "up" else a.get("state") or "-")
        flag = f"""<span class="chip cv-bad" title="{C._esc("; ".join(notes))}">{C._esc(notes[0])}{f" (+{len(notes) - 1})" if len(notes) > 1 else ""}</span>""" if notes else '<span class="chip cv-ok">ok</span>' if a.get("state") == "up" else ""
        return f"""<tr><td><b>{C._esc(g["name"])}</b></td><td class="mono">{C._esc(a["name"])}</td><td>{C._esc(a.get("kind") or "")}</td><td class="cv-dim">{C._esc(a.get("driver") or "")}</td><td>{C._esc(sp)}</td><td>{C._esc(a.get("duplex") or "")}</td><td>{a.get("mtu") or ""}</td><td class="cv-dim">{C._esc(a.get("qdisc") or "")}</td><td class="mono">{C._esc(", ".join(a.get("addrs") or []))}</td><td>{flag}</td></tr>"""
    rows = "".join(irow(g, n) for g in machines for n in R.parts(g["id"]) if n["kind"] == "net")
    ifs = f"""<b>Network interfaces</b> <span class="cv-dim">as each machine reported at the last read; a red chip names what usually slows a path (hover for all)</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>machine</th><th>interface</th><th>kind</th><th>driver</th><th>link</th><th>duplex</th><th>MTU</th><th>queue</th><th>addresses</th><th></th></tr>{rows}</table></div>""" if rows else C._dim("No interfaces reported yet (a machine reports them once its Magpie is updated, then Read the machines again).")
    lanes = [ln for g in machines for ln in R.parts(g["id"]) if ln["kind"] == "lane"]
    def lrow(ln):
        f = figs.get(ln["id"], {})
        return f"""<tr><td>{C._esc(ln["name"])}</td><td class="mono cv-dim">{C._esc(ln["attrs"].get("a_addr"))} &#x2192; {C._esc(ln["attrs"].get("b_addr"))}</td><td>{_fig(f.get("to_mb_s"), "MB/s")}</td><td>{_fig(f.get("from_mb_s"), "MB/s")}</td><td>{_fig(f.get("rtt_ms"), "ms")}</td></tr>"""
    lt = f"""<b>Lanes between machines</b> <span class="cv-dim">each network two machines share, measured on its own (sent from the first machine's address there); a lane much slower one way than the other points at that direction's interface</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>lane</th><th>addresses</th><th>to</th><th>from</th><th>round trip</th></tr>{"".join(lrow(ln) for ln in lanes)}</table></div>""" if lanes else ""
    return f"""<details><summary><b>Network</b> <span class="cv-dim">interfaces and lanes</span></summary>{ifs}{lt}</details>"""

# --- Panel ---

async def p_resources(c) -> str:
    R, admin = C.AV.resources, C._admin(c.request)
    if not R.groups(): await R.sync()
    figs, provs = R.figures(prefix=True), {p["id"]: p for p in C.AV.lib.list("provider")}
    machines = [g for g in R.groups() if g["kind"] == "machine"]
    def mline(g):
        gid, parts = g["id"], R.parts(g["id"])
        cpu, ram = figs.get(f"{gid}/cpu", {}), figs.get(f"{gid}/ram", {})
        store = _disks([p for p in parts if p["kind"] == "storage"])
        link = figs.get(f"portal~{gid}", {})
        t = TESTS.get(gid, {})
        test = f"""<span class="cv-dim">{C._esc(t["notes"][-1] if t.get("notes") else "testing ...")}</span>""" if t.get("running") else C._btn("Test", "res_test", "ui-btn cv-small", face=c.face["id"], pid=gid, title="Measures the machine (processor, memory, disk), the path to it from this portal and to each other machine, and each chat model on it (speed, and memory held once loaded). Models load one after another; work running there waits its turn.") if admin and gid in provs else ""
        return f"""<tr><td><b>{C._esc(g["name"])}</b></td><td>{_fig(cpu.get("threads"))}</td><td>{_fig(cpu.get("cpu_mb_s_all"), "MB/s")}</td><td>{_fig(ram.get("total_gb"), "GB")}</td><td>{_fig(ram.get("mem_gb_s"), "GB/s")}</td><td>{_fig(figs.get(f"{gid}/storage/models", {}).get("disk_read_gb_s"), "GB/s")}</td><td>{_fig(link.get("to_mb_s"), "MB/s")} / {_fig(link.get("from_mb_s"), "MB/s")}{" | " + _fig(link.get("rtt_ms"), "ms") if link.get("rtt_ms") else ""}</td><td class="cv-dim">{store}</td><td>{test}</td></tr>"""
    head = """<tr><th>machine</th><th>threads</th><th>processor</th><th>memory</th><th>memory rate</th><th>disk read (models)</th><th>path from / to this portal | round trip</th><th>storage free / total</th><th></th></tr>"""
    ms = R.models()
    def speed(m, g):
        here = figs.get(f"""{m["id"]}@{g["id"]}""", {})
        f, mem = here.get("decode_tps"), here.get("ram_gb_loaded")
        held = f"""<br><span class="cv-dim" title="memory held once loaded ({C._esc(mem.get("source") or "")})">{_num(mem["measured"], "GB")} loaded</span>""" if mem and mem.get("measured") is not None else ""
        if f and f.get("measured") is not None: return _fig(f, "t/s") + held
        if "chat" not in m["facts"].get("capabilities", []): return '<span class="cv-dim" title="decode speed is a figure of chat models; this one does other work">n/a</span>'
        e = R.estimate(m["id"], g["id"])
        return f"""<span class="cv-dim" title="estimate from {C._esc(e.get("from", ""))}">~{_num(e["decode_tps"])}</span>""" if e else '<span class="cv-dim">-</span>'
    def manage(m):
        """Copy or move to a machine without a copy; remove one copy (the last only by its own button)."""
        have, mid = {cp["grp"]: cp["name"] for cp in m["copies"]}, m["id"]
        to = [g for g in machines if g["id"] not in have]
        pick = f"""<select name="dst" class="module-select" style="width:auto">{"".join(f'<option value="{g["id"]}">{C._esc(g["name"])}</option>' for g in to)}</select>""" if to else ""
        src = next(iter(have))
        moves = f"""<form class="row" onsubmit="return false" id="cv-mv-{abs(hash(mid))}">{pick}{C._btn("Copy", "res_copy", "ui-btn cv-small", face=c.face["id"], mid=mid, src=src, include=f"#cv-mv-{abs(hash(mid))}", title="A copy sent straight from the machine that has it; checked once there")}{C._btn("Move", "res_copy", "ui-btn cv-small", face=c.face["id"], mid=mid, src=src, move="1", include=f"#cv-mv-{abs(hash(mid))}", title="Copied, checked, then removed where it was")}</form>""" if pick else ""
        def rm(g, n):
            last = len(have) == 1
            return C._btn(f"""Remove {"the last copy" if last else "copy"} on {C._esc(next((x["name"] for x in machines if x["id"] == g), g))}""", "res_remove", "ui-btn cv-small", face=c.face["id"], mid=mid, grp=g, name=n, last="1" if last else "", confirm=f"""Remove the ONLY copy of {n}? Nothing else holds this model; it would have to be downloaded again.""" if last else f"""Remove the copy of {n} on that machine? Other copies stay.""")
        return f"""<details class="cv-dim"><summary>manage</summary>{moves}<div class="row" style="flex-wrap:wrap">{"".join(rm(g, n) for g, n in have.items())}</div><div class="cv-dim">To bring a new model onto a machine: Settings &gt; Machines &gt; Download a model file onto a machine.</div></details>"""
    def mrow(m):
        fx, here = m["facts"], {cp["grp"] for cp in m["copies"]}
        names = ", ".join(sorted({cp["name"] for cp in m["copies"]}))
        kv = figs.get(m["id"], {}).get("kv_bytes_per_token_f16", {})
        cells = "".join(f"""<td{' class="cv-dim"' if g["id"] not in here else ""} title="{"a copy is here" if g["id"] in here else "no copy here: it would be carried first"}">{speed(m, g)}</td>""" for g in machines)
        unread = f"""<br><span class="cv-dim" title="{C._esc(fx["unread"])}">header not read (hover: why)</span>""" if fx.get("unread") else ""
        return f"""<tr><td class="mono">{C._esc(names)}{unread}{manage(m) if admin else ""}</td><td>{C._esc(str(fx.get("general.architecture") or "-"))}</td><td>{_num(fx.get("params_b"), "B")}{f' <span class="cv-dim">{fx["experts_used"]}/{fx["experts"]} experts</span>' if fx.get("experts") else ""}</td><td>{_num(fx.get("bpw"))}</td><td>{_num(round(m["size"] / 1e9, 1), "GB")}</td><td>{_fig(kv, "B") if kv else "-"}</td><td>{_num(fx.get("context_length"))}</td>{cells}</tr>"""
    mhead = f"""<tr><th>model (names it has)</th><th>architecture</th><th>parameters</th><th>bits/weight</th><th>size</th><th title="computed from the header for an f16 cache; to be verified by test">KV per token</th><th>trained context</th>{"".join(f'<th>{C._esc(g["name"])} t/s</th>' for g in machines)}</tr>"""
    def path(a, b):
        if a["id"] == b["id"]: return '<td class="cv-dim">-</td>'
        f = figs.get(f"""{a["id"]}~{b["id"]}""", {}).get("to_mb_s") or figs.get(f"""{b["id"]}~{a["id"]}""", {}).get("from_mb_s")
        lag = figs.get(f"""{a["id"]}~{b["id"]}""", {}).get("rtt_ms") or figs.get(f"""{b["id"]}~{a["id"]}""", {}).get("rtt_ms")   # a round trip is the same both ways
        return f"<td>{_fig(f, 'MB/s')}{' | ' + _fig(lag, 'ms') if lag else ''}</td>" if f else '<td class="cv-dim" title="not tested yet: Test on either machine measures it">-</td>'
    paths = f"""<b>Paths between machines</b> <span class="cv-dim">row to column, as measured by Test on either one; after the bar: the round trip of a small request (the delay alone)</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>from &#x2192; to</th>{"".join(f'<th>{C._esc(g["name"])}</th>' for g in machines)}</tr>{"".join(f'<tr><td><b>{C._esc(a["name"])}</b></td>{"".join(path(a, b) for b in machines)}</tr>' for a in machines)}</table></div>""" if len(machines) > 1 else ""
    poll = f"""<div id="cv-res-tests" hx-get="{C._P}/res_tests" hx-trigger="load, every 3s" hx-swap="innerHTML"></div>""" if TESTS else ""
    every = C._btn("Test every machine", "res_test_all", face=c.face["id"], title="Each machine in turn, never two at once (so one test's traffic does not slow another's): the machine, its paths, its chat models. Takes a while; work running on a machine waits its turn while its models are tested.") if admin and not any(t.get("running") for t in TESTS.values()) else ""
    some = f"""<details><summary class="cv-dim">Test a set of machines (the paths among them)</summary><form class="row" style="flex-wrap:wrap" id="cv-test-set" onsubmit="return false">{"".join(f'<label class="chip"><input type="checkbox" name="ids" value="{C._esc(g["provider"])}"> {C._esc(g["name"])}</label>' for g in machines if g.get("provider") and C.AV.lib.has("provider", g["provider"]) and not C.AV.lib.get("provider", g["provider"]).get("speaks"))}<label class="cv-dim" title="Also load and time each ticked machine's chat models (slow); without it only the machines and the paths between them are measured"><input type="checkbox" name="models" value="1"> their models too</label>{C._btn("Test these", "res_test_all", "ui-btn cv-small", face=c.face["id"], include="#cv-test-set")}</form>{C._dim("For a group that will work together (one split model, a pipeline across machines): each ticked machine in turn measures its path to every other ticked one, so the table below fills for that group only.")}</details>""" if every else ""
    top = f"""<div class="row">{C._btn("Read the machines again", "res_sync", face=c.face["id"], title="Asks every machine for its parts, places and models. Measurements are kept.")}{every}<span class="grow"></span></div>{some}"""
    return f"""{poll}{top}{C._dim("Bold: measured (number of tests). Grey 'says': what it reports or what follows from its labels. ~: an estimate from what was measured elsewhere. A test replaces nothing: each one is added to the figures.")}
               <div class="scroll-pane"><table class="cv-tbl">{head}{"".join(mline(g) for g in machines) or '<tr><td colspan="9" class="cv-dim">no machine yet</td></tr>'}</table></div>
               {paths}
               {net_html(R, machines, figs)}
               <b>Models</b> <span class="cv-dim">one row per distinct file, under every name it has; a column per machine: decode speed there</span>
               <div class="scroll-pane"><table class="cv-tbl">{mhead}{"".join(mrow(m) for m in ms) or '<tr><td class="cv-dim">no models listed</td></tr>'}</table></div>"""

def tests_html() -> str:
    """What the tests started from this page are doing, or what they ended with."""
    rows = "".join(f"""<div class="row"><b>{C._esc(pid)}</b><span class="grow cv-dim">{C._esc(" | ".join(t["notes"][-3:]))}</span><span class="chip {"cv-mid" if t["running"] else "cv-ok"}">{"testing" if t["running"] else "done: read again to see the figures"}</span></div>""" for pid, t in TESTS.items())
    return rows

# --- Handlers ---

def _p(gid: str) -> dict: return C.AV.lib.get("provider", gid)

async def p_models(c) -> str:
    """Models as a resource of the whole set-up rather than of one machine: one row per distinct file (under every name it has), a column per machine - a copy is there or not - and, for an admin, in each cell: copy it there, move it there, or remove that copy. What a model can do and its size come from what the machines list; where it runs is placement's choice among the machines that hold it or can be given it."""
    R, admin = C.AV.resources, C._admin(c.request)
    if not R.groups(): await R.sync()
    machines, ms, names = [g for g in R.groups() if g["kind"] in ("machine", "server")], R.models(), {g["id"]: g["name"] for g in R.groups()}   # server: one that does not speak the node contract (an Ollama); its models are shown, and are its own to move or remove
    does, kinds_of = {}, {g["id"]: g["kind"] for g in R.groups()}
    for o in C._offers_now():
        for a in o["assets"]: does.setdefault(a["name"], set()).update(a.get("capabilities") or [])
    def cell(m, g):
        cp = next((x for x in m["copies"] if x["grp"] == g["id"]), None)
        if g["kind"] == "server":
            if not cp: return """<td class="cv-dim" title="A server that keeps its own files: a model comes onto it by its own pull (below the table)">-</td>"""
            rm = C._btn("remove", "res_remove", "ui-btn cv-small cv-danger", face=c.face["id"], mid=m["id"], grp=g["id"], name=cp["name"], last="1" if len(m["copies"]) == 1 else "", confirm=f"""Remove {cp["name"]} from {g["name"]}? The server deletes it itself.{" This is the only copy anywhere." if len(m["copies"]) == 1 else ""}""") if admin else ""
            return f"""<td><span class="chip cv-ok" title="{C._esc(cp["location"])}">here</span> {rm}</td>"""
        if cp:
            only = len(m["copies"]) == 1
            rm = C._btn("remove", "res_remove", "ui-btn cv-small cv-danger", face=c.face["id"], mid=m["id"], grp=g["id"], name=cp["name"], last="1" if only else "", confirm=f"""Remove {cp["name"]} from {g["name"]}?{" This is the only copy anywhere: it will be gone." if only else " Other copies stay."}""") if admin else ""
            return f"""<td><span class="chip cv-ok" title="{C._esc(cp.get("location") or "")}">here</span> {rm}</td>"""
        if not admin or not m["copies"]: return """<td class="cv-dim">-</td>"""
        if not (src := next((x["grp"] for x in m["copies"] if kinds_of.get(x["grp"]) == "machine"), "")): return """<td class="cv-dim" title="Held only by a server that keeps its own files: it cannot send them from here">-</td>"""
        give = lambda label, move: C._btn(label, "res_copy", "ui-btn cv-small", face=c.face["id"], mid=m["id"], src=src, dst=g["id"], move="1" if move else "", confirm=f"""{"Move" if move else "Copy"} it from {names.get(src, src)} to {g["name"]}?{" It is removed from " + names.get(src, src) + " once the copy is checked." if move else ""}""", title=f"""Sent straight from {names.get(src, src)}; checked by size and header once there""")
        return f"""<td class="cv-dim">- {give("copy here", False)}{give("move here", True)}</td>"""
    def row(m):
        nm = sorted({cp["name"] for cp in m["copies"]})
        kinds = sorted({k for n in nm for k in does.get(n, [])})
        return f"""<tr><td class="mono" style="overflow-wrap:anywhere">{C._esc(", ".join(nm))}</td><td class="cv-dim">{C._esc(", ".join(kinds) or "-")}</td><td>{_num(round(m["size"] / 1e9, 1), "GB")}</td>{"".join(cell(m, g) for g in machines)}</tr>"""
    poll = f"""<div id="cv-res-tests" hx-get="{C._P}/res_tests" hx-trigger="load, every 3s" hx-swap="innerHTML"></div>""" if TESTS else ""
    head = f"""<tr><th>model (names it has)</th><th>does</th><th>size</th>{"".join(f"<th>{C._esc(g['name'])}</th>" for g in machines)}</tr>"""
    servers = [g for g in machines if g["kind"] == "server"]
    pulls = "".join(f"""<form class="row" style="flex-wrap:wrap" onsubmit="return false" id="cv-pull-{n}"><span class="cv-key">{C._esc(g["name"])}</span><input name="model" class="module-select" placeholder="model name, as its registry names it" title="For example qwen3:8b. The server fetches it itself, from the registry it is set to use (an outside server unless it was pointed elsewhere).">{C._btn("Pull", "res_pull", "ui-btn cv-small", face=c.face["id"], grp=g["id"], include=f"#cv-pull-{n}")}<span class="cv-dim">or on that machine: <span class="mono">ollama pull &lt;name&gt;</span> | <span class="mono">ollama rm &lt;name&gt;</span></span></form>""" for n, g in enumerate(servers)) if admin else ""
    limits = f"""<div class="sec">Servers that are not nodes</div>{C._dim("They list their models and run them; from here a model can be removed or pulled. They do not say where their files are, so nothing is copied to or from them, and their memory and loading are their own.")}{pulls}""" if servers else ""
    return f"""{poll}<div class="row">{C._btn("Read the machines again", "res_sync", face=c.face["id"], title="Asks every machine for its models now")}<span class="grow"></span></div>
               {C._dim("Every model the machines hold, and where each copy is. A model is one file however many names it has. Which machine runs a piece of work is chosen when the work starts, among the machines that hold the model; who may use which is set under Access.")}
               <div class="scroll-pane"><table class="cv-tbl">{head}{"".join(row(m) for m in sorted(ms, key=lambda m: sorted(cp["name"] for cp in m["copies"])[:1])) or '<tr><td class="cv-dim">no models listed yet: Read the machines again</td></tr>'}</table></div>{limits}"""

async def _h_copy(request, payload, imr):
    """A copy (or a move: copy, check, then remove where it was) in the background, followed on this page."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin copies or moves models.", True), "cv-msg")
    R, mid, src, dst = C.AV.resources, payload["mid"], _p(payload["src"]), _p(payload["dst"])
    name = next(cp["name"] for cp in R.copies(mid) if cp["grp"] == src["id"])
    TESTS[f"model {name}"] = t = {"running": True, "notes": [f"""{"moving" if payload.get("move") else "copying"} to {dst.get("name") or dst["id"]}"""]}
    async def go():
        try:
            got = await R.copy(mid, src, name, dst, t["notes"].append)
            if payload.get("move") and got["copied"]: t["notes"].append(f"""removed where it was: {(await R.remove(mid, src, name))}""")
        except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
        t["running"] = False
    asyncio.create_task(go())
    return await C._refresh(request, imr, payload["face"], C._note(f"""{"Moving" if payload.get("move") else "Copying"} {C._esc(name)}: this page follows it."""))

async def _h_remove(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin removes models.", True), "cv-msg")
    try: got = await C.AV.resources.remove(payload["mid"], _p(payload["grp"]), payload["name"], bool(payload.get("last")))
    except C.PROV.ProviderError as e: got = {"removed": False, "why": str(e)}
    return await C._refresh(request, imr, payload["face"], C._note(f"""Removed: {got["freed_gb"]} GB freed.""" if got["removed"] else f"""Not removed: {got["why"]}""", not got["removed"]))

async def _h_pull(request, payload, imr):
    """A model pulled onto a server that fetches its own, in the background, followed on this page."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin brings models onto a server.", True), "cv-msg")
    p, name = _p(payload["grp"]), payload.get("model", "").strip()
    if not name: return imr.oob(C._note("Name the model to pull.", True), "cv-msg")
    TESTS[f"model {name}"] = t = {"running": True, "notes": [f"""{p.get("name") or p["id"]} is pulling it; nothing is shown of how far it is until it is done"""]}
    async def go():
        try: t["notes"].append(f"""done: {await C.AV.resources.pull(p, name)}""")
        except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
        t["running"] = False
    PULLS.add(task := asyncio.create_task(go()))
    task.add_done_callback(PULLS.discard)
    return await C._refresh(request, imr, payload["face"], C._note(f"Pulling {C._esc(name)}: this page follows it."))

async def _h_sync(request, payload, imr):
    C.PROV.forget()   # asked by a person: machines that were silent are tried again now
    got = await C.AV.resources.sync()
    bad = [f"""{r["group"]}: {r["error"]}""" for r in got if r.get("error")]
    return await C._refresh(request, imr, payload["face"], C._note("Read again." + (" Not reached: " + "; ".join(bad) if bad else ""), bool(bad)))

def _models_on(p: dict) -> list:
    """The chat models on a machine that are on (not standby), as (name there, model id)."""
    return [(cp["name"], m["id"]) for m in C.AV.resources.models() for cp in m["copies"] if cp["grp"] == p["id"] and "chat" in m["facts"].get("capabilities", []) and not cp["location"]]

async def _run(p: dict, among: list = None, models: bool = True):
    """One machine's tests, followed in TESTS; a stop keeps what was measured before it. among: only the paths to these machines; models False: no model is loaded (paths and the machine only)."""
    ms = _models_on(p) if models else []
    TESTS[p["id"]] = t = {"running": True, "notes": [f"""testing: the machine, its paths{f" to {len(among)} other(s)" if among is not None else ""}, {len(ms)} model(s)"""]}
    try: t["result"] = await C.AV.resources.characterize(p, ms, t["notes"].append, among)
    except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
    t["running"] = False

async def _h_test(request, payload, imr):
    """A machine's tests started in the background; the page follows them."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin starts tests: they load models on the machine.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    asyncio.create_task(_run(p))
    return await C._refresh(request, imr, payload["face"], C._note(f"""Testing {C._esc(p.get("name") or p["id"])}: this page follows it."""))

async def _h_test_all(request, payload, imr):
    """Every machine that speaks the node contract, one after another, in the background - or only those ticked ("ids"), with the paths among them alone, and their models only when asked ("models")."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin starts tests: they load models on the machines.", True), "cv-msg")
    ids = payload.get("ids") or []
    ids = [ids] if isinstance(ids, str) else ids
    ps = [p for p in C.AV.lib.list("provider") if not p.get("speaks") and (not ids or p["id"] in ids)]
    if ids and len(ps) < 2: return imr.oob(C._note("Tick at least two machines: the test measures the paths between them.", True), "cv-msg")
    for p in ps: TESTS[p["id"]] = {"running": True, "notes": ["waiting its turn"]}
    async def go():
        await C.AV.resources.sync()
        for p in ps: await (_run(p, [q["id"] for q in ps], bool(payload.get("models"))) if ids else _run(p))
    asyncio.create_task(go())
    return await C._refresh(request, imr, payload["face"], C._note(f"""Testing {len(ps)} machine(s) one after another: this page follows them."""))
