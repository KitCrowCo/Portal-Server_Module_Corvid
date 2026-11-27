"""trace_view.py - what an agent step did, round by round, read from its run's journal (the "round" and "check" entries Aviary's agent loop writes): its reasoning, what it wrote, each tool call with its arguments and the head of its result, the round's time and tokens. Nothing here changes a run.
run_trace(r): every round of one run and of the runs its steps made (an orchestrator's agent tasks), for the run view.
p_trace: a panel beside a conversation - one line for where the conversation's latest turn stands (which run, round, the last tool and whether it worked), the steps of its run and of every task it handed on (each with where it stands), its rounds below; it asks again every 2 s while the turn works, every 15 s otherwise. Rounds keep their place open or closed across the redraws (ids, corvid KEEP_OPEN_JS).
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import json, time

C = None

def init(c):
    global C
    C = c

# --- Reading ---

def _notes(r, *what) -> list:
    f = r.dir / "journal.jsonl"
    return [e for e in map(json.loads, f.read_text().splitlines()) if e["what"] in what] if f.exists() else []

def _placed(e: dict) -> str:
    """A role's placement in words: the model, the machine, what the machine said it needs, and whether it waits."""
    who = (C.AV.lib.get("provider", e["provider"]) if C.AV.lib.has("provider", e["provider"]) else {}).get("name") or e["provider"]
    need = f""" (needs about {e["need_gb"]} GB)""" if e.get("need_gb") else ""
    warn = f""" <span class="cv-mid" title="{C._esc(e.get("will", ""))}">- sent although its plan says it does not fit (the load decides; hover for the machine's answer)</span>""" if e.get("fits") == "try" else ""
    return f"""{C._esc(e["role"])}: {C._esc(e["asset"])} on {C._esc(who)}{need}{" - waits for the machine" if e.get("fits") == "wait" else ""}{warn}"""

def _n(u: dict, *keys) -> int: return int(next((u[k] for k in keys if u.get(k) is not None), 0) or 0)   # a token count under any of the names programs use

def about(r) -> str:
    """What a turn took, under the progress line: each role's machine and model with what the machine said it needs, the last request's tokens (in, out, against the window asked for or met), all requests' together, and any conversation fitted to a window."""
    placed = [e for k in _tree(r) for e in _notes(k, "placed")]
    work = [e for k in _tree(r) for e in _notes(k, "work")]
    fit = [e for k in _tree(r) for e in _notes(k, "fit")]
    seen = {}
    for e in placed: seen[(e["role"], e["provider"], e["asset"])] = e
    where = " | ".join(_placed(e) for e in seen.values())
    last, ins, outs = (work[-1].get("usage") or {}) if work else {}, sum(_n(e.get("usage") or {}, "prompt_n", "prompt_tokens", "prompt_eval_count") for e in work), sum(_n(e.get("usage") or {}, "gen_n", "completion_tokens", "eval_count") for e in work)
    win = int(r.data.get("num_ctx") or 0) or (fit[-1].get("window") if fit else 0)
    tokens = f"""last request: {_n(last, "prompt_n", "prompt_tokens", "prompt_eval_count")} tokens in{f" of a {win} window" if win else ""}, {_n(last, "gen_n", "completion_tokens", "eval_count")} out | {len(work)} request(s): {ins} in, {outs} out""" if work else ""
    trimmed = f"""fitted to the window {len(fit)} time(s), the latest keeping {fit[-1].get("messages")} messages""" if fit else ""
    return "".join(C._dim(x) for x in (where, tokens, trimmed) if x)

def _entries(r) -> list:
    f = r.dir / "journal.jsonl"
    return [{**e, "run": r.id} for e in map(json.loads, f.read_text().splitlines()) if e["what"] in ("round", "check")] if f.exists() else []

def _kids(r) -> list: return sorted((k for k in C.AV.director.runs.values() if k.meta.get("parent") == r.id), key=lambda k: k.meta["created"])
def _tree(r) -> list: return [r] + [x for k in _kids(r) for x in _tree(k)]
def _ok(result: str) -> bool: return not result.startswith("error")
def _tokens(u: dict) -> str: return f"""{u.get("prompt_n", "?")} in, {u.get("gen_n", "?")} out""" if u else "no token count reported"
def _label(r, top) -> str: return "this turn" if r is top else r.id.split("~", 1)[-1]
def _id(*parts) -> str: return C._elid("tr-" + "-".join(str(p) for p in parts))   # a stable element id, so a redraw keeps what was opened

# --- Drawing ---

def _call(c: dict) -> str:
    args = json.dumps(c["arguments"], ensure_ascii=False, indent=1)
    return f"""<details class="sec"><summary><span class="chip {"cv-ok" if _ok(c["result"]) else "cv-bad"}">{C._esc(c["name"] or "unreadable call")}</span> <span class="cv-dim mono">{C._esc(" ".join(args.split())[:140])}</span></summary><div class="quote-block mono cv-log pre-wrap">{C._esc(args)}</div><div class="quote-block mono cv-log pre-wrap">{C._esc(c["result"]) or "(no result recorded: finish, or the round ended at this call)"}</div></details>"""

