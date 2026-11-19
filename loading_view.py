"""loading_view.py - how each machine loads and unloads: its rules (kept loaded, run alone, stop after idle by program, wait when memory is short, longest wait, memory kept for the system), and what each running program is doing now under them (memory, idle for, stops after, kept).
Every machine's row is drawn at once from what it last said (Aviary's seen, with how old that is); a row being asked again asks for itself (GET /loading?pid=), so a machine that is slow or away holds up nothing. The rules are changed with the machine's own settings form (its /knobs).
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
C = None
RULES = ("scheduler.keep", "scheduler.alone", "scheduler.idle_stop_s", "scheduler.wait_for_memory", "scheduler.max_hold_s", "resources.reserve_gb")   # the node's knobs that make up its loading strategy

def init(c):
    global C
    C = c

def _mins(s) -> str: return "-" if s in (None, "") else f"{s / 60:.0f} min" if s >= 120 else f"{s:.0f} s"

def _program(sv: dict) -> str:
    """One running program in words: what it holds, how long it has had nothing to do, and when or whether it stops by itself."""
    lease, idle, stop = sv.get("lease") or {}, sv.get("idle_s"), sv.get("stops_after_idle_s")
    held = f"""{lease.get("ram_gb", sv.get("rss_gb") or 0):.1f} GB{" measured" if lease.get("measured") else ""}""" if lease or sv.get("rss_gb") else "-"
    when = "kept loaded: stops only by hand" if sv.get("kept") else ("busy" if sv.get("active") else f"""idle {_mins(idle)}""") + (f"""; stops after {_mins(stop)} idle""" if stop else "; never stops for idleness") + "; makes way when other work needs the memory"
    model = sv.get("model") or ""
    return f"""<tr><td class="mono">{C._esc(sv["name"])}</td><td class="mono cv-dim">{C._esc(model)}</td><td>{held}</td><td>{C._esc(when)}</td></tr>"""

async def row(p: dict) -> str:
    """A machine's loading rules and its running programs, as it answers now."""
    a, b = await C.MACHINES._heard(p, "status", "/control/status"), await C.MACHINES._heard(p, "knobs", "/knobs")
    poll = f"""hx-get="{C._P}/loading?pid={C.quote(p["id"])}" hx-trigger="every 2s" hx-swap="outerHTML" """ if a["asking"] or b["asking"] else ""
    if a["value"] is None or b["value"] is None:
        e = a["error"] or b["error"]
        word = ("chip", "being asked ...") if not e else ("chip cv-dim", "answers, without loading rules (an older Magpie, or not Magpie)") if "answered 404" in e else ("chip cv-bad", "not answering")
        return f"""<div class="list-row" {poll}><b>{C._esc(p.get("name") or p["id"])}</b> <span class="{word[0]}" title="{C._esc(e)}">{word[1]}</span> <span class="cv-dim" style="overflow-wrap:anywhere">{C._esc(e)}</span></div>"""
    st, knobs = a["value"], {k["key"]: k for k in b["value"]["knobs"]}
    said = lambda k: C._esc(C._shown(knobs[k]["current"] if knobs.get(k, {}).get("value") is None else knobs[k]["value"])) if k in knobs else "-"
    rules = "".join(f"""<tr><td>{C._esc(knobs[k].get("label") or k)}</td><td class="mono">{said(k) or "-"}</td><td class="cv-dim">{"set" if knobs[k].get("value") is not None else "the node's own"}</td></tr>""" for k in RULES if k in knobs)
    progs = [s for s in st.get("services") or [] if s.get("pid")]
    mem = st.get("memory") or {}
    return f"""<details class="cv-machine" open {poll}><summary><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip {"cv-ok" if not a["error"] else "cv-dim"}">{"answering" if not a["error"] else "not reached now"}</span> <span class="cv-dim">{C.MACHINES._as_of(a)}</span> <span class="cv-dim">{len(progs)} program(s) up | {mem.get("ram_avail_gb", "?")} of {mem.get("ram_total_gb", "?")} GB free</span></summary>
               <table class="cv-tbl"><tr><th>running</th><th>model</th><th>holds</th><th>now, and when it stops</th></tr>{"".join(_program(s) for s in progs) or '<tr><td colspan="4" class="cv-dim">nothing running</td></tr>'}</table>
               <table class="cv-tbl"><tr><th>rule</th><th>now</th><th></th></tr>{rules or '<tr><td class="cv-dim">this machine names no loading rules (older Magpie)</td></tr>'}</table>
               <div class="row">{C._btn("Change these rules", "knobs_form", pid=p["id"], title="The machine's own settings form: kept loaded, run alone, stop after idle by program, and the rest")}</div><div id="cv-knobs-{p["id"]}"></div></details>"""

async def p_loading(c) -> str:
    """Every machine's loading rules and running programs, each drawn when it answers."""
    ps = [p for p in C.AV.lib.list("provider") if not p.get("speaks")]
    places = "".join([await row(p) for p in ps])   # each from what it last said: drawn at once, asking for itself while it is asked again
    return f"""{C._dim("How each machine loads and frees memory. A program starts when work needs it; it stops when it has been idle for its time, or earlier when other work needs the memory - unless it is kept loaded. What a run will do (load, make way, wait) is in Settings > Needs, under each need.")}{places or C._dim("No machines yet.")}"""
