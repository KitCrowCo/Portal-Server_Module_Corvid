"""sent_view.py - what the model that answered was actually sent: the messages of the conversation's last answered turn as its run framed them (the system prompt first, then the conversation), each with its role in the words most programs use, and the turn's settings. Shown in a face's "This conversation" panel (corvid.py p_params), from the run kept in memory (a run from before the portal last started is not kept).
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
C = None

ROLES = {"system": "System prompt (role \"system\"): sent first, again with every turn", "user": "User message (role \"user\")", "assistant": "Earlier answer (role \"assistant\")", "tool": "Tool result (role \"tool\")"}
SETTINGS = ("think", "effort", "num_ctx", "kv_type", "prefer", "at_once")   # a turn's inputs that change how the model works, shown beside what it was sent

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_sent": [_h_sent]})

def _last_run(t: dict) -> str:
    """The run behind the conversation's latest answer (its "The run behind this" action), "" when there is none."""
    return next((a["vals"]["id"] for m in reversed(t["messages"]) if m["role"] in ("assistant", "system") for a in m.get("actions") or [] if a.get("vals", {}).get("type") == "corvid_run_view"), "")

def link(cid: str) -> str: return C._btn("What the model was sent last", "sent", cid=cid, title="The system prompt and the conversation exactly as the model received them with the latest answer, and that turn's settings")

def _block(n: int, m: dict) -> str:
    text = m.get("content") if isinstance(m.get("content"), str) else C._shown(m.get("content"))
    pics = f""", {len(m["images"])} picture(s)""" if m.get("images") else ""
    return f"""<details class="list-row" {"open" if m.get("role") == "system" else ""}><summary>{n}. <b>{C._esc(ROLES.get(m.get("role"), m.get("role", "?")))}</b> <span class="cv-dim">{len(text or "")} characters, about {len(text or "") // 4} tokens{pics}</span></summary><div class="mono pre-wrap scroll-pane" style="max-height:40vh">{C._esc(text or "")}</div></details>"""

async def _h_sent(request, payload, imr):
    """The latest answered turn's messages as sent (run data "framed"), into #cv-sent; closed with "close"."""
    if payload.get("close"): return imr.oob("", "cv-sent")
    t = C._talk(C._user(request), payload["cid"])
    rid = _last_run(t)
    r = C.AV.director.runs.get(rid) if rid else None
    if not r: return imr.oob(C._dim("Nothing to show: no answer yet, or its run is from before the portal last started (runs are kept in memory). Send a message, then look again."), "cv-sent")
    if r.meta.get("owner") != C._user(request) and not C._admin(request): return imr.oob(C._note("That run belongs to someone else.", True), "cv-sent")
    sent = r.data.get("framed")
    if not isinstance(sent, list): return imr.oob(C._dim(f"""Not known for that answer ({C._esc(r.plan.get("name") or rid)}): what a turn sent is held in memory only (it would copy the whole conversation into every run's folder), so an answer from before the portal last started, or from a pipeline that does not frame its messages under "framed", cannot show it. The run behind it (on the answer) shows each step it kept."""), "cv-sent")
    bound = "; ".join(f"""{role}: {b.get("asset", "")} on {C._esc((C.AV.lib.get("provider", b["provider"]).get("name") if C.AV.lib.has("provider", b.get("provider", "")) else b.get("provider", "")) or "")}""" for role, b in (r.meta.get("bound") or {}).items() if isinstance(b, dict))
    sets = ", ".join(f"""{k} = {C._esc(C._shown(r.data[k]))}""" for k in SETTINGS if r.data.get(k) not in (None, "", [], {}))
    head = f"""<div class="row"><b class="grow">Sent with the latest answer: {len(sent)} message(s)</b>{C._btn("Close", "sent", cid=t["id"], close="1")}</div>{C._dim(C._esc(bound))}{C._dim(C._esc("Settings of that turn: " + sets) if sets else "")}{await _loaded(r)}"""
    return imr.oob(f"""<div class="cv-sec">{head}{"".join(_block(n + 1, m) for n, m in enumerate(sent) if isinstance(m, dict))}</div>""", "cv-sent")

async def _loaded(r) -> str:
    """How the machine has the answering model loaded now (its program's plan: context, layers on the GPU, context-memory type, flash attention, the estimate and its notes), asked of each bound machine; "" when none says. What the speed of an answer depends on."""
    out = []
    for b in (r.meta.get("bound") or {}).values():
        if not (isinstance(b, dict) and C.AV.lib.has("provider", b.get("provider", ""))): continue
        try: svcs = (await C.PROV.machine(C.AV.lib.get("provider", b["provider"]), "GET", "/services", timeout=8.0))["services"]
        except C.PROV.ProviderError: continue
        for sv in svcs:
            pl = sv.get("plan") or {}
            if sv.get("model") != b.get("asset") or not pl: continue
            p, e = pl.get("params") or {}, pl.get("est") or {}
            out.append(f"""<details class="list-row"><summary>{C._esc(sv["name"])} has {C._esc(b.get("asset", ""))} loaded: context {p.get("ctx")}, GPU layers {p.get("ngl")} (99 = all), estimate {e.get("gpu_gb", "?")} GB on the GPU and {e.get("ram_gb", "?")} GB of system RAM, context memory {C._esc(p.get("kv_cache_type") or "f16")}, flash attention {C._esc(p.get("flash_attn") or "-")}, {sv.get("status")}</summary><div class="mono pre-wrap cv-dim">{C._esc(C._shown({"params": p, "estimate": e, "experiments": pl.get("experiments"), "notes": pl.get("notes")}))}</div></details>""")
    return "".join(out)
