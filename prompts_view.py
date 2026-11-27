"""prompts_view.py - kept prompts for pictures, as the earlier Image tool had them: a list with each prompt's state (not encoded, encoding, ready, failed), an editor that saves the text without encoding it, Encode as its own act,
the encodings each prompt has (which encoder, which machine, how long, for which text), and making a picture from the chosen prompt, which uses a kept encoding when one matches (no encoder then).
Prompts are library objects of kind "image_prompt" ({"id", "name", "text", "max_len": tokens kept, "truncate": a longer prompt cut, "encoder": {"provider", "asset"} or none (placed), "encodings": [{embed, at, encoder, max_len, tokens, text, t}]}); how a prompt is encoded belongs to the prompt, so the picture form has none of it. Encodings are noted by the pipelines image_encode, image_make and image_change (step lib_note).
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import time

C = None
SEL = {}   # person -> the prompt they have chosen here (kept while the portal runs; the first prompt otherwise)
SIDES = ("left", "right")   # what a change to a prompt redraws: the form in the workspace takes the chosen prompt when it starts, so what is picked or drawn on it stays
KIND, MAX_LEN = "image_prompt", 512   # tokens kept when a prompt says nothing else; an encoding counts as ready for the text it was made of at the prompt's length

def init(c):
    global C
    C = c
    C.CHOSEN.update({"prompt": lambda request: (_chosen(C._user(request)) or {}).get("id", ""), "prompt.max_len": lambda request: _len(_chosen(C._user(request)) or {}), "prompt.truncate": lambda request: bool((_chosen(C._user(request)) or {}).get("truncate", True)), "prompt.encoder": lambda request: (_chosen(C._user(request)) or {}).get("encoder"), "prompt.text": lambda request: (_chosen(C._user(request)) or {}).get("text", "")})   # prompt.text: the words themselves, for a pipeline that takes them and has no kept encoding to use (clips)
    C.IM.scripts.update({"corvid_prompt_pick": [_h_pick], "corvid_prompt_new": [_h_new], "corvid_prompt_save": [_h_save], "corvid_prompt_encode": [_h_encode], "corvid_prompt_remove": [_h_remove]})

# --- State of a prompt ---

def _len(p: dict) -> int: return int(p.get("max_len") or MAX_LEN)
def _ready(p: dict) -> list: return [e] if (e := C.STEPS.kept_encoding(p, p.get("text", ""), _len(p), MAX_LEN)) else []   # Aviary's own rule (steps.kept_encoding): the same one a picture run asks, so "ready" here means that run will not encode

def _encoding_runs(pid: str, plans=("image_encode", "image_make", "image_change", "image_inpaint")) -> list: return [r for r in C.AV.director.runs.values() if r.plan.get("id") in plans and r.data.get("saved") == pid and r.meta["state"] in C.LIVE]

def _failed(pid: str):
    """The newest encode run of this prompt, when it failed: its error."""
    runs = sorted((r for r in C.AV.director.runs.values() if r.plan.get("id") == "image_encode" and r.data.get("saved") == pid), key=lambda r: r.meta["created"])
    return runs[-1].meta.get("error") if runs and runs[-1].meta["state"] in ("failed", "unplaced") else ""

def state(p: dict) -> tuple:
    """(word, colour class, detail) for a prompt now: encoding, ready, failed, or not encoded (for this text)."""
    if _encoding_runs(p["id"], ("image_encode",)): return "encoding", "cv-mid", "a run is encoding it now"
    if r := _ready(p): return "ready", "cv-ok", f"""{_tokens(r[-1])} tokens, {r[-1].get("encoder", "?")} on {_machine(r[-1].get("at", ""))}""" + (" - a picture is being painted from it" if _encoding_runs(p["id"]) else "")   # a picture run of a ready prompt paints from the kept encoding (steps.kept_encoding); it does not encode
    if _encoding_runs(p["id"]): return "encoding", "cv-mid", "a picture run is encoding it first"
    if e := _failed(p["id"]): return "failed", "cv-bad", e
    return "not encoded", "cv-dim", "older encodings are of an earlier text" if p.get("encodings") else "never encoded"

def _tokens(e: dict) -> str:
    t = e.get("tokens")
    return str(t.get("tokenized_len") or t.get("tokens") or "?") if isinstance(t, dict) else str(t or "?")

def _machine(pid: str) -> str: return (C.AV.lib.get("provider", pid).get("name") or pid) if pid and C.AV.lib.has("provider", pid) else pid or "?"

def _chosen(user: str) -> dict:
    ps = C.AV.lib.list(KIND)
    return next((p for p in ps if p["id"] == SEL.get(user)), ps[0] if ps else None)

# --- Panels ---

async def p_prompts(c) -> str:
    """The kept prompts, each with its state; the chosen one marked."""
    user, ps = C._user(c.request), sorted(C.AV.lib.list(KIND), key=lambda p: -float(p.get("modified") or 0))
    cur = (_chosen(user) or {}).get("id")
    def row(p):
        word, cls, detail = state(p)
        return f"""<div class="side-list-item{" active" if p["id"] == cur else ""}" {C._act("prompt_pick", face=c.face["id"], pid=p["id"])}><span class="chip {cls}" title="{C._esc(detail)}">{word}</span> <span class="side-list-item-title">{C._esc(p.get("name") or p["id"])}</span> <span class="cv-dim">~{len(p.get("text", "")) // 4}t</span></div>"""
    poll = f"""hx-get="{C._P}/prompts?face={c.face["id"]}" hx-trigger="every 3s" hx-swap="outerHTML" """ if any(_encoding_runs(p["id"]) for p in ps) else ""   # while one encodes: its state follows by itself
    return f"""<div id="cv-prompts" {poll}><div class="row">{C._btn("+ New prompt", "prompt_new", face=c.face["id"])}</div>{"".join(row(p) for p in ps) or C._dim("No prompts yet: + New prompt, write it, Save. Encode when you want it ready.")}</div>"""

async def p_prompt(c) -> str:
    """The chosen prompt: its name and text (Save keeps them, nothing is encoded), its state, Encode, its encodings, and making a picture from it."""
    p = _chosen(C._user(c.request))
    if not p: return C._dim("Choose or make a prompt (left).")
    word, cls, detail = state(p)
    est, form, n = len(p.get("text", "")) // 4, f"cv-pr-{C._elid(p['id'])}", _len(p)
    warn = C._dim(f"""~{est} tokens is more than the {n} kept at encoding: {"the rest is cut" if p.get("truncate", True) else "encoding will refuse it"}.""") if est > n else ""
    encs_able = sorted({(f"""{o["p"]["id"]}|{a["name"]}""", f"""{a["name"]} on {o["p"].get("name") or o["p"]["id"]}""") for o in await C._offers() for a in o["assets"] if "text_encode" in (a.get("capabilities") or [])}, key=lambda x: x[1])
    cur = f"""{p["encoder"]["provider"]}|{p["encoder"]["asset"]}""" if p.get("encoder") else ""
    pick = f"""<select name="encoder" class="module-select" style="width:auto" title="Which encoder (model and machine) encodes this prompt. Placed: whichever fits when it starts.">{"".join(f'<option value="{C._esc(v)}"{" selected" if v == cur else ""}>{C._esc(t)}</option>' for v, t in [("", "encoder: placed when it starts"), *encs_able])}</select>"""
    how = f"""<div class="row" style="flex-wrap:wrap"><label class="cv-dim">tokens kept <input name="max_len" type="number" min="64" max="4096" step="64" value="{n}" class="module-select" style="width:6em"></label><label class="cv-dim"><input type="checkbox" name="truncate" value="1"{" checked" if p.get("truncate", True) else ""}> cut a longer prompt</label>{pick}</div>"""
    encs = "".join(f"""<tr><td>{C._esc(e.get("encoder", "?"))}</td><td>{C._esc(_machine(e.get("at", "")))}</td><td>{C._esc(str(e.get("max_len", "?")))}</td><td>{_tokens(e)}</td><td>{"this text" if e.get("text") == p.get("text", "") else '<span class="cv-dim">an earlier text</span>'}</td><td class="cv-dim">{time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("t") or 0))}</td></tr>""" for e in reversed(p.get("encodings") or []))
    return f"""<form id="{form}" class="cv-form" onsubmit="return false">
               <input name="name" class="module-select" value="{C._esc(p.get("name") or "")}" placeholder="Name">
               <textarea name="text" class="cm-input" rows="10" oninput="var t=document.getElementById('{form}-t');if(t)t.textContent='~'+(this.value.length>>2)+' tokens / {n}'">{C._esc(p.get("text", ""))}</textarea>
               <div class="row"><span class="chip {cls}">{word}</span><span class="grow"></span><span class="cv-dim" id="{form}-t">~{est} tokens / {n}</span></div>{C._dim(C._esc(detail))}{warn}{how}
               <div class="row">{C._btn("Save", "prompt_save", face=c.face["id"], pid=p["id"], include=f"#{form}", title="Keeps the name and text. Nothing is encoded; an encoding of the earlier text stays, marked as of an earlier text.")}{C._btn("Re-encode" if p.get("encodings") else "Encode", "prompt_encode", face=c.face["id"], pid=p["id"], include=f"#{form}", title="Saves, then encodes it on the encoder (placed as for any run, or as Settings > Needs says). The encoding is kept on that machine and noted here.")}<span class="grow"></span>{C._btn("Remove", "prompt_remove", "ui-btn cv-danger", face=c.face["id"], pid=p["id"], confirm="Remove this prompt? The library keeps it as an earlier version; its encodings stay on their machines.")}</div></form>
               {f'<details><summary class="cv-dim">Encodings ({len(p.get("encodings") or [])})</summary><table class="cv-tbl"><tr><th>encoder</th><th>kept on</th><th>length</th><th>tokens</th><th>of</th><th>when</th></tr>{encs}</table></details>' if encs else ""}"""

async def p_make(c) -> str:
    """The run form of a picture pipeline (the panel's "pipeline", image_make by default), open, with the chosen prompt filled in."""
    p, pid = _chosen(C._user(c.request)), c.spec.get("pipeline", "image_make")
    if not p: return C._dim("Choose or write a prompt on the left first: what is made here is made from it.")
    word, cls, detail = state(p)
    head = f"""<div class="row"><span class="cv-dim">From the prompt</span> <b>{C._esc(p.get("name") or p["id"])}</b> <span class="chip {cls}" title="{C._esc(detail)}">{word}</span><span class="cv-dim grow">{C._esc(detail)}</span></div>"""
    form = f"""<div id="cv-run-form">{await C._run_form_html(c.request, c.face["id"], pid, c.key, {"saved": p["id"]})}</div>"""
    if word == "ready": return f"""{head}{C._dim("Painted from its encoding: nothing is encoded at Start, and no encoder is loaded.")}{form}"""
    wait = C.BESIDE["status_view"]._again(c, 2) if word == "encoding" else ""   # while it is being encoded this panel looks again by itself
    return f"""<div {wait}>{head}{C._note("It is being encoded now." if word == "encoding" else "This prompt has no encoding yet for its text as it is now: Start encodes it first, once, and keeps the encoding - or encode it ahead on the left.", word != "encoding")}</div>{form if word != "encoding" else ""}"""

async def p_latest(c) -> str:
    """The newest picture made into the panel's space and folder, large, with a link to it."""
    fm = C.AV.space(c.spec.get("space", "media"))[0]
    root = fm.resolve(c.spec.get("folder", "images"))
    files = sorted((f for f in root.rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif")), key=lambda f: f.stat().st_mtime) if root.is_dir() else []
    if not files: return C._dim("Nothing made yet: what is made shows here, large.")
    rel = files[-1].relative_to(fm.resolve("")).as_posix()
    url = f"""{C._P}/media/{c.spec.get("space", "media")}/{rel}"""
    return f"""<a href="{url}" target="_blank"><img src="{url}" alt="{C._esc(rel)}" style="width:100%;max-height:70vh;object-fit:contain;display:block;margin:auto"></a><div class="cv-dim" style="text-align:center">{C._esc(rel)}</div>"""

async def p_progress(c) -> str:
    """The runs of the groups the panel names, newest first, with how far each is (it follows itself while one is under way)."""
    return C._run_list(c.request, c.face, c.key)

# --- Handlers ---

async def _h_pick(request, payload, imr):
    SEL[C._user(request)] = payload["pid"]
    return await C._refresh(request, imr, payload["face"], regions=SIDES)

async def _h_new(request, payload, imr):
    pid = f"""pr-{time.strftime("%Y%m%d-%H%M%S")}"""
    C.AV.lib.save(KIND, {"id": pid, "name": "New prompt", "text": "", "encodings": []}, by=C._user(request))
    SEL[C._user(request)] = pid
    return await C._refresh(request, imr, payload["face"])

def _save(request, payload) -> dict:
    p = C.AV.lib.get(KIND, payload["pid"])
    text = payload.get("text", p.get("text", "")).replace("\r\n", "\n")
    enc = payload.get("encoder", "")
    how = {"max_len": int(payload.get("max_len") or _len(p)), "truncate": bool(payload.get("truncate")), "encoder": {"provider": enc.split("|", 1)[0], "asset": enc.split("|", 1)[1]} if "|" in enc else None} if "max_len" in payload else {}   # the form held how it is encoded (a save from elsewhere keeps it)
    return C.AV.lib.save(KIND, {**p, "name": payload.get("name", "").strip() or text[:40] or "Untitled", "text": text, **how}, by=C._user(request))

async def _h_save(request, payload, imr):
    _save(request, payload)
    return await C._refresh(request, imr, payload["face"], C._note("Saved. Nothing was encoded."), regions=SIDES)

async def _h_encode(request, payload, imr):
    """Saved, then encoded by the pipeline image_encode (its encoder placed as for any run); the encoding is noted on the prompt when it is done."""
    p, face = _save(request, payload), C.AV.lib.get("face", payload["face"])
    if not p.get("text", "").strip(): return imr.oob(C._note("Nothing to encode: the prompt is empty.", True), "cv-msg")
    try: rid = await C.AV.start("image_encode", {"saved": p["id"], "prompt": "", "max_len": _len(p), "truncate": bool(p.get("truncate", True)), "again": bool(_ready(p))}, owner=C._user(request), profiles=face.get("profiles", []), pins={"encoder": p["encoder"]} if p.get("encoder") else None, may=C._may(request))
    except ValueError as e: return imr.oob(C._note(f"Not started: {e}", True), "cv-msg")
    return await C._refresh(request, imr, payload["face"], C._note(f"Encoding ({rid}); its state shows in the list."), regions=SIDES)

async def _h_remove(request, payload, imr):
    C.AV.lib.remove(KIND, payload["pid"])
    SEL.pop(C._user(request), None)
    return await C._refresh(request, imr, payload["face"], C._note("Removed; the library keeps it as an earlier version."))
