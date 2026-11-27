"""catalog_view.py - the model finder and catalog (D-13 in claude/data/decisions.md, I-79 in claude/data/issues.md): the old AI Calc finder's search, filters and weighted ranking, against one of these machines' measured memory and speed, plus a general score fitted from public benchmark results, and Get to download a file onto a machine.
Flow of a search (shown as it goes): the Hub lists for the task's queries and tags are read; models are kept or left out by name, tags, size and quant before any model page is read; the rest are ranked with estimated file sizes; the pages of the best few are read (exact sizes, licence, base model, the benchmarks their cards state); everything is ranked again.
Outside contact happens only through a machine whose web module is active (web_fetch: the node reads, D-02), only when an admin asks; every text read is kept as a dated snapshot (Aviary catalog.py), so the benchmark scale works offline from the last reading. The finder's tables (quants, task presets, curated benchmarks, weights) are data: Aviary catalog_config.json, replaced key by key by <Aviary data>/catalog/config.json.
Fit and speed are estimates (catalog.fit and kv_gb over the machine's measured memory and rate); the machine's own plan is exact once the file is there. Downloads are made through the machine's downloads module, the same as Settings > Machines and Settings > Models.
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import json, time, asyncio
from pathlib import PurePosixPath

C = None
STATE: dict = {}      # user -> {"f": the form as sent, "busy", "log": [steps], "error", "models": {id: facts}, "rows": [ranked], "t"}
SCALE: dict = {}      # {"scale": {model: score}, "rows": n, "t": when read, "file": snapshot} - filled from the last snapshot on first use
_TASKS: set = set()   # the event loop holds tasks weakly
_FIELDS = ("preset", "words", "extra", "min_params", "max_params", "ctx", "machine", "min_tps", "target_tps", "curve", "min_quant", "must", "any", "exclude", "details", "cap")

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_cat_search": [_h_search], "corvid_cat_scale": [_h_scale], "corvid_cat_get": [_h_get]})

def _spawn(coro):
    t = asyncio.create_task(coro)
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)

def _blank(user: str) -> dict: return STATE.setdefault(user, {"f": {}, "busy": False, "log": [], "error": "", "models": {}, "rows": [], "t": time.time()})

# --- Reading the outside (through a machine) ---

async def _reader():
    """The first machine that reads pages for the portal (its web module active)."""
    return next((o["p"] for o in await C._offers() if any("web_fetch" in a.get("capabilities", []) for a in o["assets"])), None)

async def _read(p: dict, url: str) -> str:
    d = (await C.PROV.run(p, "web_fetch", {"model": "web", "url": url}))["result"] or {}
    if d.get("status") != 200: raise C.PROV.ProviderError(f"""{url} answered {d.get("status")}: {(d.get("text") or d.get("note") or "")[:300]}""")
    return d["text"]

def _need_reader(p):
    if not p: raise C.PROV.ProviderError("no machine reads pages for the portal: activate the web module on one (Settings, Machines, its programs), then try again")
    return p

async def _detail(p: dict, m: dict):
    """A model's page read into its facts: exact files, licence, base model, architecture, the scores its card states."""
    K = C.AV.catalog
    text = await _read(p, K.detail_url(m["id"]))
    K.keep("hf", m["id"].replace("/", "__"), text)
    d = K.parse_detail(text)
    m.update(files=d["files"], license=d["license"], base=d["base"] or m.get("base", ""), arch=d["arch"], ctx_max=d["ctx"], gated=d["gated"], card=K.card_scores(json.loads(text)), read=True, params_b=round(d["params"] / 1e9, 2) if d["params"] else m["params_b"])

