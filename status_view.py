"""status_view.py - the program that does one need of a pipeline, on the machine placement would use now: what it says of itself (loaded or not, which model, its last error, its progress) and its own controls (load, unload, stop, clear the error).
A face names, in the panel's spec, the need and what the program offers for it, by the names its node module gives them (a module's "info" and "actions", read with GET /info/<name> and done with POST /act/<name>):
  {"panel": "status", "pipeline": "image_make", "role": "painter", "info": "image_status", "progress": "image_progress", "actions": [{"name": "image_load", "label": "Load", "model": "model_path"}, ...]}
  "model": the action's parameter that takes the placed model's name (so Load loads what this need would use). Nothing here starts a program unless an action says it does (Load).
  "warm": true: a Warm button - what a run started from this face now would use for this role (the prompt chosen on the left, its encoder ...: the spec's "inputs", "inputs_from", "pins_from", as a run form takes them) brought up ahead (Aviary.warm), and how long it took.
While the program is busy the panel asks again every 2 s by itself; otherwise every 15 s.
Conversations get "Prepare" in their header (prepare): the model of the next turn loaded on the machine it would use, and the talk so far read once, so the turn starts at once ("Ready (n s)").
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import json, time, asyncio

C = None

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_status_act": [_h_act], "corvid_status_warm": [_h_warm], "corvid_talk_warm": [_h_prepare]})

def _again(c, seconds: int) -> str:
    """This panel asking for itself again after a while (the same GET /panel the page used)."""
    vid, rest = c.key.split(":", 1)
    region, n = rest.split(".")
    return f"""hx-get="{C._P}/panel?face={C.quote(c.face["id"])}&amp;view={C.quote(vid)}&amp;region={region}&amp;n={n}&amp;host={C.quote(c.host)}" hx-trigger="every {seconds}s" hx-swap="outerHTML" """

def _warm_btn(c) -> str: return (C._btn("Warm", "status_warm", "ui-btn cv-small", face=c.face["id"], key=c.key, title="Loads now what a run from here would use for this, where it would run, so the run does not wait for it") + f"""<span id="cv-warm-{C._elid(c.key)}" class="cv-dim"></span>""") if c.spec.get("warm") else ""

def _value(v) -> str: return C._esc(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else "-" if v in (None, "") else str(v))

async def p_status(c) -> str:
    s, pl = c.spec, C.AV.lib.get("pipeline", c.spec["pipeline"])
    got = await C.BESIDE["needs_view"].now(pl["id"], s["role"], pl["roles"][s["role"]], C._user(c.request), c.face.get("profiles", []))
    if got.get("pending"): return f"""<div {_again(c, 2)}>{C._dim("Being placed ...")}</div>"""
    if got.get("error"): return f"""<div {_again(c, 15)}>{C._note("Nothing can do it now: " + got["error"], True)}</div>"""
    p, asset = C.AV.lib.get("provider", got["provider"]), got["asset"]
    if not s.get("info"): return await _plain(c, p, asset)
    try: info = await C.PROV.machine(p, "GET", f"""/info/{s["info"]}""", timeout=6.0)
    except C.PROV.ProviderError as e: return f"""<div {_again(c, 15)}><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip cv-bad" title="{C._esc(str(e))}">no answer</span> <div class="cv-bad" style="overflow-wrap:anywhere">{C._esc(str(e))}</div></div>"""
    prog = info.get("progress") or {}
    if s.get("progress") and not prog:
        try: prog = await C.PROV.machine(p, "GET", f"""/info/{s["progress"]}""", timeout=6.0)
        except C.PROV.ProviderError: prog = {}
    busy, up = bool(info.get("busy")) or prog.get("status") in ("running", "stopping"), info.get("status") != "stopped"
    state = ("busy", "cv-mid") if busy else ("loaded", "cv-ok") if info.get("loaded") else ("up, nothing loaded", "cv-dim") if up else ("stopped", "cv-dim")
    bar = f"""<div class="row"><progress max="{prog["total"]}" value="{prog.get("step", 0)}" style="flex:1"></progress><span class="cv-dim">{prog.get("step", 0)}/{prog["total"]} {C._esc(str(prog.get("status", "")))}</span></div>""" if prog.get("total") else ""
    err = f"""<div class="cv-bad" style="white-space:pre-wrap">{C._esc(str(info["last_error"]))}</div>""" if info.get("last_error") else ""
    shown = {k: v for k, v in info.items() if k not in ("log_tail", "progress", "last_error", "status", "busy", "loaded") and v not in (None, "", [], {})}
    facts = "".join(f"""<tr><td class="cv-dim">{C._esc(k.replace("_", " "))}</td><td class="mono">{_value(v)}</td></tr>""" for k, v in shown.items())
    btns = _warm_btn(c) + "".join(C._btn(a.get("label") or a["name"], "status_act", "ui-btn cv-small", face=c.face["id"], pid=p["id"], act=a["name"], param=a.get("model", ""), model=asset, title=a.get("about", "")) for a in s.get("actions") or [])
    log = f"""<details><summary class="cv-dim">its log</summary><pre class="mono" style="max-height:20em;overflow:auto">{C._esc(info["log_tail"][-6000:])}</pre></details>""" if info.get("log_tail") else ""
    return f"""<div {_again(c, 2 if busy else 15)}><div class="row"><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip {state[1]}">{state[0]}</span><span class="cv-dim grow mono" title="what placement would use now for {C._esc(s["role"])}">{C._esc(asset)}</span></div>{bar}{err}
               <table class="cv-tbl">{facts}</table><div class="row" style="flex-wrap:wrap">{btns}</div>{log}</div>"""

