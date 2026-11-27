"""figures.py - Corvid's panels over what runs measured, beside corvid.py: a chart of one figure against another (chart), what was used, by machine and asset (usage), and the pool itself: what every machine holds and what starting it would take there (fits). The rows come from Aviary's measurement store (AV.measure, filled from the run folders); the charts are the portal's (BI.Charts).
Nothing here knows what a figure means: the names offered are those the runs have. A person who is not an admin sees only the runs they started.
C is a live view of corvid.py's globals, set when Corvid starts."""
import re, json, time, asyncio

C = None
WHEN = "t"   # the x choice that is not a figure: when the work ended
SINCE = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400, "all": 0}

def _owner(request) -> str: return "" if C._admin(request) else C._user(request)   # whose runs a person sees: an admin everyone's, anyone else their own
def _opts(pairs: list, cur: str) -> str: return "".join(f"""<option value="{C._esc(v)}"{" selected" if str(v) == str(cur) else ""}>{C._esc(label)}</option>""" for v, label in pairs)

# --- Panel: chart ---

async def p_chart(c) -> str:
    """One figure against another, from every run of a plan (and the runs its steps made). The panel's data gives the first choice ("plan", "x", "y", "by", "split", "logx", "logy"); what is chosen on the page is kept by the face's tab (ch_*)."""
    M, s, t = C.AV.measure, c.spec, c.tab
    ch = {k: t.get("ch_" + k, s.get(k, d)) for k, d in (("plan", ""), ("x", WHEN), ("y", "seconds"), ("by", "asset"), ("split", ""), ("logx", ""), ("logy", ""), ("lines", "1"))}
    names = M.names(ch["plan"])
    if ch["y"] not in names and names: ch["y"] = names[0]
    fid = f"cv-chart-f-{c.face['id']}"
    sel = lambda k, pairs, title: f"""<label class="row cv-dim" title="{C._esc(title)}">{k}<select name="ch_{k}" class="module-select">{_opts(pairs, ch[k])}</select></label>"""
    tick = lambda k, label: f"""<label class="row cv-dim"><input type="hidden" name="ch_{k}" value=""><input type="checkbox" name="ch_{k}" value="1"{" checked" if ch[k] else ""}>{label}</label>"""
    form = f"""<form id="{fid}" class="row" style="flex-wrap:wrap" onsubmit="return false">{sel("plan", [("", "(every plan)")] + M.plans(), "whose runs")}{sel("x", [(WHEN, "(when it ended)")] + [(n, n) for n in names], "across")}{sel("y", [(n, n) for n in names], "up")}{sel("by", [(k, k) for k in M.BY], "a line per")}{sel("split", [("", "(nothing)")] + [(n, n) for n in names], "and a line per value of this figure too")}{tick("logx", "log x")}{tick("logy", "log y")}{tick("lines", "lines")}{C._btn("Show", "open_tab", id=c.host, include="#" + fid)}{C._btn("Read the runs again", "measure_rebuild", "ui-btn cv-small", title="Fills the store again from every run folder there is; rows of removed runs stay", face=c.face["id"]) if C._admin(c.request) else ""}</form>"""
    if not names: return form + C._dim("No run has measured anything yet. Runs that do work through a role (a model, a knowledge group, a machine) leave their figures here as they end.")
    pts = M.points(ch["x"], ch["y"], by=ch["by"], plan=ch["plan"], owner=_owner(c.request), split=ch["split"])
    series = {}
    for p in pts: series.setdefault(" | ".join(x for x in (str(p["by"] or "-"), f"""{ch["split"]} {p["split"]:g}""" if ch["split"] and p["split"] is not None else "") if x), []).append((p["x"], p["y"], f"""{C._when(p["t"])} {p["run"]} {p["step"]}: {ch["x"]} {p["x"]:g}, {ch["y"]} {p["y"]:g}""" + (f""" on {p["provider"]}""" if p["provider"] else "")))
    svg = C.BI.Charts.xy([{"name": k, "points": v} for k, v in series.items()], "when it ended" if ch["x"] == WHEN else ch["x"], ch["y"], logx=bool(ch["logx"]) and ch["x"] != WHEN, logy=bool(ch["logy"]), lines=bool(ch["lines"]), zero=not ch["logy"], xfmt=(lambda v: time.strftime("%m-%d %H:%M", time.localtime(v))) if ch["x"] == WHEN else None)
    rows = "".join(f"""<tr><td><span style="color:{C.BI.Charts.hue(k)}">&#x25A0;</span> {C._esc(k)}</td><td>{len(v)}</td><td>{min(p[1] for p in v):.4g}</td><td>{sum(p[1] for p in v) / len(v):.4g}</td><td>{max(p[1] for p in v):.4g}</td></tr>""" for k, v in series.items())
    return f"""{form}{svg}<table class="cv-tbl"><tr><th>line</th><th>points</th><th>least {C._esc(ch["y"])}</th><th>mean</th><th>most</th></tr>{rows}</table>{C._dim(f"{len(pts)} points. Hover or press a point for the run and step it came from; the run list opens any of them.")}"""