async def _finder(user: str):
    s, K = STATE[user], C.AV.catalog
    cfg, f, say = K.config(), s["f"], s["log"].append
    try:
        p = _need_reader(await _reader())
        preset = cfg["TASK_PRESETS"].get(f["preset"], {})
        urls = K.finder_urls(preset, f["words"], f["extra"])
        raw = []
        for i, u in enumerate(urls):
            got = json.loads(await _read(p, u))
            raw += got
            say(f"""list {i + 1} of {len(urls)} read: {len(got)} models""")
        K.keep("hf", f"""finder-{f["preset"] or "words"}-{f["words"]}""", json.dumps(raw))
        kept, counts = K.prefilter(raw, f, cfg)
        for m in kept: m.setdefault("base", K._tagged(m.get("tags", []), "base_model:"))
        names, qwant = K.words_of(f["words"])
        if names: say(f"""name words {", ".join(names)}: {counts["named"][0]} of {counts["named"][1]} found together{"" if counts["named"][0] == counts["named"][1] else " at most - the models with the most of them are kept"}; {counts["name"]} other models left out""")
        if qwant: say(f"""quants asked for: {", ".join(qwant)}""")
        say(f"""{len(kept)} of {len({m.get("id") for m in raw})} models kept; left out: {counts["exclude"]} by excluded words, {counts["words"]} by required words, {counts["params"]} by size, {counts["quant"]} with no quant at or above {f["min_quant"]}""")
        machine = _machine(f["machine"])
        first = K.rank(kept, f, machine, cfg, _scale().get("scale"))
        ids = list(dict.fromkeys(r["id"] for r in first))[:int(f["details"] or 0)]
        say(f"""{len(first)} model and quant pairs fit {machine["name"]}; reading the pages of the best {len(ids)} ...""")
        by = {m["id"]: m for m in kept}
        for i, mid in enumerate(ids):
            await _detail(p, by[mid])
            say(f"""page {i + 1} of {len(ids)} read: {mid}""")
        s["models"], s["rows"] = by, K.rank(kept, f, machine, cfg, _scale().get("scale"))[:int(f["cap"] or 40)]
        say(f"""done at {time.strftime("%H:%M")}: {len(s["rows"])} ranked for {machine["name"]}""")
    except (C.PROV.ProviderError, ValueError, KeyError) as e: s["error"] = f"{type(e).__name__}: {e}" if isinstance(e, KeyError) else str(e)
    s["busy"] = False

async def _scale_read(user: str):
    s, K = STATE[user], C.AV.catalog
    try:
        p = _need_reader(await _reader())
        s["log"].append("reading Epoch AI's benchmark results ...")
        text = await _read(p, "https://epoch.ai/data/eci_benchmarks.csv")
        f = K.keep("eci", "eci_benchmarks.csv", text)
        rows = K.bench_rows(text)
        s["log"].append(f"fitting the scale from {len(rows)} results ...")
        SCALE.update(scale=await asyncio.to_thread(K.fit_scale, rows), rows=len(rows), t=time.time(), file=f.name)
        s["log"].append(f"""scale fitted: {len(SCALE["scale"])} models""")
    except (C.PROV.ProviderError, ValueError) as e: s["error"] = str(e)
    s["busy"] = False

def _scale() -> dict:
    """The fitted scale, fitted again from the last snapshot after a restart (no outside contact)."""
    if not SCALE:
        text, f = C.AV.catalog.latest("eci")
        rows = C.AV.catalog.bench_rows(text) if text else []
        SCALE.update(scale=C.AV.catalog.fit_scale(rows) if rows else {}, rows=len(rows), t=f.stat().st_mtime if f else 0, file=f.name if f else "")
    return SCALE

# --- Machines ---

def _machines() -> list:
    """[(group, its provider, total memory GB, effective rate bytes/s)] for every machine in the resource store that has a Magpie provider (downloads go to nodes)."""
    R, figs = C.AV.resources, C.AV.resources.figures(prefix=True)
    return [(g, C.AV.lib.get("provider", g["provider"]), figs.get(f"""{g["id"]}/ram""", {}).get("total_gb", {}).get("best") or 0, R.rate(g["id"]).get("bytes_s") or 0) for g in R.groups() if g.get("provider") and C.AV.lib.has("provider", g["provider"]) and not C.AV.lib.get("provider", g["provider"]).get("speaks")]