async def _plain(c, p: dict, asset: str) -> str:
    """For a program whose module names no status of its own: its entry among the machine's running programs (by "program", a name prefix, or the model it holds) - up or not, what it holds, idle for - and Stop."""
    try: st = await C.PROV.machine(p, "GET", "/control/status", timeout=6.0)
    except C.PROV.ProviderError as e: return f"""<div {_again(c, 15)}><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip cv-bad" title="{C._esc(str(e))}">no answer</span></div>"""
    sv = next((x for x in st.get("services") or [] if x.get("pid") and (x.get("model") == asset or (c.spec.get("program") and x["name"].startswith(c.spec["program"])))), None)
    if not sv: return f"""<div {_again(c, 15)}><div class="row"><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip cv-dim">not running</span><span class="cv-dim grow mono">{C._esc(asset)}</span></div>{C._dim("It starts by itself when work needs it.")}<div class="row">{_warm_btn(c)}</div></div>"""
    lease = sv.get("lease") or {}
    stop = C._btn("Stop", "status_act", "ui-btn cv-small", face=c.face["id"], pid=p["id"], act="", service=sv["name"], title="Stops the program and frees its memory (work running in it finishes first)")
    return f"""<div {_again(c, 15)}><div class="row"><b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip cv-ok">up</span><span class="cv-dim grow mono">{C._esc(asset)}</span></div>{C._dim(f'{lease.get("ram_gb", sv.get("rss_gb") or 0):.1f} GB held; idle {sv.get("idle_s") or 0} s; stops after {sv.get("stops_after_idle_s") or "never"} s idle')}<div class="row">{_warm_btn(c)}{stop}</div></div>"""

async def _h_act(request, payload, imr):
    """One of the program's own controls, on the machine named; a Load is given the model the need would use."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin uses a program's controls.", True), "cv-msg")
    q = f"""?{C.quote(payload["param"])}={C.quote(payload["model"])}""" if payload.get("param") else ""
    path = f"""/services/{C.quote(payload["service"])}/stop""" if payload.get("service") else f"""/act/{payload["act"]}{q}"""
    try: got = await C.PROV.machine(C.AV.lib.get("provider", payload["pid"]), "POST", path, timeout=600.0)
    except C.PROV.ProviderError as e: got = {"status": "Error", "detail": str(e)}
    bad = str(got.get("status", "")).lower() == "error"
    return await C._refresh(request, imr, payload["face"], C._note(C._esc(f"""{payload["act"] or "stop"}: {got.get("detail") or got.get("status") or "done"}"""), bad))

# --- Warming ahead ---

def said(got: dict, seconds: float) -> tuple:
    """(words, title, ok) for what Aviary.warm answered: "Ready (n s)" when every role it warmed is up, else what went wrong."""
    roles = {r: w for r, w in got.items() if not r.startswith("_")}
    bad = [f"""{r}: {w["error"]}""" for r, w in roles.items() if w.get("error")] + ([got["_unplaced"]] if got.get("_unplaced") else [])
    title = "; ".join(f"""{r}: {w.get("asset") or "-"} on {w.get("provider")} in {w.get("seconds")} s{" (its start read ahead)" if w.get("read_ahead") else " (" + w["why"] + ")" if w.get("why") else ""} - {w.get("how", "")}""" for r, w in roles.items() if not w.get("error"))
    if bad: return "Not ready: " + " | ".join(bad), title, False
    return (f"Ready ({seconds:.0f} s)" if roles else "Nothing to warm: no step this would run needs a model"), title, True

def _span(sid: str, words: str, title: str = "", cls: str = "cv-dim") -> str: return f"""<span id="{sid}" class="{cls}" hx-swap-oob="outerHTML" title="{C._esc(title)}">{C._esc(words)}</span>"""

def _later(sid: str, user: str, warm):
    """Warms in the background (it may take minutes) and tells the page when it is done; the page is answered at once."""
    async def go():
        t0 = time.time()
        try: got = await warm()
        except (ValueError, KeyError) as e: got = {"_unplaced": str(e)}
        words, title, ok = said(got, time.time() - t0)
        await C.WS.send_personal_message(_span(sid, words, title, "cv-ok" if ok else "cv-err"), user)
    asyncio.ensure_future(go())

def prepare(face_id: str, cid: str) -> str:
    """Prepare, in a conversation's header."""
    return f"""{C._btn("Prepare", "talk_warm", "ui-btn cv-small", face=face_id, cid=cid, title="Loads the model of the next turn where it would run, and reads the conversation so far once, so the next turn starts at once")}<span id="cv-warm-{C._elid(cid)}" class="cv-dim"></span>"""

async def _h_prepare(request, payload, imr):
    user, face = C._user(request), C.AV.lib.get("face", payload["face"])
    t, spec, sid = C._talk(user, payload["cid"]), C._conv_spec(face), f"""cv-warm-{C._elid(payload["cid"])}"""
    _later(sid, user, lambda: C.AV.warm(C._pipe(spec, t), C._turn_inputs(spec, t, user), owner=user, profiles=face.get("profiles", []), pins=C._pins(spec, t), may=C._may(request), case=face.get("case")))
    return imr.raw(_span(sid, "preparing ..."))

async def _h_warm(request, payload, imr):
    """Warm on a status panel: for its role only, with what a run started from this face now would be given."""
    user, face, sid = C._user(request), C.AV.lib.get("face", payload["face"]), f"""cv-warm-{C._elid(payload["key"])}"""
    spec = C._spec(face, payload["key"])
    pl = C.AV.lib.get("pipeline", spec["pipeline"])
    inputs, pins = C._spec_given(request, spec, pl)
    _later(sid, user, lambda: C.AV.warm(pl["id"], inputs, owner=user, profiles=face.get("profiles", []), pins=pins, roles=[spec["role"]], may=C._may(request), case=face.get("case")))
    return imr.raw(_span(sid, "warming ..."))