def _round(e: dict) -> str:
    if e["what"] == "check": return C._note(f"""Goal check {"passed" if e["passed"] else "failed"}{": " + e["feedback"] if e.get("feedback") else ""}""", not e["passed"])
    bad = sum(not _ok(c["result"]) for c in e["calls"])
    calls = f"""{len(e["calls"])} call{"" if len(e["calls"]) == 1 else "s"}""" + (f" ({bad} failed)" if bad else "") if e["calls"] else "no tool call"
    think = f"""<details class="sec"><summary class="cv-dim">Reasoning ({len(e["thinking"])} chars)</summary><div class="quote-block cv-log pre-wrap">{C._esc(e["thinking"])}</div></details>""" if e["thinking"] else ""
    said = f"""<div class="quote-block pre-wrap">{C._esc(e["text"])}</div>""" if e["text"].strip() else ""
    return f"""<details class="sec" id="{_id(e.get("run", ""), e["step"], e["n"])}"><summary>Round {e["n"] + 1} <span class="cv-dim">{C._esc(e["step"])} - {calls} - {e["seconds"]:.1f} s - {_tokens(e["usage"])}</span></summary>{think}{said}{"".join(_call(c) for c in e["calls"])}</details>"""

def run_trace(r, top=None) -> str:
    """Every agent round of r, then each run its steps made under its own heading, in the order they were made."""
    top = top or r
    kids = "".join(f"""<div class="cv-form"><div class="row"><b class="grow mono">{C._esc(_label(k, top))}</b><span class="chip {C._STATE.get(k.meta["state"], "")}">{C._esc(k.meta["state"])}</span></div>{run_trace(k, top) or C._dim("no agent rounds")}</div>""" for k in _kids(r))
    return "".join(_round(e) for e in _entries(r)) + kids

def progress(r) -> str:
    """One line: the run's state, its latest round anywhere under it (which run, round n, the last tool and whether it worked), how many rounds in all, and how long since the latest ended."""
    every = [(k, e) for k in _tree(r) for e in _entries(k) if e["what"] == "round"]
    state = f"""<span class="chip {C._STATE.get(r.meta["state"], "")}">{C._esc(r.meta["state"])}</span>"""
    if not every: return f"""<div class="row">{state}<span class="grow cv-dim">no agent round yet</span></div>"""
    k, e = max(every, key=lambda ke: ke[1]["t"])
    last = e["calls"][-1] if e["calls"] else None
    tool = f"""{last["name"]} {"ok" if _ok(last["result"]) else "failed"}""" if last else "no tool call"
    return f"""<div class="row">{state}<span class="grow cv-dim">{C._esc(_label(k, r))}: round {e["n"] + 1}, {C._esc(tool)} - {len(every)} rounds in all, the latest {int(time.time() - e["t"])} s ago</span></div>"""

def steps(r) -> str:
    """Where each step of a run stands, as one row of chips (done, running, next, waiting, unreached)."""
    chip = lambda k, v: f"""<span class="chip {C._STATE.get(v, "")}" title="{C._esc(v)}">{C._esc(k)}</span>"""
    return f"""<div class="row" style="gap:.2rem">{"".join(chip(k, v) for k, v in C._step_states(r).items())}</div>"""

def tasks(r) -> str:
    """The run's steps, then each task it handed on (a run its steps made): what it was asked, its steps and where its latest round stands."""
    kid = lambda k: f"""<details class="list-row" id="{_id("task", k.id)}" {"open" if k.meta["state"] in C.LIVE else ""}><summary class="row"><b class="mono grow">{C._esc(_label(k, r))}</b><span class="chip {C._STATE.get(k.meta["state"], "")}">{C._esc(k.meta["state"])}</span>{C._btn("Open", "run_view", "ui-btn cv-small", id=k.id)}</summary>{C._dim(C._esc(str(k.data.get("task") or "")[:300]))}{steps(k)}{progress(k)}</details>"""
    return f"""<b>Steps</b>{steps(r)}{("<b>Tasks it handed on</b>" + "".join(kid(k) for k in _kids(r))) if _kids(r) else ""}"""

# --- Panel ---

async def p_trace(c) -> str:
    t = C._current(c.request, c.face, c.tab)
    r = C.AV.director.runs.get(t["pending"]) if t["pending"] else None
    if not r: return f"""<div {C.BESIDE["status_view"]._again(c, 15)}>{C._dim("Nothing has run in this conversation yet.")}</div>"""
    return f"""<div {C.BESIDE["status_view"]._again(c, 2 if r.meta["state"] in C.LIVE else 15)}>{progress(r)}{about(r)}{C._note(r.meta["error"], True) if r.meta.get("error") else ""}{tasks(r)}<details id="{_id("rounds", r.id)}" open><summary><b>Rounds</b></summary>{run_trace(r) or C._dim("This turn made no agent rounds (or ran before rounds were recorded).")}</details><div class="row">{C._btn("Open the run", "run_view", "ui-btn cv-small", id=r.id)}{C._btn("Change ...", "run_edit", "ui-btn cv-small", face=c.face["id"], id=r.id, title="Its form: Start anew, or Go on with this run from where it is (more rounds, a larger context window)") if r.meta["state"] not in C.LIVE else ""}</div></div>"""
