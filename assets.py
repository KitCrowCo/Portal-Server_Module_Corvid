"""assets.py - Corvid's panels over what providers hold, beside corvid.py: assets (the things a provider lets a manager make there, by kind - the provider says what one is made of), records (what such an asset holds, through capabilities the panel's own data names) and graph (an asset's graph, drawn by the portal's graph_view.js).
Nothing here knows what any kind is: a knowledge group, a model source and whatever comes later are the same panels fed by different face data.
C is a live view of corvid.py's globals, set when Corvid starts."""
import re, json
from urllib.parse import quote

C = None

# --- Panels: assets (what a provider lets a manager make there, by kind: the provider says what one is made of) and records (what such an asset holds, through capabilities the panel names) ---

def _asset_fields(kind: dict, assets: list, new: bool, elsewhere: list = ()) -> list:
    """The kind's own fields as form fields; one that picks a model lists what that provider offers for the capability named, then what every other machine offers for it (elsewhere: [(provider, its assets)]) - picked as "@<provider id>|<model>", which a save turns into a model source on the provider the thing lives on (_from_elsewhere)."""
    def field(f):
        cap = f.get("pick", "").partition(":")[2]
        here = [(a["name"], a["name"]) for a in assets if cap in a.get("capabilities", [])]
        there = [(f"""@{q["id"]}|{a["name"]}""", f"""{a["name"]} - done on {q.get("name") or q["id"]}""") for q, theirs in elsewhere for a in theirs if cap in a.get("capabilities", []) and "/" not in a["name"]]   # a machine's own models: one it only passes on from a third is picked where it runs
        sf = C.BI.SettingField(f["name"], f.get("label") or f["name"], "select" if cap else C._FIELD.get(f.get("type"), "text"), default=f.get("default"), options=[("", "(choose)")] + here + there if cap else None, hint=(f"""Not used on this machine yet: {f["unavailable"]}. """ if f.get("unavailable") else "") + f.get("hint", "") + (" A model on another machine: the work is sent there, and this machine only keeps what comes of it." if cap and there else ""))   # unavailable: the machine says it cannot act on this choice yet, and why; the choice is still kept
        sf.advanced = bool(f.get("advanced"))   # a kind's deeper settings ("advanced": true) are drawn folded under the main ones
        return sf
    return ([C.BI.SettingField("new_name", "Name", "text", hint="Short, without spaces; it is how it is named everywhere from here on.")] if new else []) + [field(f) for f in kind["fields"]]   # the new one's name is "new_name": the button's own values carry the name of the one being changed

def _as_picked(v):
    """A stored model name as the form offers it: "<source>/<model>", where the source is a route this portal made to one of its machines, is that machine's choice "@<provider id>|<model>"; anything else as it is."""
    src, _, model = str(v or "").partition("/")
    pid = next((q["id"] for q in C.AV.lib.list("provider") if re.sub(r"[^A-Za-z0-9_-]", "_", q["id"])[:40] == src), "") if model else ""
    return f"@{pid}|{model}" if pid else v

async def _from_elsewhere(p: dict, kinds: dict, body: dict) -> dict:
    """body with every model picked on another machine ("@<provider id>|<model>") made usable where the thing lives: that machine is made a model source on p (named after it; its address and the key this portal holds for it), and the pick becomes "<source>/<model>", which p routes there. So where work is done is chosen here, among everything this portal knows, and no machine is set up by hand for it."""
    out = dict(body)
    for k, v in body.items():
        if not (isinstance(v, str) and v.startswith("@") and "|" in v): continue
        if "source" not in kinds: raise C.PROV.ProviderError(f"""{p.get("name") or p["id"]} cannot send work to another machine yet: its "remote" program (model sources) is not active there - Settings, Machines.""")
        q, model = C.AV.lib.get("provider", v[1:].split("|", 1)[0]), v.split("|", 1)[1]
        src = re.sub(r"[^A-Za-z0-9_-]", "_", q["id"])[:40]
        await C.PROV.manage(p, "PUT", "source", src, {"url": q["url"], "key": q.get("key", ""), "enabled": True})
        out[k] = f"{src}/{model}"
    return out