# --- Panel: usage ---

async def p_usage(c) -> str:
    """What was used since a time, per machine, asset and capability: how often, how long, how much failed, and the provider's own figures summed. The panel's data: "since" (day, week, month, all) as the first choice; the tab keeps what is chosen (us_since)."""
    since = c.tab.get("us_since") or c.spec.get("since", "week")
    rows = C.AV.measure.usage(time.time() - SINCE[since] if SINCE[since] else 0, owner=_owner(c.request))
    pick = "".join(f"""<span class="chip cv-link{" cv-on" if k == since else ""}" {C._act("open_tab", id=c.host, us_since=k)}>{k}</span>""" for k in SINCE)
    if not rows: return f"""<div class="row">{pick}</div>{C._dim("Nothing used in this time.")}"""
    def figs(r): return ", ".join(f"""{n} {f["sum"]:.4g}""" for n, f in sorted(r["figures"].items()) if n.endswith("_n")) or "-"
    table = "".join(f"""<tr><td>{C._esc(r["provider"])}</td><td class="mono">{C._esc(r["asset"]) or "-"}</td><td>{C._esc(r["capability"])}</td><td>{r["n"]}</td><td>{r["seconds"] or 0:.1f}</td><td>{r["failed"] or ""}</td><td class="cv-dim">{C._esc(figs(r))}</td></tr>""" for r in rows)
    bars = C.BI.Charts.bars([(f"""{r["asset"] or r["capability"]} @ {r["provider"]}""", round(r["seconds"] or 0, 1), f"""{r["n"]} times, {r["seconds"] or 0:.1f} s""") for r in rows[:12]], unit=" s")
    return f"""<div class="row">{pick}</div>{bars}<table class="cv-tbl"><tr><th>machine</th><th>asset</th><th>capability</th><th>times</th><th>seconds</th><th>failed</th><th>counts (sum)</th></tr>{table}</table>"""

