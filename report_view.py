"""report_view.py - one text that says how this set-up stands, to read or to hand on (Asio > Report).
It gathers, without changing anything: the portal's own code (a fingerprint per part), each machine as it answers now (its Magpie code, programs, state, speed figures, power), what Asio has measured, the pipelines and faces this portal holds as its own, and the latest runs that failed with their errors in full.
Asking every machine takes a moment, so the report is made in the background and the page shows it when ready; nothing waits on a machine that does not answer (each is asked with a short limit and its silence is written down)."""
import sys, json, time, asyncio, hashlib
from pathlib import Path

C = None   # corvid.py's live view, given to init
REPORT: dict = {}   # the last report: {"running", "text", "t"}
_TASKS = set()   # its task: the event loop holds tasks only weakly
FAILED_SHOWN = 8   # how many of the latest failed runs are written out

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_report_make": [_h_make]})

def _fp(folder: Path) -> str:
    """A short fingerprint of a code folder's .py and .json files, to tell two copies apart."""
    h = hashlib.sha256()
    for f in sorted(folder.rglob("*")):
        if f.suffix in (".py", ".json") and "__pycache__" not in f.parts and "/data/" not in str(f): h.update(str(f.relative_to(folder)).encode() + f.read_bytes())
    return h.hexdigest()[:12]

async def _machine(p: dict) -> list:
    """One machine's lines: answered now or not, its code, programs, figures and power."""
    name = p.get("name") or p["id"]
    if p.get("speaks"):
        try: return [f"## {name} (speaks {p['speaks']})", f"models: {', '.join(m['name'] for m in await C.PROV.assets(p, timeout=8.0))}"]
        except C.PROV.ProviderError as e: return [f"## {name} (speaks {p['speaks']})", f"not answering: {e}"]
    try: node, code = await asyncio.gather(C.PROV.machine(p, "GET", "/node", timeout=8.0), C.PROV.machine(p, "GET", "/node/code", timeout=8.0))
    except C.PROV.ProviderError as e: return [f"## {name}", f"not answering: {e}"]
    hw, now, sp = node.get("hardware") or {}, node.get("now") or {}, node.get("speed") or {}
    progs = [f"""  {s.get("name")}: {s.get("status")}{" " + s["detail"] if s.get("detail") else ""}{" model " + s["model"] if s.get("model") else ""}{" rss " + str(s.get("rss_gb")) + " GB" if s.get("rss_gb") else ""}""" for s in node.get("services", [])]
    return [f"## {name}", f"""magpie code {code.get("fingerprint")}, up {node.get("uptime_s")} s""", f"""hardware: {json.dumps({k: hw.get(k) for k in ("cpu", "threads", "ram_gb", "gpu", "arch") if k in hw})}""", f"now: {json.dumps(now)}", f"speed test: {json.dumps({k: v for k, v in sp.items() if k not in ('sig',)})}", "programs:", *(progs or ["  none up"])]

def _figures() -> list:
    """What Asio has measured, one line per thing measured."""
    out = []
    for subject, figs in sorted(C.AV.resources.figures().items()):
        out.append(f"""  {subject}: {", ".join(f"{k} {round(v['best'], 2) if isinstance(v.get('best'), (int, float)) else v.get('best')} {v.get('unit') or ''}{' (' + str(v['n']) + ')' if v.get('n') else ''}" for k, v in sorted(figs.items()))}""")
    return out or ["  nothing measured yet"]

def _failed() -> list:
    """The latest runs that failed or were held, with their errors in full."""
    runs = sorted((r for r in C.AV.director.runs.values() if r.meta["state"] in ("failed", "held", "unplaced")), key=lambda r: r.meta.get("created", 0), reverse=True)[:FAILED_SHOWN]
    return [f"""  {r.id} {r.plan.get("id", "")} {r.meta["state"]}: {r.meta.get("error", "")}""" for r in runs] or ["  none"]

async def make() -> str:
    """The whole report as text (markdown headings, so it reads as it is)."""
    here = Path(__file__).parent
    own = {k: sorted(o["id"] for o in C.AV.lib.list(k) if C.AV.lib.origin(k, o["id"]) == "mine") for k in ("pipeline", "face", "translator")}   # this portal's own copies: they shadow the shipped ones of the same id
    machines = await asyncio.gather(*(_machine(p) for p in C.AV.lib.list("provider")))
    lines = ["# Portal report", f"""made {time.strftime("%Y-%m-%d %H:%M:%S")}""", "", "## This portal", f"corvid {_fp(here)}, aviary {_fp(Path(sys.modules[type(C.AV).__module__].__file__).parent)}", f"own library objects: {json.dumps(own)}", ""]
    for m in machines: lines += [*m, ""]
    lines += ["## Measured (Asio)", *_figures(), "", "## Latest failed or held runs", *_failed()]
    return "\n".join(lines)

async def _h_make(request, payload, imr):
    """Starts a report in the background; the panel shows it when it is ready."""
    if REPORT.get("running"): return imr.oob(C._note("A report is being made already."), "cv-msg")
    REPORT.update(running=True, text="", t=time.time())
    async def go():
        try: REPORT["text"] = await make()
        except Exception as e: REPORT["text"] = f"The report could not be made: {type(e).__name__}: {e}"   # any failure of gathering is the report's own content here, shown in full
        REPORT["running"] = False
    _TASKS.add(task := asyncio.create_task(go()))
    task.add_done_callback(_TASKS.discard)
    return await C._refresh(request, imr, payload["face"], C._note("Making the report: it shows below when every machine has answered or been passed over."))

def report_html() -> str:
    """The report area (GET /report): asks again every 2 s while the report is made."""
    if REPORT.get("running"): return f"""<div id="cv-report" hx-get="{C._P}/report" hx-trigger="every 2s" hx-swap="outerHTML">{C._dim("Asking the machines...")}</div>"""
    if not REPORT.get("text"): return """<div id="cv-report"></div>"""
    return f"""<div id="cv-report"><div class="row">{C._dim(f"made {time.strftime('%H:%M:%S', time.localtime(REPORT['t']))}")}<span class="grow"></span><button class="ui-btn cv-small" type="button" onpointerdown="navigator.clipboard.writeText(document.getElementById('cv-report-text').value)">Copy</button></div><textarea id="cv-report-text" class="mono" readonly style="width:100%;height:60vh;font-size:.75rem">{C._esc(REPORT["text"])}</textarea></div>"""

async def p_report(c) -> str:
    """Asio > Report: what the report holds, the button, and the last report."""
    return f"""{C._dim("One text to read or to hand on: this portal's code, each machine as it answers now (its code, programs, state, speed, power), what has been measured, and the latest failed runs with their errors. Nothing is changed by making it. Before sharing it outside this set-up: it holds machine names and addresses, model names and run errors.")}<div class="row">{C._btn("Make a report", "report_make", face=c.face["id"])}</div>{report_html()}"""