def _machine(gid: str) -> dict:
    """The machine a search ranks for: {name, ram_gb, rate}. Its memory must be known (Asio, Resources measures it); its speed may not be (speed is then not scored)."""
    g, _, ram, rate = next((x for x in _machines() if x[0]["id"] == gid), (None, None, 0, 0))
    if not g: raise ValueError("choose the machine to rank for")
    if not ram: raise ValueError(f"""{g["name"]}'s memory is not known yet: measure it in Asio, Resources""")
    return {"name": g["name"], "ram_gb": ram, "rate": rate}

# --- Intents ---

async def _h_search(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin reads the outside from here.", True), "cv-msg")
    s = _blank(C._user(request))
    if s["busy"]: return imr.oob(C._note("A reading is under way; it shows below as it goes.", True), "cv-msg")
    cfg = C.AV.catalog.config()
    weights = {**cfg["DEFAULT_WEIGHTS"], **cfg["TASK_PRESETS"].get(payload.get("preset", ""), {}).get("weights", {}), **{d: float(payload[f"w_{d}"]) for d in cfg["SCORE_DIMS"] if str(payload.get(f"w_{d}") or "").strip()}}
    s.update(f={**{k: str(payload.get(k) or "").strip() for k in _FIELDS}, "weights": weights, "w_given": {d: payload[f"w_{d}"] for d in cfg["SCORE_DIMS"] if str(payload.get(f"w_{d}") or "").strip()}}, busy=True, log=[], error="", t=time.time())
    _spawn(_finder(C._user(request)))
    return imr.oob(body(C._user(request), payload["face"]), "cv-cat", swap="outerHTML")

async def _h_scale(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin reads the outside from here.", True), "cv-msg")
    s = _blank(C._user(request))
    if s["busy"]: return imr.oob(C._note("A reading is under way; it shows below as it goes.", True), "cv-msg")
    s.update(busy=True, error="", log=[])
    _spawn(_scale_read(C._user(request)))
    return imr.oob(body(C._user(request), payload["face"]), "cv-cat", swap="outerHTML")

async def _h_get(request, payload, imr):
    """Downloads one file (every part of a split one) of a ranked model and quant onto the chosen machine, into its language-model place, folder gguf_local. A model whose page was not read yet is read first. A name that exists there is refused by the machine."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin downloads onto machines.", True), "cv-msg")
    m = (STATE.get(C._user(request)) or {}).get("models", {}).get(payload["mid"])
    if not (m and payload.get("pid")): return imr.oob(C._note("Choose a machine for it (and search again if the list changed).", True), "cv-msg")
    p, K, quant = C.AV.lib.get("provider", payload["pid"]), C.AV.catalog, payload.get("q") or payload["quant"]   # q: the quant picked on the row (named apart: a button's own values win over its form's fields)
    try:
        if not m.get("read"): await _detail(_need_reader(await _reader()), m)
        f = next((x for x in m["files"] if not x["projector"] and (x["quant"] or "").replace("UD-", "") == quant), None)
        if not f: return imr.oob(C._note(f"""{m["id"]} has no {quant} file on its page now: its files are {", ".join(x["quant"] for x in m["files"] if not x["projector"])}.""", True), "cv-msg")
        for path in f["paths"]: await C.PROV.manage(p, "PUT", "download", PurePosixPath(path).name, {"url": K.file_url(m["id"], path), "location": "text_models", "folder": "gguf_local"})
    except C.PROV.ProviderError as e: return imr.oob(C._note(f"""{e}{" - this repository asks for an access token: download it from Settings, Models, where a token can be given" if m.get("gated") else ""}""", True), "cv-msg")
    return imr.oob(C._note(f"""Downloading {f["name"]} ({f["parts"]} part{"s" if f["parts"] > 1 else ""}, {f["bytes"] / 1e9:.1f} GB) onto {p.get("name") or p["id"]}: progress under Settings, Models."""), "cv-msg")

# --- Drawing ---

def _fit_cell(f: dict, ram: float, rate: float) -> str:
    x = C.AV.catalog.fit(f["bytes"], ram, rate)
    if not ram: return """<td class="cv-dim" title="this machine's memory is not known yet: Asio, Resources">?</td>"""
    return f"""<td class="{"cv-ok" if x["fits"] else "cv-bad"}" title="needs about {x["need_gb"]} GB with a working context, of {ram:.0f} GB (4 GB kept for the system)">{f"~{x['tps']} t/s" if x["fits"] and x["tps"] else "fits" if x["fits"] else "too big"}</td>"""

def _files(m: dict, machines: list) -> str:
    """A read model's files, each against every machine."""
    K = C.AV.catalog
    head = "".join(f"""<th>{C._esc(g["name"])}</th>""" for g, *_ in machines)
    rows = "".join(f"""<tr><td class="mono" title="{C._esc(f["name"])}">{C._esc(f["quant"])}{" (vision)" if f["projector"] else ""}</td><td>{f["bytes"] / 1e9:.1f}</td><td>{K.bits_per_weight(f, int(m["params_b"] * 1e9)) if not f["projector"] else ""}</td>{"".join(_fit_cell(f, ram, rate) for _, _, ram, rate in machines)}</tr>""" for f in m["files"])
    return f"""<details class="sec"><summary><b>{C._esc(m["id"])}</b> <span class="cv-dim">{C._esc(m.get("arch") or "")} | {m["params_b"]} B | {C._esc(m.get("license") or "licence ?")} | context {m.get("ctx_max") or "?"} | base {C._esc(m.get("base") or "?")}{" | gated" if m.get("gated") else ""}</span> <a href="{C._esc(K.page_url(m["id"]))}" target="_blank" rel="noopener noreferrer">its page</a></summary><div class="scroll-pane"><table class="cv-tbl"><tr><th>quant</th><th>GB</th><th>bits/weight</th>{head}</tr>{rows}</table></div></details>"""

def _quants(m: dict) -> list:
    """Every quant a model offers: its read page's files (all of them, below the lowest quality too), else the file names the search listed."""
    return list(dict.fromkeys((x["quant"] or "").replace("UD-", "") for x in m["files"] if not x["projector"])) if m.get("read") else m.get("quants", [])

def _row(i: int, r: dict, m: dict, face_id: str, opts: str, labels: dict) -> str:
    fid = f"""cv-catg-{i}"""
    parts = "; ".join(f"""{labels.get(k, k)} {v:.2f}""" for k, v in r["sub"].items())
    bench = C.AV.catalog._wavg(r["benches"], C.AV.catalog._AVG_W)
    quants = "".join(f"""<option value="{C._esc(q)}"{" selected" if q == r["quant"] else ""}>{C._esc(q)}</option>""" for q in _quants(m) or [r["quant"]])
    get = f"""<form id="{fid}" class="row" onsubmit="return false"><select name="q" class="module-select" title="the quant to download (this row ranks {C._esc(r["quant"])})">{quants}</select><select name="pid" class="module-select"><option value="">machine ...</option>{opts}</select>{C._btn("Get", "cat_get", "ui-btn cv-small", face=face_id, mid=r["id"], quant=r["quant"], include="#" + fid)}</form>"""
    return f"""<tr><td>{i + 1}</td><td class="mono" style="overflow-wrap:anywhere" title="{C._esc(r["id"])}">{C._esc(r["id"].split("/")[-1])} <span class="cv-dim">{C._esc(r["id"].split("/")[0])}</span>{" <span class='chip'>MTP</span>" if r["mtp"] else ""}</td><td class="mono">{C._esc(r["quant"])}</td><td>{"" if r["exact"] else "~"}{r["gb"]}</td><td>{r["params_b"]}</td><td>{r["tps"] if r["tps"] is not None else "?"}</td><td>{r["need_gb"]}</td><td title="{C._esc(parts)}"><b>{r["total"]:.3f}</b></td><td>{f"{r['general']:+.2f}" if r["general"] is not None else "-"}</td><td>{f"{bench:.0f}" if bench else "-"}</td><td class="cv-dim">{C._esc(m.get("license") or "")}</td><td>{get}</td></tr>"""

def _form(f: dict, face_id: str, cfg: dict, machines: list) -> str:
    v = lambda k, d="": C._esc(f.get(k) or d)
    sel = lambda k, items, d="": "".join(f"""<option value="{C._esc(a)}"{" selected" if (f.get(k) or d) == a else ""}>{C._esc(b)}</option>""" for a, b in items)
    num = lambda k, label, d, title, step="any": f"""<label class="cv-dim" title="{C._esc(title)}">{label} <input name="{k}" type="number" step="{step}" min="0" class="module-select" style="width:5.5em" value="{v(k, d)}"></label>"""
    txt = lambda k, label, ph, title: f"""<label class="cv-dim grow" title="{C._esc(title)}">{label} <input name="{k}" class="module-select" style="width:100%" value="{v(k)}" placeholder="{C._esc(ph)}"></label>"""
    presets = [(k, p.get("label", k)) for k, p in cfg["TASK_PRESETS"].items()]
    mach = [(g["id"], f"""{g["name"]} ({ram:.0f} GB{", speed measured" if rate else ", speed not measured"})""" if ram else f"""{g["name"]} (memory not known)""") for g, _, ram, rate in machines]
    quants = [(q, f"""{q} (quality {x["quality"]})""") for q, x in sorted(cfg["QUANTS"].items(), key=lambda kv: kv[1]["bpp"])]
    weights = "".join(f"""<label class="cv-dim">{C._esc(cfg["SCORE_DIM_LABELS"].get(d, d))} <input name="w_{d}" type="number" min="0" max="10" step="0.5" class="module-select" style="width:4.5em" value="{C._esc((f.get("w_given") or {}).get(d, ""))}" placeholder="{cfg["DEFAULT_WEIGHTS"].get(d, 1)}"></label>""" for d in cfg["SCORE_DIMS"])
    return f"""<form id="cv-cat-f" class="cv-form" onsubmit="return false">
               <div class="row" style="flex-wrap:wrap"><label class="cv-dim">Task <select name="preset" class="module-select">{sel("preset", presets, next(iter(cfg["TASK_PRESETS"])))}</select></label>{txt("words", "Words", "e.g. qwen3.5 4b q8, or a name whole: Qwen3.5-4B-Q8_0", "any order, any case; a name typed whole is split at - / : and searched whole, then shorter; quant words (q8, Q4_K_M, bf16) choose the quants shown")}<label class="cv-dim">Rank for <select name="machine" class="module-select">{sel("machine", mach)}</select></label></div>
               <div class="row" style="flex-wrap:wrap">{num("min_params", "Params from (B)", "1", "smallest size kept, billions of parameters")}{num("max_params", "to", "35", "largest size kept")}{num("ctx", "Context (tokens)", "16384", "the context the model must fit with: adds its cache to the memory needed")}{num("min_tps", "At least t/s", "1", "on the machine ranked for; not applied while its speed is not measured")}{num("target_tps", "Target t/s", "8", "the speed the speed score is judged against")}<label class="cv-dim" title="{C._esc("; ".join(f"{k}: {x}" for k, x in C.AV.catalog.CURVES.items()))}">Past the target <select name="curve" class="module-select">{sel("curve", [(k, k) for k in C.AV.catalog.CURVES], "cap")}</select></label><label class="cv-dim" title="quants below this quality are left out before ranking">Lowest quant <select name="min_quant" class="module-select">{sel("min_quant", quants, "Q3_K_M")}</select></label></div>
               <details class="sec"><summary class="cv-dim">Words to require or exclude, how much is read, weights</summary>
               <div class="row" style="flex-wrap:wrap">{txt("must", "Must contain all", "instruct, chat", "comma-separated, over the repository name and its tags")}{txt("any", "Must contain any", "creative, roleplay", "comma-separated")}{txt("exclude", "Exclude", "vision, embed, base", "comma-separated")}{txt("extra", "Extra Hub query", "", "one more search on the Hub")}</div>
               <div class="row" style="flex-wrap:wrap">{num("details", "Model pages read", "12", "the best this many models have their pages read (exact sizes, licence, card benchmarks): one outside read each", "1")}{num("cap", "Rows shown", "40", "results cap", "1")}</div>
               <div class="cv-dim">Score weights (0 to 10; empty: the task's own)</div><div class="row" style="flex-wrap:wrap">{weights}</div></details>
               <div class="row"><span class="grow"></span>{C._btn("Search", "cat_search", face=face_id, include="#cv-cat-f")}</div></form>"""

def body(user: str, face_id: str) -> str:
    s, sc, cfg, machines = STATE.get(user) or {}, _scale(), C.AV.catalog.config(), _machines()
    poll = f"""hx-get="{C._P}/catalog?face={C.quote(face_id)}" hx-trigger="every 2s" hx-swap="outerHTML" """ if s.get("busy") else ""
    scale = f"""General score: {len(sc["scale"])} models, fitted here from {sc["rows"]} benchmark results (Epoch AI, CC-BY; read {time.strftime("%Y-%m-%d", time.localtime(sc["t"]))}); standard deviations from the mean model, not Epoch's published values.""" if sc.get("scale") else "No general score yet: read Epoch AI's public benchmark results (CC-BY) once; the scale is fitted here and kept."
    log = f"""<details class="sec"{" open" if s.get("busy") else ""}><summary class="cv-dim">{"Working: " if s.get("busy") else "Last search: "}{C._esc((s.get("log") or ["-"])[-1])}</summary><div class="quote-block mono cv-log pre-wrap">{C._esc(chr(10).join(s.get("log") or []))}</div></details>""" if s.get("log") else ""
    opts = "".join(f"""<option value="{C._esc(p["id"])}">{C._esc(g["name"])}</option>""" for g, p, _, _ in machines)
    head = """<tr><th>#</th><th>model</th><th>quant</th><th title="~ estimated from parameters until the model's page is read">GB</th><th>B params</th><th title="estimated on the machine ranked for">t/s</th><th title="file and context cache">needs GB</th><th title="weighted 0-1; hover a score for its parts">score</th><th title="general score: standard deviations from the mean model in Epoch's data">general</th><th title="average of the benchmarks the card or the curated table gives">bench</th><th>licence</th><th>download</th></tr>"""
    rows = "".join(_row(i, r, s["models"].get(r["id"], {}), face_id, opts, cfg["SCORE_DIM_LABELS"]) for i, r in enumerate(s.get("rows") or []))
    files = "".join(_files(m, machines) for m in (s.get("models") or {}).values() if m.get("read"))
    table = f"""<div class="scroll-pane"><table class="cv-tbl">{head}{rows}</table></div>{f'<div class="sec">Files of the models read, on every machine</div>{files}' if files else ""}""" if rows else ""
    about = C._dim("Pages are read by a machine with its web module active, only when you ask; what was read is kept (Aviary data, catalog/). Sizes marked ~ are estimated until a model's page is read; fit and speed are estimates from the machine's measured memory and rate (Asio, Resources) - a mixture-of-experts file reads less per token than its size, so its speed shows low.")
    return f"""<div id="cv-cat" {poll}>{_form(s.get("f") or {}, face_id, cfg, machines)}<div class="row cv-dim"><span class="grow">{scale}</span>{C._btn("Read the benchmark results" if not sc.get("scale") else "Read them again", "cat_scale", "ui-btn cv-small", face=face_id)}</div>{C._note(s["error"], True) if s.get("error") else ""}{log}{table}{about if not rows else ""}</div>"""

async def p_catalog(c) -> str: return body(C._user(c.request), c.face["id"])