async def _h_measure_rebuild(request, payload, imr):
    """The measurement store read again from every run folder there is (admin). Rows of runs removed since are kept."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin reads the store again.", True), "cv-msg")
    n = C.AV.measure.rebuild()
    return await C._refresh(request, imr, payload["face"], C._note(f"Read {n} runs again from their folders."))

# --- Panel: now (what is under way: runs here, and each machine's jobs, speed and memory) ---

NOW_EVERY_S = 3

async def p_now(c) -> str:
    return f"""<div id="cv-now" hx-get="{C._P}/now?face={C._esc(c.face["id"])}" hx-trigger="load, every {NOW_EVERY_S}s" hx-swap="innerHTML">{C._dim("asking the machines ...")}</div>"""

def _tps(j: dict) -> str: return f"""{j["live_tps"]} t/s so far""" if j.get("live_tps") else f"""{(j.get("timings") or {}).get("tps")} t/s""" if (j.get("timings") or {}).get("tps") else ""

async def now_html(request, face_id: str) -> str:
    """Runs under way that this person may see, then (for an admin) every machine: its jobs running and waiting with their speed, what holds memory, and the last ones finished."""
    live = sorted((r for r in C.AV.director.runs.values() if r.meta.get("state") in ("running", "stopping") and (C._admin(request) or r.meta.get("owner") == C._user(request))), key=lambda r: r.meta.get("created", 0))
    rows = "".join(f"""<tr><td>{C._esc(r.plan.get("name") or r.id)}</td><td class="cv-dim">{C._esc(r.meta.get("owner", ""))}</td><td>{C._esc(", ".join(r.view()["busy"]) or "-")}</td><td>{round(time.time() - r.meta.get("created", time.time()))} s</td></tr>""" for r in live)
    out = f"""<b>Runs under way</b><table class="cv-tbl"><tr><th>run</th><th>for</th><th>steps working</th><th>for</th></tr>{rows or '<tr><td colspan="4" class="cv-dim">none</td></tr>'}</table>"""
    if not C._admin(request): return out
    async def one(p):
        try: return p, await C.PROV.machine(p, "GET", "/control/status", timeout=8.0), ""
        except C.PROV.ProviderError as e: return p, None, C.older(e, "say what it is doing")
    provs = C.AV.lib.list("provider")
    src, urls = {re.sub(r"[^A-Za-z0-9_-]", "_", q["id"])[:40]: q.get("name") or q["id"] for q in provs}, {_host(q.get("url")) for q in provs}   # a model source's name on a machine -> the machine it reaches (spread_view._src); urls: a source that is a machine of this portal (by address, whatever it was named) has its own table
    got, total = await asyncio.gather(*(one(p) for p in provs if not p.get("speaks"))), {"n": 0, "tps": 0.0}
    for p, st, err in got:
        for j in (st or {}).get("requests") or []:
            if j.get("adapter") != "remote" and j["capability"] != "warm": total["n"], total["tps"] = total["n"] + 1, total["tps"] + float(j.get("live_tps") or (j.get("timings") or {}).get("tps") or 0)
    out += C._dim(f"""All machines together: {total["n"]} request(s) working here and there, about {round(total["tps"])} t/s (requests a machine sent on to another are counted where they run).""")
    for p, st, err in got:
        name = C._esc(p.get("name") or p["id"])
        if not st:
            out += f"""<div class="cv-machine"><b>{name}</b> {C._note(err, True)}</div>"""
            continue
        m = st.get("memory") or {}
        mine = [j for j in st.get("requests") or [] if j["capability"] != "warm" and j.get("adapter") != "remote"]   # requests passed on to another machine are shown where they run, not here
        held = ", ".join(f"""{C._esc(s["name"])} {s.get("rss_gb") or 0:.1f} GB""" for s in st.get("services") or [] if s.get("pid"))
        recent = " | ".join(f"""{C._esc(str(d.get("model") or d.get("kind")))} {d.get("seconds")} s {C._esc(d.get("outcome") or "")}""" for d in list(st.get("recent") or [])[-4:])
        mem = f"""{m.get("ram_avail_gb", "?")} of {m.get("ram_total_gb", "?")} GB free""" + (f""" | GPU {m["gpu_used_gb"]} GB used""" if m.get("gpu_used_gb") else "") + (f""" | load {m["load1"]}""" if m.get("load1") is not None else "") + (f""" | {m["temp_c"]} C""" if m.get("temp_c") else "") if m else ""
        out += f"""<div class="cv-machine"><div class="row"><b class="grow">{name}</b><span class="cv-dim">{mem} | {sum(1 for j in mine if j["phase"] != "queued")} working, {sum(1 for j in mine if j["phase"] == "queued")} waiting here</span></div>{_streams(p["id"], mine)}{C._dim("holding memory: " + held) if held else ""}{C._dim("last finished: " + recent) if recent else ""}</div>"""
        out += _sources_now(name, {**st, "sources": {n: v for n, v in (st.get("sources") or {}).items() if n not in src and _host(v.get("url")) not in urls}})
    out += "".join(await asyncio.gather(*(_server_now(p) for p in provs if p.get("speaks"))))
    return out + C._dim(f"Every {NOW_EVERY_S} s. A running job's speed is counted from what it has streamed (about a token a piece); a finished one's is the program's own figure.")

def _host(url) -> str: return re.sub(r"^\w+://", "", str(url or "")).rstrip("/").lower()

def _ctx(j: dict) -> tuple:
    """A request's context as its machine reads it while it streams: tokens held (of them reused from the cache) against its share of the window, and the memory they take."""
    x = j.get("ctx") or {}
    if not x.get("of"): return "-", "-"
    pct, reused = f""" ({round(100 * x["used"] / x["of"])}%)""" if x.get("used") else "", f""" - {x["cached"]} reused""" if x.get("cached") else ""
    return f"""{x.get("used", 0)} / {x["of"]}{pct}{reused}""", f"""{x.get("gb", 0)} GB"""