async def p_assets(c) -> str:
    kind, out = c.spec["kind"], ""
    for o in await C._offers():
        p, pname = o["p"], o["p"].get("name") or o["p"]["id"]
        if o["error"]:
            out += C._note(o["error"], True)
            continue
        if p.get("speaks"):
            out += C._dim(f"""{C._esc(pname)} speaks {C._esc(p["speaks"])}: nothing can be made there from here.""")
            continue
        try: kinds = (await C.PROV.manage(p, "GET"))["kinds"]
        except C.PROV.ProviderError:
            out += C._dim(f"{C._esc(pname)}: this provider's software has no way yet to make things on it from here (it needs the update that adds /assets).")
            continue
        if kind not in kinds:
            out += C._dim(f"{C._esc(pname)}: nothing active there manages this kind. Install or activate its module on that machine: Settings, Machines.")
            continue
        k = kinds[kind]
        def row(a):
            said = " | ".join(f.get("label", f["name"]) + ": " + C._shown(a.get(f["name"])) for f in k["fields"] if a.get(f["name"]) not in (None, ""))
            return f"""<div class="list-row row"><b>{C._esc(a["name"])}</b><span class="chip">{C._esc(a.get("status", ""))}</span><span class="cv-dim grow">{C._esc(said)}</span>{C._btn("Change", "asset_form", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"])}{C._btn("Remove", "asset_del", "ui-btn cv-danger", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"], confirm="Remove it from that machine?" + (" What it holds stays on disk there." if k.get("holds") else ""))}{C._btn("Remove with what it holds", "asset_del", "ui-btn cv-danger", face=c.face["id"], pid=p["id"], kind=kind, name=a["name"], data="1", confirm="Remove it AND delete everything it holds on that machine? This cannot be undone.") if k.get("holds") else ""}</div>"""
        rows = "".join(row(a) for a in (await C.PROV.manage(p, "GET", kind))["assets"] if C._admin(c.request) or C._usable(c.request, p["id"], a["name"]))   # an admin administers every machine's things; anyone else sees what no pool keeps from them
        out += f"""<div class="row"><b>{C._esc(k.get("label", kind))}s on {C._esc(pname)}</b><span class="grow"></span>{C._btn("New", "asset_form", face=c.face["id"], pid=p["id"], kind=kind)}</div>{C._dim(C._esc(k.get("about", "")))}{rows or C._dim("none yet - New makes the first")}"""
    return f"""{out or C._dim("no provider yet - add one in Settings")}<div id="cv-asset-form"></div>"""

async def _h_asset_form(request, payload, imr):
    if payload.get("close"): return imr.oob("", "cv-asset-form")
    p, kind, name = C.AV.lib.get("provider", payload["pid"]), payload["kind"], payload.get("name", "")
    k, assets = (await C.PROV.manage(p, "GET"))["kinds"][kind], next(o["assets"] for o in await C._offers() if o["p"]["id"] == p["id"])
    cur = next((a for a in (await C.PROV.manage(p, "GET", kind))["assets"] if a["name"] == name), {})
    head = f"""Change {C._esc(name)}""" if name else f"""New {C._esc(k.get("label", kind)).lower()} on {C._esc(p.get("name") or p["id"])}"""
    elsewhere = [(o["p"], o["assets"]) for o in await C._offers() if o["p"]["id"] != p["id"]]
    fields, vals = _asset_fields(k, assets, not name, elsewhere), {f["name"]: _as_picked(cur.get(f["name"], f.get("default"))) for f in k["fields"]}
    for f in fields:   # a stored value no choice matches (a model since removed, a source made by hand) stays chosen as it is, so saving does not drop it
        if f.type == "select" and vals.get(f.name) and vals[f.name] not in [o[0] for o in f.options]: f.options.append((vals[f.name], f"""{vals[f.name]} (as set; not offered now)"""))
    deeper = f"""<details><summary class="cv-dim">Program settings</summary>{C._dim("Left empty: the program's own default.")}{C._group([f for f in fields if f.advanced]).render(vals)}</details>""" if any(f.advanced for f in fields) else ""
    rename = f"""<details><summary class="cv-dim">Rename</summary><form class="row" id="cv-asset-rn" onsubmit="return false"><input name="to" class="module-select grow" value="{C._esc(name)}" title="Letters, digits, - and _. What it holds moves with it; its program stops and starts again under the new name.">{C._btn("Rename", "asset_rename", "ui-btn cv-small", face=payload["face"], pid=p["id"], kind=kind, name=name, include="#cv-asset-rn", confirm=f"Rename {name}? Its program stops while what it holds is moved.")}</form></details>""" if name and k.get("renames") else ""
    return imr.oob(f"""{rename}<form class="cv-form" id="cv-asset-f" onsubmit="return false"><b>{head}</b><div id="cv-asset-msg"></div>{C._group([f for f in fields if not f.advanced]).render(vals)}{deeper}<div class="row"><span class="grow"></span>{C._btn("Save", "asset_save", face=payload["face"], pid=p["id"], kind=kind, name=name, include="#cv-asset-f")}{C._btn("Cancel", "asset_form", close="1")}</div></form>""", "cv-asset-form")