def _stream(j: dict) -> str:
    used, gb = _ctx(j)
    return f"""<tr><td>{C._esc(j["phase"])}</td><td>{C._esc(j["capability"])}</td><td class="mono">{C._esc(str(j.get("model") or ""))}</td><td>{j["age_s"]} s</td><td>{j.get("out_n") or 0}</td><td>{_tps(j) or "-"}</td><td>{C._esc(used)}</td><td>{gb}</td></tr>"""

def _streams(pid: str, jobs: list) -> str:
    """A machine's requests that run there: per kind of work and model a line for all of them together, each working request on its own line (tokens written, speed, its context in tokens and memory), and the waiting ones folded under a line of their own. Requests passed on to another machine are shown there."""
    by, rows = {}, ""
    for j in jobs: by.setdefault((j["capability"], str(j.get("model") or "")), []).append(j)
    for (cap, model), js in sorted(by.items()):
        work, wait = [j for j in js if j["phase"] != "queued"], [j for j in js if j["phase"] == "queued"]
        rows += f"""<tr class="cv-sum"><td><b>all</b></td><td>{C._esc(cap)}</td><td class="mono">{C._esc(model)}</td><td>{max((j["age_s"] for j in work), default=0)} s longest</td><td>{sum(int(j.get("out_n") or 0) for j in work)}</td><td>{round(sum(float(j.get("live_tps") or 0) for j in work))} t/s</td><td>{len(work)} working, {len(wait)} waiting</td><td>{round(sum(float((j.get("ctx") or {}).get("gb") or 0) for j in work), 2)} GB</td></tr>"""
        rows += "".join(_stream(j) for j in sorted(work, key=lambda j: -j["age_s"]))
        rows += f"""<tr><td colspan="8"><details id="cv-wait-{C._esc(pid)}-{C._esc(cap)}-{re.sub(r"[^A-Za-z0-9_-]", "_", model)}"><summary class="cv-dim">{len(wait)} waiting - longest {max(j["age_s"] for j in wait)} s</summary><table class="cv-tbl">{"".join(_stream(j) for j in sorted(wait, key=lambda j: -j["age_s"]))}</table></details></td></tr>""" if wait else ""
    return f"""<table class="cv-tbl"><tr><th>state</th><th>doing</th><th>model</th><th>for</th><th>written</th><th>speed</th><th>context: tokens held / its window</th><th>context memory</th></tr>{rows or '<tr><td colspan="8" class="cv-dim">nothing running</td></tr>'}</table>"""

def _loaded(name: str, note: str, loaded: list) -> str:
    """What a server outside Magpie (an Ollama) holds loaded, as it says: each model's size and quantization, memory, the part on the GPU, context, kept until."""
    def row(x):
        size, vram = int(x.get("size") or 0), int(x.get("vram") or 0)
        gpu = f"""{vram / 1e9:.1f} GB ({round(100 * vram / size)}%)""" if size and vram else "none (processor only)" if size else "-"
        return f"""<tr><td class="mono">{C._esc(x.get("name"))}</td><td>{C._esc(" ".join(str(v) for v in (x.get("params"), x.get("quant")) if v))}</td><td>{size / 1e9:.1f} GB</td><td>{gpu}</td><td>{C._esc(x.get("context") or "-")}</td><td class="cv-dim">{C._esc(str(x.get("until") or "")[11:16])}</td></tr>"""
    return f"""<div class="cv-machine"><div class="row"><b class="grow">{name}</b><span class="cv-dim">{note}</span></div><table class="cv-tbl"><tr><th>model</th><th>size, quant</th><th>memory</th><th>on the GPU</th><th>context</th><th>kept until</th></tr>{"".join(row(x) for x in loaded) or '<tr><td colspan="6" class="cv-dim">nothing loaded</td></tr>'}</table></div>"""