async def _h_asset_save(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin makes or changes things on a provider.", True), "cv-msg")
    p, kind = C.AV.lib.get("provider", payload["pid"]), payload["kind"]
    kinds = (await C.PROV.manage(p, "GET"))["kinds"]
    k = kinds[kind]
    name = payload.get("name") or (payload.get("new_name", "").strip() if k.get("plain_names") else C._slug(payload.get("new_name", ""), bool(k.get("keep_case"))))   # a kind whose names are something's real name (a file's) takes them as written; the provider says what a name may be
    body = {key: v for key, v in C._group(_asset_fields(k, [], False)).parse(payload).items() if v not in ("", None)}
    if not name: return imr.oob(C._note("It needs a name.", True), "cv-msg").oob(C._note("It needs a name.", True), "cv-asset-msg")
    try: await C.PROV.manage(p, "PUT", kind, name, await _from_elsewhere(p, kinds, body))
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg").oob(C._note(str(e), True), "cv-asset-msg")   # also in the form, which may be far below the top
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"Saved {name}."))

async def _h_asset_rename(request, payload, imr):
    """The thing under a new name on its machine, what it holds kept (the machine moves it). Capitals are kept as typed when the kind keeps case."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin renames things on a provider.", True), "cv-msg")
    p, kind = C.AV.lib.get("provider", payload["pid"]), payload["kind"]
    k = (await C.PROV.manage(p, "GET"))["kinds"][kind]
    to = payload.get("to", "").strip() if k.get("plain_names") else C._slug(payload.get("to", ""), bool(k.get("keep_case")))
    if not to or to == payload["name"]: return imr.oob(C._note("Give it a different name.", True), "cv-msg")
    try: await C.PROV.manage(p, "POST", kind, f"""{payload["name"]}/rename""", {"to": to})
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg").oob(C._note(str(e), True), "cv-asset-msg")
    C._recheck(p["id"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""Renamed {payload["name"]} to {to}. Pipelines and set-ups that named the old name need it chosen again."""))