async def _server_now(p: dict) -> str:
    """A server added as a provider of its own that does not speak the node contract (an Ollama), as far as its translator maps what it holds loaded."""
    name = C._esc(p.get("name") or p["id"])
    try: got = (await C.PROV.ask(p, "state", timeout=8.0))["loaded"]
    except C.PROV.ProviderError as e:
        why = C._dim(f"""speaks {C._esc(p["speaks"])}: its translator says nothing of what it holds loaded (no state). A copy of that translator in your library from before keeps the shipped one out: remove or update the copy.""") if "has no state" in str(e) else C._note(str(e), True)
        return f"""<div class="cv-machine"><b>{name}</b> {why}</div>"""
    return _loaded(name, f"""speaks {C._esc(p["speaks"])}, reached by the portal: what it holds loaded, as it says (its requests are not reported)""", got)

def _sources_now(machine: str, st: dict) -> str:
    """The servers a machine passes work on to (its remote sources: an Ollama on another computer), each with what it holds loaded and how many requests this machine has sent there now."""
    return "".join(_loaded(f"""{C._esc(n)} <span class="cv-dim">via {machine}</span>""", f"""{C._esc(s.get("url") or "")}{" | Ollama " + C._esc(s["version"]) if s.get("version") else ""} | {s.get("working", 0)} request(s) sent there now{" | " + C._esc(s["error"]) if s.get("error") else ""} | requests that reach it some other way are not seen""", s.get("loaded") or []) for n, s in sorted((st.get("sources") or {}).items()))

# --- Panel: fits (the pool of what every machine holds, and each machine's own answer to what starting one would take there) ---

def _starts(a: dict) -> bool: return a.get("kind", "model") == "model" and bool(a.get("capabilities"))   # what a machine has to start to serve: a model, not a body of data
def _size(n) -> str: return f"{n / 1e9:.1f} GB" if n and n > 5e7 else "-"

async def p_fits(c) -> str:
    """Every asset the person may use, by machine, with which pools hold it; "What fits here" asks that machine what starting each would take as things are."""
    out, pools = "", C.AV.lib.list("pool")
    for o in C._mine(c.request, await C._offers()):
        p, pname = o["p"], o["p"].get("name") or o["p"]["id"]
        if o["error"]:
            out += C._note(o["error"], True)
            continue
        if p.get("speaks") and (C.PROV.translator(p["speaks"]).get("assets") or {}).get("models") is False:   # its assets are files of its own kind (poses in a pose bridge): counted, not listed among models
            out += f"""<div class="cv-machine"><b>{C._esc(pname)}</b> <span class="cv-dim">{len(o["assets"])} file(s) of its own - not models: they are picked where they are used (a pose in Sunbird, a pipeline's form)</span></div>"""
            continue
        rows = "".join(f"""<tr><td class="mono">{C._esc(a["name"])}{f' <span class="chip cv-mid" title="its program is installed and off">{C._esc(a["standby"])} off</span>' if a.get("standby") else ""}</td><td class="cv-dim">{C._esc(", ".join(a.get("capabilities") or [])[:90])}</td><td>{_size(a.get("size"))}</td><td class="cv-dim">{C._esc(", ".join(q.get("name") or q["id"] for q in pools if C.AV.access.holds(q, p["id"], a["name"])))}</td></tr>""" for a in o["assets"])
        ask = "" if p.get("speaks") else C._btn("What fits here", "fits_ask", face=c.face["id"], pid=p["id"], title="Asks this machine, for each model it holds, what starting it would take as things are. Nothing is started.")
        out += f"""<details class="cv-machine"{" open" if len(o["assets"]) <= 12 else ""}><summary><b>{C._esc(pname)}</b> <span class="cv-dim">{len(o["assets"])} offered</span></summary><div class="row"><span class="grow"></span>{ask}</div><div id="cv-fits-{C._esc(p["id"])}"></div><table class="cv-tbl"><tr><th>asset</th><th>does</th><th>size</th><th>in pools</th></tr>{rows}</table></details>"""
    return f"""{C._dim("Everything the machines offer that is open to you: the pool work is placed from. A role is filled from it by a profile's candidates, a named pool, or a pin (Settings, Providers and roles; Library, Pools).")}{out or C._dim("no provider yet")}"""