async def _h_asset_del(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin removes things from a provider.", True), "cv-msg")
    try: await C.PROV.manage(C.AV.lib.get("provider", payload["pid"]), "DELETE", payload["kind"], payload["name"], query="?confirm=1" + ("&data=1" if payload.get("data") else ""))
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    C._recheck(payload["pid"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""Removed {payload["name"]}{" and what it held" if payload.get("data") else ""}."""))

async def _asset_pick(c, cap: str):
    """(provider, asset name, the row of tabs choosing it) among every asset offering cap; the choice is kept by the face's tab, so the views of one face show the same asset. None when there is none."""
    offers = C._mine(c.request, await C._offers())
    have = [(o["p"], a["name"]) for o in offers for a in o["assets"] if cap in a.get("capabilities", [])]
    if not have: return None, None, C._unreached(offers) + C._dim("nothing of this kind exists yet")
    cur = c.tab.get("asset") if c.tab.get("asset") in [p["id"] + "|" + n for p, n in have] else have[0][0]["id"] + "|" + have[0][1]
    p, name = next((p, n) for p, n in have if p["id"] + "|" + n == cur)
    return p, name, C._tab_row("cv-asset-tabs", c.host, [(n, p2["id"] + "|" + n == cur, {"asset": p2["id"] + "|" + n}) for p2, n in have])

def _program_btns(c, p: dict, name: str) -> str:
    """The panel's ways to steer the program behind an asset, from its data: "cancel" and "retry" (capabilities: stop its work on what was added, take up what failed again), "clear" (a capability: empty it and keep it) and "service" (the name of the program on its machine, {asset} filled: stopped at once, or started again, from here)."""
    sp, kw = c.spec, {"face": c.face["id"], "pid": p["id"], "asset": name}
    svc = sp.get("service", "").replace("{asset}", name)
    return "".join(x for x in (
        C._btn("Stop its work", "program", cap=sp["cancel"], title="Asks the program to stop working on what was added; what is half done is marked failed", **kw) if sp.get("cancel") else "",
        C._btn("Take up failed again", "program", cap=sp["retry"], **kw) if sp.get("retry") else "",
        C._btn("Empty it", "program", "ui-btn cv-danger", cap=sp["clear"], confirm=f"Remove everything {name} holds, and everything worked out from it? {name} itself stays, with its settings. This cannot be undone.", title="Removes everything it holds and keeps the asset itself", **kw) if sp.get("clear") else "",
        C._btn("Hard stop", "program", "ui-btn cv-danger", svc=svc, verb="kill", confirm="Kill its program at once? Work under way is lost and has to be taken up again.", title="Kills the program on its machine; it starts again with the next work", **kw) if svc else "",
        C._btn("Restart it", "program", svc=svc, verb="restart", **kw) if svc else ""))

async def _h_program(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin steers a provider's programs.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    try: await (C.PROV.machine(p, "POST", "/node/restart", {}, timeout=20.0) if payload.get("node") else C.PROV.machine(p, "POST", f"""/services/{quote(payload["svc"])}/{payload["verb"]}""", {}, timeout=300.0) if payload.get("svc") else C.PROV.run(p, payload["cap"], {"model": payload["asset"]}))
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    C._recheck(payload["pid"])
    return await C._refresh(request, imr, payload["face"], C._note(f"""{payload["asset"]}: {payload.get("verb") or "asked"} - done."""))

async def p_records(c) -> str:
    """What an asset holds. The panel's own data says how to ask: {"list": capability, "in": the list's field in its answer, "status": capability, "remove": capability, "open": capability answering one record whole ({"text"}), "id": a record's id field, "columns": {heading: field}}, and how to steer its program (see _program_btns). Which asset: chosen at the top, among all that offer the list capability."""
    p, name, chips = await _asset_pick(c, c.spec["list"])
    if not p: return chips
    try: status, found = (await C.PROV.run(p, c.spec["status"], {"model": name}))["result"] if c.spec.get("status") else {}, (await C.PROV.run(p, c.spec["list"], {"model": name, "page_size": 200}))["result"]
    except C.PROV.ProviderError as e: return f"""{chips}{C._note(str(e), True)}"""
    cols, recs = c.spec["columns"], found.get(c.spec.get("in", "documents"), [])
    waiting = status.get("queued") or []
    going = {str(i) for q in waiting if q.get("capability") == c.spec.get("remove") for i in (q.get("body") or {}).get("ids") or []}   # records whose removal is kept until the program is free
    def row(d):
        cells = "".join(f"""<td>{C._esc(C._shown(d.get(f))[:160])}</td>""" for f in cols.values())
        rid = str(d.get(c.spec.get("id", "id")))
        if rid in going: return f"""<tr class="cv-dim"><td colspan="{len(cols)}" style="text-decoration:line-through">{C._esc(C._shown(d.get(next(iter(cols.values()))))[:160])}</td><td><span class="chip cv-mid" title="Asked to be removed; the program is busy adding, so the removal is kept and done as soon as it is free">removal waiting</span></td></tr>"""
        see = C._btn("Open", "record_open", "ui-btn cv-small", pid=p["id"], asset=name, cap=c.spec["open"], rid=rid, shown=C._shown(d.get(next(iter(cols.values()))))[:120]) if c.spec.get("open") else ""
        return f"""<tr>{cells}<td>{see}{C._btn("&#x2715;", "record_del", "ui-btn cv-small", face=c.face["id"], pid=p["id"], asset=name, cap=c.spec["remove"], rid=rid, confirm="Remove this from what it holds?", title="Remove from the group (while it is busy adding, the removal is kept and done when it is free)") if c.spec.get("remove") else ""}</td></tr>"""
    counts = " | ".join(f"{k}: {v}" for k, v in (status.get("counts") or {}).items()) + (" | working on what was added" + (f""": {C._shown(status["doing"])}""" if status.get("doing") else "") if status.get("busy") else "") + (f""" | {len(status["queued"])} waiting until it is free: """ + ", ".join(C._esc(str(q["capability"]).replace("knowledge_", "")) for q in status["queued"][:6]) if status.get("queued") else "")
    heads = "".join(f"""<th>{C._esc(h)}</th>""" for h in cols)
    held = C._note(f"""{len(waiting)} request(s) wait until the program is free, in this order: """ + "; ".join(f"""{str(q.get("capability", "")).replace("knowledge_", "")}{" of " + str(len(q["body"]["ids"])) + " record(s)" if (q.get("body") or {}).get("ids") else ""}""" for q in waiting) + ". Nothing is lost: each is sent as soon as the program takes it.") if waiting else ""
    return f"""{chips}{held}<div class="row">{C._dim(C._esc(counts))}<span class="grow"></span>{_program_btns(c, p, name)}</div>{_progress(status)}<table class="cv-tbl"><tr>{heads}<th></th></tr>{"".join(row(d) for d in recs)}</table>{"" if recs else C._dim("it holds nothing yet")}<div id="cv-record-view"></div>"""

def _progress(status: dict) -> str:
    """While the program works: its job, the batch it is on, and its own recent messages in full (they name the file and the chunk: "Chunk 3 of 12 extracted ..."). Nothing when it is idle or says none of this."""
    g = status.get("progress") or {}
    if not status.get("busy") or not g: return ""
    head = " | ".join(x for x in (str(g.get("job_name") or ""), f"""batch {g["cur_batch"]} of {g["batchs"]}""" if g.get("batchs") else "", f"""{g["docs"]} document(s) in this job""" if g.get("docs") else "", f"""since {str(g["job_start"])[:19].replace("T", " ")}""" if g.get("job_start") else "") if x)
    said = [str(m) for m in (g.get("history_messages") or [])][-12:]
    return f"""<details class="sec" open><summary>{C._esc(head or "working")}</summary><div class="pre-wrap mono cv-dim">{C._esc(chr(10).join(said))}</div></details>""" if said or head else ""

def _dig(d, path: str):
    for k in path.split("."): d = d.get(k) if isinstance(d, dict) else None
    return d

GRAPH_LAYOUTS = (("force", "Force"), ("ring", "Ring (by type)"), ("rings", "Rings (hubs inside)"))   # the layouts the portal's graph_view.js knows

async def p_graph(c) -> str:
    """An asset's graph, drawn by the portal's graph_view.js. The panel's data: {"graph": capability answering {nodes, edges, is_truncated}, "labels": capability answering {labels} (what the graph can be centred on), "type" and "info": where a node's kind and description are in it, "joins": a separator the program puts between merged descriptions}. Centre, depth and size are kept by the face's tab; a large graph is asked for a part at a time (around one label, at most so many nodes)."""
    p, name, chips = await _asset_pick(c, c.spec["graph"])
    if not p: return chips
    g = {"label": c.tab.get("g_label") or "*", "depth": int(c.tab.get("g_depth") or 2), "max_nodes": int(c.tab.get("g_max") or 300), "layout": c.tab.get("g_layout") or "force"}
    try: data, labels = (await C.PROV.run(p, c.spec["graph"], {"model": name, **g}))["result"], (await C.PROV.run(p, c.spec["labels"], {"model": name}))["result"].get("labels", []) if c.spec.get("labels") else []
    except C.PROV.ProviderError as e: return f"""{chips}{C._note(str(e), True)}"""
    text = lambda d, n: str(_dig(d, c.spec.get("info", "properties.description")) or "").replace(c.spec.get("joins") or "\x00", "\n")[:n]
    nodes = [{"id": str(n.get("id")), "label": str((n.get("labels") or [n.get("id")])[0]), "type": str(_dig(n, c.spec.get("type", "properties.entity_type")) or ""), "info": text(n, 800)} for n in data.get("nodes", [])]
    edges = [{"s": str(e.get("source")), "t": str(e.get("target")), "info": text(e, 300)} for e in data.get("edges", [])]
    fid, opts = f"cv-graph-f-{c.face['id']}", "".join(f"""<option value="{C._esc(l)}">""" for l in labels[:3000])
    layouts = "".join(f"""<option value="{v}"{" selected" if v == g["layout"] else ""}>{l}</option>""" for v, l in GRAPH_LAYOUTS)
    said = f"""{len(nodes)} nodes, {len(edges)} edges""" + (" - cut at the most nodes asked for: centre it on a label, or ask for more" if data.get("is_truncated") else "")
    form = f"""<form id="{fid}" class="row" style="flex-wrap:wrap" onsubmit="return false"><input name="g_label" list="{fid}-l" value="{C._esc(g["label"])}" class="module-select" style="width:13rem" title="what it is centred on: pick from the list, or * for everything"><datalist id="{fid}-l"><option value="*">{opts}</datalist><label class="row cv-dim">depth<input type="number" name="g_depth" value="{g["depth"]}" min="1" max="6" class="module-select" style="width:4rem"></label><label class="row cv-dim">most nodes<input type="number" name="g_max" value="{g["max_nodes"]}" min="10" step="50" class="module-select" style="width:5rem"></label><label class="row cv-dim">layout<select name="g_layout" class="module-select">{layouts}</select></label>{C._btn("Show", "open_tab", id=c.host, include="#" + fid)}<span class="cv-dim">{said}</span></form>"""
    init = f"""(function go() {{ var b = document.getElementById('cv-graph'); if (!b || b.dataset.ready) return; if (!window.graphView) return setTimeout(go, 50); b.dataset.ready = 1; graphView(b, {{layout: b.dataset.layout, onOpen: function (n) {{ htmx.ajax('POST', '/im/in', {{values: {{type: 'corvid_open_tab', branch: '{C.IM.branch_id}', lvl: 1, id: '{c.host}', g_label: n.id}}, swap: 'none'}}); }}}}); }})();"""
    js = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False).replace("</", "<\\/")
    return f"""{chips}{form}{C._dim("Tap a node for what it is and what it links to; double-tap to centre on it. Drag to move, wheel or two fingers to zoom.")}<div id="cv-graph" class="cv-graph" data-layout="{C._esc(g["layout"])}"><script type="application/json">{js}</script></div><script src="/static/js/graph_view.js"></script><script>{init}</script>"""

SHOWN_CHARS = 300_000   # how much of one record's text is put on the page; the rest is said to be cut

async def _h_record_open(request, payload, imr):
    """One record whole, as the capability the panel names answers it, shown under the list."""
    if payload.get("close"): return imr.oob("", "cv-record-view")
    try: text = str((await C.PROV.run(C.AV.lib.get("provider", payload["pid"]), payload["cap"], {"model": payload["asset"], "id": payload["rid"]}))["result"].get("text") or "")
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-record-view")
    cut = C._dim(f"The first {SHOWN_CHARS} of {len(text)} characters are shown.") if len(text) > SHOWN_CHARS else ""
    return imr.oob(f"""<div class="cv-form"><div class="row"><b class="grow">{C._esc(payload.get("shown") or payload["rid"])}</b><span class="cv-dim">{len(text)} characters</span>{C._btn("Close", "record_open", close="1")}</div>{cut}<div class="quote-block pre-wrap cv-doc">{C._esc(text[:SHOWN_CHARS])}</div></div>""", "cv-record-view")

async def _h_record_del(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin removes what an asset holds, for now.", True), "cv-msg")
    try: got = (await C.PROV.run(C.AV.lib.get("provider", payload["pid"]), payload["cap"], {"model": payload["asset"], "ids": [payload["rid"]]})).get("result") or {}
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    return await C._refresh(request, imr, payload["face"], C._note("It is busy adding: the removal is kept and done as soon as it is free (it shows under the list until then)." if got.get("status") == "queued" else "Removed." if got.get("status") in ("deletion_started", "success", None) else f"""It answered: {C._esc(str(got.get("status")))} {C._esc(str(got.get("message", ""))[:200])}"""))

def init(c):
    global C
    C = c
    def kept(fn):
        """What an asset holds is shown and changed only for those its pools allow (the request names the asset)."""
        async def go(request, payload, imr): return await fn(request, payload, imr) if not (payload.get("pid") and payload.get("asset")) or C._usable(request, payload["pid"], payload["asset"]) else imr.oob(C._note(C.AV.access.why_not(C.AV.lib, C._user(request), payload["pid"], payload["asset"]), True), "cv-msg")
        return go
    C.IM.scripts.update({f"corvid_{k}": [kept(fn)] for k, fn in {"asset_form": _h_asset_form, "asset_save": _h_asset_save, "asset_del": _h_asset_del, "asset_rename": _h_asset_rename, "record_del": _h_record_del, "record_open": _h_record_open, "program": _h_program}.items()})