def _weighed(need: dict) -> str:
    """What the machine's own planner weighed for a model (each choice it could load, the chosen one marked) and how its estimate compares with a real load, folded under the row."""
    rows, said = "".join(f"""<div class="{"" if c.get("chosen") else "cv-dim"}">{C._esc(c["label"])}</div>""" for c in need.get("choices") or []), " - " + C._esc(need["checked"]) if need.get("checked") else ""
    return f"""<details><summary>choices{said}</summary>{rows}</details>""" if rows or said else ""

async def _fits_html(face_id: str, p: dict, assets: list, admin: bool) -> str:
    gate = asyncio.Semaphore(4)
    async def one(a):
        async with gate:
            try: return a, await C.PROV.machine(p, "POST", "/plan", {"capability": a["capabilities"][0], "model": a["name"]}, timeout=60.0), ""
            except C.PROV.ProviderError as e: return a, None, C.older(e, "say what a model would take")
    got = await asyncio.gather(*(one(a) for a in assets if _starts(a)))
    chip = {"yes": ("cv-ok", "fits"), "wait": ("cv-mid", "fits when its work in progress ends"), "yes_if": ("cv-mid", "fits if changed"), "no": ("cv-bad", "does not fit")}
    def row(a, pl, err):
        if not pl: return f"""<tr><td class="mono">{C._esc(a["name"])}</td><td colspan="4">{C._note(err, True)}</td></tr>"""
        ways = "".join(C._btn(C._esc(w["label"]), "fits_apply", "ui-btn cv-small", face=face_id, pid=p["id"], set=json.dumps(w["set"]), confirm=f"""Change this machine's settings so it fits? {w.get("cost", "")}""") for w in pl.get("ways", []) if admin and w.get("fits") and not w.get("auto") and w.get("set"))
        need = pl["needs"]
        return f"""<tr><td class="mono">{C._esc(a["name"])}</td><td><span class="chip {chip[pl["fits"]][0]}">{"running" if pl.get("running") else chip[pl["fits"]][1]}</span></td><td title="{C._esc(json.dumps(need.get("parts") or {}))}">{pl.get("need_gb", need.get("ram_gb", 0)):.1f} GB <span class="cv-dim">{C._esc(need.get("source", ""))}</span></td><td class="cv-dim">{C._esc(pl.get("will", ""))}{_weighed(need)}</td><td>{ways}</td></tr>"""
    have = next((pl["have"] for _, pl, _ in got if pl), None)
    mem = C._dim(f"""{have["free_gb"]} GB free of {have["ram_total_gb"]} ({have["reserve_gb"]} kept for the system); {have["free_if_idle_stopped_gb"]} if idle programs stop, {have["free_if_alone_gb"]} alone. Holding memory now: {C._esc(", ".join(f"{h['service']} {h['ram_gb']} GB" for h in have["holders"]) or "nothing")}.""") if have else ""
    return f"""{mem}<table class="cv-tbl"><tr><th>model</th><th>now</th><th>needs</th><th>what the machine would do</th><th>ways</th></tr>{"".join(row(*g) for g in got) or "<tr><td>nothing here needs starting</td></tr>"}</table>"""

async def _h_fits_ask(request, payload, imr):
    p = C.AV.lib.get("provider", payload["pid"])
    assets = next(o["assets"] for o in C._mine(request, await C._offers()) if o["p"]["id"] == p["id"])
    return imr.oob(await _fits_html(payload["face"], p, assets, C._admin(request)), f"""cv-fits-{p["id"]}""")

async def _h_fits_apply(request, payload, imr):
    """One of the ways a machine named to make a model fit: its settings changed as that way says (the machine keeps the version before)."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes a machine's settings.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try:
        for key, v in json.loads(payload["set"]).items(): await C.PROV.machine(p, "PATCH", "/settings", {"path": key, "value": v, "source": f"{C._user(request)} from the portal"}, timeout=30.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    return (await _h_fits_ask(request, payload, imr)).oob(C._note(f"""Changed on {p.get("name") or p["id"]}: {payload["set"]}"""), "cv-msg")

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_measure_rebuild": [_h_measure_rebuild], "corvid_fits_ask": [_h_fits_ask], "corvid_fits_apply": [_h_fits_apply]})
