"""media.py - Corvid's media parts, beside corvid.py: made files shown in the portal's image gallery (one per space), and voice in conversations.
Voice is two pipelines a face's conversation panel names: "hear" (a recording to words) before a turn, and "speak", whose voice says the answer sentence by sentence while it is written (Speaker). Listening may wait for a wake word (checked with a light recognizer, before the full one hears anything), say who is speaking (voiceprints, per login), and take a few spoken commands (stop, sleep). An answer marks text in another language with <lang code="xx">...</lang>: that text gets that language's voice, and the tags are never shown or said. How a conversation is spoken and heard is its own (panel "speech"). The chat's microphone is the portal chat interface's own (hold to talk, call mode); a face turns it on with "chat": {"voice": true}.
C is a live view of corvid.py's globals, set when Corvid starts."""
import io, re, json, time, wave, base64, asyncio, difflib
from pathlib import Path
from urllib.parse import quote
from fastapi import Request
from fastapi.responses import FileResponse

C = None
GALLERIES = {}   # space id -> the portal's ImageGallery over that space's folder

# --- Gallery: a space's files, through the portal's own image gallery ---

def gallery(space: str):
    if space not in GALLERIES: GALLERIES[space] = C.BI.ImageGallery(root_dir=C.AV.space(space)[0].root, IM=C.IM, intent_prefix=f"""corvid_gal_{C._elid(space)}""", nesting_level=1, file_manager=C.AV.space(space)[0], full_url_fn=lambda rel, s=space: f"""{C._P}/media/{s}/{quote(rel)}""")
    return GALLERIES[space]

async def p_gallery(c) -> str:
    """The files of a space (the panel's "space"), as pictures: open, page through, rename, move, delete - all the portal gallery's own."""
    sp = C.AV.lib.get("space", c.spec["space"])
    return f"""{C._dim(C._esc(sp.get("about", "")))}<div class="cv-gallery">{gallery(c.spec["space"]).render_shell()}</div>"""

async def media_file(request: Request, space: str, path: str):
    """One file of a space, for the gallery's full view and for players."""
    f = C.AV.space(space)[0].resolve(path)
    if not f.is_file(): return C.HTMLResponse("not found", status_code=404)
    return FileResponse(f)

async def thumb_file(request: Request, space: str, path: str):
    """A small picture of one file of a space (made once and kept in the space's .thumbs folder, as the portal's gallery does), for pickers."""
    if not (f := C.BI.ensure_thumb_cached(C.AV.space(space)[0], path)): return C.HTMLResponse("no picture", status_code=404)
    return FileResponse(f, headers={"Cache-Control": "private, max-age=86400"})

# --- Attachments: pictures and files with a message ---
# Kept with the conversation (data/conversations/<user>/files/<cid>/), named as uploaded (a taken name gets -2, -3). A message holds {"files": [{"name", "url", "image"}], "seen": what the eyes role read in its pictures}. The model that answers gets the text of files and what was read in pictures as part of the message; pictures themselves go only to the eyes role (the pipeline's "pictures"), downscaled.

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PICTURE_PX = 1600   # the longest side a picture is sent at: enough for a whiteboard's handwriting, small enough for a vision model's context
FILE_CHARS = 30000   # of one attached file's text, at most, given to the model

def _files_dir(user: str, cid: str) -> Path: return C._talk_dir(user) / "files" / Path(cid).name
def _url(cid: str, name: str, small: bool = False) -> str: return f"""{C._P}/talkfile/{quote(cid)}/{quote(name)}{"?small=1" if small else ""}"""
def _free(d: Path, name: str) -> str: return next(n for n in (name, *(f"{Path(name).stem}-{i}{Path(name).suffix}" for i in range(2, 10000))) if not (d / n).exists())

def attach_html(cid: str) -> str:
    """The footer's attach button (on a phone it offers the camera too) and the chips of what is picked; the chips sit inside the chat form, so Send carries their names."""
    return f"""<label class="cm-qbtn" title="Attach pictures or files">&#x1F4CE;<input type="file" name="files" multiple hidden hx-post="{C._P}/attach" hx-encoding="multipart/form-data" hx-trigger="change" hx-include="this" hx-vals='{{"cid": "{C._esc(cid)}"}}' hx-target="#cm-att-{cid}" hx-swap="beforeend" hx-on::after-request="this.value=''"></label><span id="cm-att-{cid}" class="row" style="flex-wrap:wrap"></span>"""

async def attach(request: Request):
    """Files picked in a conversation's footer, kept with it; answers a chip for each, holding the name Send carries."""
    form, user = await request.form(), C._user(request)
    cid = str(form["cid"])
    C._talk(user, cid)   # only into a conversation of this person's
    d, out = _files_dir(user, cid), ""
    d.mkdir(parents=True, exist_ok=True)
    for up in form.getlist("files"):
        name = _free(d, re.sub(r"[^\w.\- ]", "_", Path(up.filename or "file").name)[:120].strip() or "file")
        (d / name).write_bytes(await up.read())
        out += f"""<span class="chip">{"&#x1F5BC;" if Path(name).suffix.lower() in IMAGE_EXT else "&#x1F4C4;"} {C._esc(name)}<input type="hidden" name="att" value="{C._esc(name)}"><button type="button" class="cm-act" onclick="this.parentNode.remove()" title="Leave it out of this message">&#x2715;</button></span>"""
    return C.HTMLResponse(out)

async def talk_file(request: Request, cid: str, name: str, small: bool = False):
    """One attached file of one of this person's conversations; small: a picture made small (kept beside it) for the message it is shown in."""
    f = _files_dir(C._user(request), cid) / Path(name).name
    if not f.is_file(): return C.HTMLResponse("not found", status_code=404)
    if small and f.suffix.lower() in IMAGE_EXT:
        s = f.parent / ".small" / f"{f.name}.jpg"
        if not s.exists():
            s.parent.mkdir(exist_ok=True)
            s.write_bytes(_jpeg(f, 640))
        f = s
    return FileResponse(f, headers={"Cache-Control": "private, max-age=86400"})

def _jpeg(f: Path, px: int) -> bytes:
    """A picture turned upright (a phone's photo carries its turn as a tag), at most px on its longest side, as JPEG."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
    im.thumbnail((px, px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()

def message_files(user: str, cid: str, names) -> list:
    """What a message carries: the picked names (one, or a list) that are kept with this conversation."""
    d = _files_dir(user, cid)
    return [{"name": n, "url": _url(cid, n, Path(n).suffix.lower() in IMAGE_EXT), "full": _url(cid, n), "image": Path(n).suffix.lower() in IMAGE_EXT} for n in ([names] if isinstance(names, str) else names or []) if (d / Path(n).name).is_file()]

def _text_of(f: Path) -> str:
    """A file's text: what the portal reads from documents (text, tables, PDF), else the file itself when it is plain text (code, JSON, HTML ...), else a note that none could be read."""
    if (t := C.BI.extract_file_text(f)): return t
    try: return f.read_bytes().decode("utf-8")
    except UnicodeDecodeError: return "[no text could be read from this file]"

def for_model(user: str, cid: str, m: dict) -> str:
    """A message as the model that answers reads it: who said it when the voice was told apart ("(Name): ", "(Name?): " when only likely, "(another voice): "), its words, the text of its attached files (each up to FILE_CHARS), and what was read in its pictures."""
    d, parts = _files_dir(user, cid), [("(said to others in the room, not to you) " if m.get("aside") else "") + (f"""({m["speaker"]["said"]}): """ if m.get("speaker") else "") + str(m.get("content") or "")]
    parts += [f"""[Attached file {f["name"]}:]\n{_text_of(d / f["name"])[:FILE_CHARS]}""" for f in m.get("files") or [] if not f.get("image")]
    if m.get("seen"): parts.append(m["seen"])
    return "\n\n".join(x for x in parts if x)

def pictures(user: str, cid: str, m: dict) -> list:
    """A message's pictures as the eyes role gets them: JPEG as plain base64 (the contract's messages carry images as Ollama does), upright, at most PICTURE_PX on the longest side."""
    d = _files_dir(user, cid)
    return [base64.b64encode(_jpeg(d / f["name"], PICTURE_PX)).decode() for f in m.get("files") or [] if f.get("image")]

# --- Voice: heard before a turn, said after it ---

def _audio_dir(user: str) -> Path: return C.DATA / "audio" / Path(user).name
def _keep_audio(user: str, name: str, b64: str) -> str:
    """A recording kept beside the conversations (data URL or bare base64); answers the URL a player reaches it at."""
    f = _audio_dir(user) / Path(name).name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
    return f"""{C._P}/audio/{f.name}"""

async def audio_file(request: Request, name: str):
    f = _audio_dir(C._user(request)) / Path(name).name
    if not f.is_file(): return C.HTMLResponse("not found", status_code=404)
    return FileResponse(f)

async def _quiet(rid: str) -> tuple:
    """(state, run) once a run rests."""
    return await C.AV.director.wait(rid), C.AV.director.runs[rid]

async def _verdict(user: str, cid: str, heard: bool, say: str = "", stop: bool = False):
    """Told to the chat in the browser: whether the last utterance was heard (cm-voice: not heard resumes a reply it paused, heard drops it), a line for its listening status (cm-voice-say), and with stop, that what is being spoken stops (cm-voice-stop)."""
    await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cm-voice", "detail": {"sid": cid, "heard": heard}})
    if say: await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cm-voice-say", "detail": {"sid": cid, "text": say}})
    if stop: await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cm-voice-stop", "detail": {"sid": cid}})

async def _idle(user: str, cid: str, wait_s: float = 4.0) -> dict:
    """The conversation once no turn is running in it, waiting up to wait_s: an utterance that interrupted a reply pressed Stop just before it was sent, and that turn takes a moment to end."""
    t0 = time.time()
    while C._working(t := C._talk(user, cid)) and time.time() - t0 < wait_s: await asyncio.sleep(0.1)
    return t

async def h_audio(request, payload, imr):
    """The chat's microphone: {cid, audio_b64 = WAV data URL}. In this order: a voice sample being recorded is kept as one (nothing else happens); with listening by wake word, an utterance while not addressed is checked by the light recognizer and dropped unless it holds a wake word; then the face's "hear" pipeline turns it into words (and, with identification on, its voiceprint says who spoke, at the same time); a spoken stop or sleep command is done here. What was heard is said in the conversation like typed words, with the recording and who said it kept on the message, and the turn's answer is spoken. The browser is always told the verdict (cm-voice), so a reply the utterance paused resumes or stops."""
    user, cid, b64 = C._user(request), payload.get("cid", ""), payload.get("audio_b64", "")
    t = C._talk(user, cid)
    face, spec = C.AV.lib.get("face", t["face"]), C._conv_spec(C.AV.lib.get("face", t["face"]))
    if not b64 or not spec.get("hear"): return imr
    s, words, pins = speech(spec, t), _wake_words(face, speech(spec, t)), C._pins(spec, t)
    if (pid := ENROLL.pop(user, None)): return await _enroll(user, cid, face, spec, pid, b64, imr, pins)
    if s["listen"] == "wake" and not awake(cid) and s["wake_word"]:   # a wake word model (openWakeWord): milliseconds, nothing else heard until it fires
        try: got = await _wake_word(request, s, pins, b64)
        except (ValueError, KeyError, C.PROV.ProviderError) as e: return await _verdict(user, cid, False, f"wake word check failed: {e}") or imr
        if not got["woken"]: return await _verdict(user, cid, False, f"""not addressed - {_spoken(s["wake_word"])} scored {max(got["scores"].values() or [0]):.2f} (needs {float(s["wake_threshold"] or 0.5):.2f})""") or imr
        wake(cid, s)
        payload["_woken"] = _spoken(s["wake_word"])
    elif s["listen"] == "wake" and not awake(cid):
        try: light = await _light(face, user, spec, b64, s, words, pins)
        except (ValueError, KeyError, C.PROV.ProviderError) as e: return await _verdict(user, cid, False, f"wake check failed: {e}") or imr
        if _STOP.match(light): return await _verdict(user, cid, True, "stopped", stop=True) or imr   # stop needs no wake word: a long answer may outlast the time it stays addressed
        if not woken(light, words, float(s["wake_fuzz"] or 0.75)): return await _verdict(user, cid, False, f"""not addressed - heard "{light[:80]}" (say {words[0] if words else "the wake word"} first)""") or imr
        wake(cid, s)
        if len(_norm(light).split()) <= len(_norm(words[0]).split()) + 1: return await _verdict(user, cid, False, "listening - go on") or imr   # the wake word alone: the next utterance is the question
    t = await _idle(user, cid, 0.0 if s["listen"] == "aware" else 4.0)   # aware: an utterance during an answer is decided on first (an aside lets the answer go on)
    if C._working(t) and s["listen"] != "aware": return await _verdict(user, cid, False, "an answer is still being written - stop it first") or imr
    people = _people(user) if s["identify"] else {}
    async def hear(): return await _quiet(await C.AV.start(spec["hear"], {"audio_b64": b64, **({"language": s["language"]} if s["language"] else {})}, owner=user, profiles=face.get("profiles", []), pins=pins, may=C._may(request), case=face.get("case")))
    async def who():
        try: return _who(user, people, await _print(face, user, spec, b64, pins), s) if people else None
        except (ValueError, KeyError, C.PROV.ProviderError) as e: return {"said": "unknown voice", "badge": f"voice not told: {e}", "mine": False, "sure": False}
    try: (state, r), spk = await asyncio.gather(hear(), who())
    except ValueError as e: (state, r), spk = ("unplaced", type("R", (), {"data": {}, "meta": {"error": str(e)}})()), None
    heard = (r.data.get("text") or "").strip() if state == "done" else ""
    if not heard:
        await _verdict(user, cid, False)
        return imr.raw(C._chat_note(cid, C._esc("Nothing was heard." if state == "done" else f"""Not heard: the listening run is {state}. {r.meta.get("error", "")}""")))   # said in the conversation itself: a face that is a conversation alone has no other place for it
    if _STOP.match(heard): return await _verdict(user, cid, True, "stopped", stop=True) or imr
    if _SLEEP.search(heard) and s["listen"] == "wake":
        AWAKE.pop(cid, None)
        return await _verdict(user, cid, True, f"""sleeping - say {words[0] if words else "the wake word"} to talk again""", stop=True) or imr
    if payload.get("_woken") and len(_norm(heard).split()) <= len(payload["_woken"].split()) + 1: return await _verdict(user, cid, True, "listening - go on") or imr   # the wake word alone: the next utterance is the question
    if s["listen"] == "aware": return await _aware(request, user, cid, face, spec, s, words, pins, heard, b64, spk) or imr
    await _verdict(user, cid, True, f"""heard{" " + spk["badge"] if spk else ""}""")
    if s["listen"] == "wake": wake(cid, s)
    await _said(user, cid, heard, b64, spk)
    asyncio.create_task(C._turn(user, C._talk(user, cid), None, C._may(request), spoken=True))
    return imr

async def _said(user: str, cid: str, heard: str, b64: str, spk: dict, note: str = ""):
    """What was heard, said in the conversation like typed words: by whom (a voice told apart shows under its name; the login's own voice as the login), with its recording, and a note in its corner (who it most likely is; with awareness, what was decided)."""
    badge = " - ".join(x for x in ((spk or {}).get("badge", ""), note) if x)
    mine = C._msg("user", heard, user_name=user if not spk or spk["mine"] else spk["name"], **({"speaker": {k: spk[k] for k in ("said", "score", "name")}, "voice_badge": spk["badge"]} if spk else {}), **({"badge": badge} if badge else {}))
    mine["audio"] = {"url": _keep_audio(user, mine["id"] + ".wav", b64)}
    await C.WS.send_personal_message(C._take(user, C._talk(user, cid), mine), user)

# --- Awareness: is it for the assistant, is it finished? ---
# With listening "aware", each utterance is said in the conversation, then a quick decision model (the speech panel's "attend" pipeline, role judge) reads it with the conversation before it: answer now, wait for the rest (a pause mid-thought: decided again after hold_s of silence, answered at the latest after hold_max_s), or aside (people talking to each other: kept in the conversation as context for later, not answered, and an answer being spoken goes on). The assistant's name is not needed when the exchange is already with it. A decision that cannot be made answers, as listening without awareness would.

HELD: dict = {}   # conversation id -> {"n": utterances heard, "since": when the first unanswered one was, "task": the pending decision after a pause}
ACTS = {"answer": "for the assistant", "wait": "waiting for the rest", "aside": "not for the assistant"}

def voice_opts(spec: dict, t: dict): return {"merge_running": 0} if spec.get("hear") and speech(spec, t)["listen"] == "aware" else None   # aware: the browser does not stop an answer by itself when someone speaks; the decision does

def _line(m: dict, name: str) -> str: return f"""{name}: {m["content"]}""" if m["role"] == "assistant" else f"""({(m.get("speaker") or {}).get("said") or m.get("user_name") or "someone"}): {m["content"]}"""

async def _decide(request, user: str, cid: str, face: dict, spec: dict, s: dict, words: list, pins: dict, pause_s: float = 0.0) -> tuple:
    """(act, why): the decision on the conversation's newest utterance, with the conversation before it; ("answer", reason) when no decision can be made."""
    t, name = C._talk(user, cid), (words or [face.get("name") or "the assistant"])[0]
    msgs = [m for m in t["messages"] if m["role"] in ("user", "assistant")][-int(s["recent"] or 8):]
    if not msgs: return "answer", "nothing to decide on"
    last = msgs[-1]
    text = f"""The assistant is called {name}.\n\nThe conversation (oldest first):\n""" + "\n".join(_line(m, name) for m in msgs[:-1]) + f"""\n\nJust said: {_line(last, name)}""" + ("\nIt names the assistant." if woken(last["content"], words, float(s["wake_fuzz"] or 0.75)) else "") + (f"""\nSilence since then: {pause_s:.1f} seconds.""" if pause_s else "")
    try:
        state, r = await _quiet(await C.AV.start(s["attend"] or "attend", {"input": text}, owner=user, profiles=face.get("profiles", []), pins=pins, may=C._may(request), case=face.get("case")))
        act = str(r.data.get("act") or "").strip().lower() if state == "done" else ""
        return (act, "") if act in ACTS else ("answer", f"""awareness gave no decision ({state}: {r.meta.get("error", "")}{act})""")
    except (ValueError, KeyError) as e: return "answer", f"awareness could not run: {e}"

async def _aware(request, user: str, cid: str, face: dict, spec: dict, s: dict, words: list, pins: dict, heard: str, b64: str, spk: dict):
    h = HELD.setdefault(cid, {"n": 0, "since": time.time(), "task": None})
    if h["task"]: h["task"].cancel()   # more was said: the pending decision is made with it
    h["n"] += 1
    await _said(user, cid, heard, b64, spk, "deciding ...")
    await _act_on(request, user, cid, face, spec, s, words, pins, *await _decide(request, user, cid, face, spec, s, words, pins))

async def _act_on(request, user: str, cid: str, face: dict, spec: dict, s: dict, words: list, pins: dict, act: str, why: str):
    """What a decision does: answer (an answer being written stops; the turn answers everything unanswered), wait (decided again after hold_s of silence), aside (nothing; an answer paused by it resumes)."""
    h, t = HELD.setdefault(cid, {"n": 0, "since": time.time(), "task": None}), C._talk(user, cid)
    await _verdict(user, cid, act != "aside", f"""{ACTS[act]}{" (" + why + ")" if why else ""}""")
    _mark(user, cid, ACTS[act] + (f" ({why})" if why else ""), act == "aside")
    if act == "wait" and time.time() - h["since"] < float(s["hold_max_s"] or 10):
        n = h["n"]
        async def later():
            await asyncio.sleep(float(s["hold_s"] or 2.5))
            if HELD.get(cid, {}).get("n") != n: return
            h["task"] = None
            a, w = await _decide(request, user, cid, face, spec, s, words, pins, float(s["hold_s"] or 2.5))
            await _act_on(request, user, cid, face, spec, s, words, pins, a, w)
        h["task"] = asyncio.create_task(later())
        return
    HELD.pop(cid, None)
    if act == "aside": return
    if C._working(t):
        C.AV.director.stop(t["pending"], now=True)
        await _idle(user, cid)
    asyncio.create_task(C._turn(user, C._talk(user, cid), None, C._may(request), spoken=True))

def _mark(user: str, cid: str, note: str, aside: bool = False):
    """The decision written on the newest heard message (its badge), so the conversation keeps what was decided on each utterance."""
    t = C._talk(user, cid)
    m = next((m for m in reversed(t["messages"]) if m["role"] == "user"), None)
    if not m: return
    m["badge"], m["aside"] = " - ".join(x for x in (m.get("voice_badge", ""), note) if x), aside   # who it most likely is, and the latest decision on it; an aside reaches the model marked as one
    C._talk_save(user, t)
    me = m.get("user_name") == user
    html = C._cm(t["face"]).render_message(m, is_me=me, can_edit=me, can_delete=True)
    asyncio.ensure_future(C.WS.send_personal_message(html.replace(f'''id="cm-msg-{m["id"]}"''', f'''id="cm-msg-{m["id"]}" hx-swap-oob="outerHTML"''', 1), user))   # shown with what was decided

# --- Listening: placed roles, the wake word, spoken commands ---

PLACED: dict = {}   # (face, user, role) -> (when, provider, binding): a voice role placed for direct asks (a wake check, a voiceprint, a spoken sentence), kept PLACED_S so each utterance does not place again
PLACED_S = 60.0
NO_LIGHT: dict = {}   # (provider id, recognizer) -> why that light recognizer could not be used there: not asked again until Corvid starts again

async def _placed(face: dict, user: str, role: str, need: dict, pins: dict = None) -> tuple:
    """(provider, binding) for a role asked directly rather than by a run: placed as a run's role would be (the face's profiles, its case, the conversation's pin for that role - Who answers), and kept PLACED_S."""
    pin = (pins or {}).get(role)
    k = (face["id"], user, role, json.dumps(pin, sort_keys=True))
    if not (got := PLACED.get(k)) or time.time() - got[0] > PLACED_S:
        b = await C.ROLES.place(C.AV.lib, role, need, C._cands(role, face.get("profiles", [])), pin, face.get("case") or {}, user)
        PLACED[k] = got = (time.time(), C.AV.lib.get("provider", b["provider"]), b)
    return got[1], got[2]

def _role_of(pipeline: str, role: str) -> dict: return C.AV.lib.get("pipeline", pipeline)["roles"][role]

AWAKE: dict = {}   # conversation id -> until when it is addressed (time.time()), when it listens by wake word: set by a wake word, and again by each turn heard and each answer spoken
_STOP = re.compile(r"^\W*(stop|halt|quiet|be quiet|enough|shh+|stop talking|\u505c|\u505c\u6b62|\u522b\u8bf4\u4e86|\u5b89\u9759)\W*$", re.I)   # an utterance that is only "stop" (also in Chinese): what is being said stops, and it is not a turn
_SLEEP = re.compile(r"\b(go to sleep|stop listening)\b|\u53bb\u7761\u89c9", re.I)   # with listening by wake word: not addressed again until the wake word

def _norm(x: str) -> str: return re.sub(r"[^\w]+", " ", x.lower()).strip()
def _wake_words(face: dict, s: dict) -> list: return [w.strip() for w in str(s["wake_words"] or face.get("name") or "").split(",") if w.strip()]   # none set: the face's own name
def awake(cid: str) -> bool: return AWAKE.get(cid, 0.0) > time.time()
def wake(cid: str, s: dict): AWAKE[cid] = time.time() + float(s["wake_window_s"] or 30)

def woken(text: str, words: list, fuzz: float) -> bool:
    """Whether what was heard holds a wake word: as written (also inside text with no spaces, as Chinese is), or close to it - each run of one or two more heard words than the wake word has is compared with it, spaces left out (difflib ratio, 1 = the same), so "Tess a" or "Tesa" wakes "Tessa" at 0.75."""
    heard, flat = _norm(text).split(), _norm(text).replace(" ", "")
    for w in (_norm(x) for x in words):
        if w.replace(" ", "") in flat: return True
        n = len(w.split())
        if any(difflib.SequenceMatcher(None, w.replace(" ", ""), "".join(heard[i:i + k])).ratio() >= fuzz for i in range(len(heard)) for k in (n, n + 1)): return True
    return False

def _spoken(word: str) -> str: return re.sub(r"_v?\d[\w.]*$", "", word).replace("_", " ")   # a wake word model's name as said: hey_jarvis_v0.1 -> hey jarvis

def _wake_words_offered() -> list: return sorted({(o["p"]["id"], a["name"]) for o in C._offers_now() for a in o["assets"] if "wake_detect" in (a.get("capabilities") or [])}, key=lambda x: x[1])

async def _wake_word(request, s: dict, pins: dict, b64: str) -> dict:
    """The wake word model's verdict on an utterance ({"scores", "woken"}), from a machine that has that word - the listening machine (ears pin) first."""
    have = [pid for pid, name in _wake_words_offered() if name == s["wake_word"]]
    if not have: raise ValueError(f"""no machine offers the wake word {s["wake_word"]} now""")
    pid = next((p for p in have if p == ((pins or {}).get("ears") or {}).get("provider")), have[0])
    return (await C.PROV.run(C.AV.lib.get("provider", pid), "wake_detect", {"audio_b64": b64, "words": [s["wake_word"]], "threshold": float(s["wake_threshold"] or 0.5)}))["result"]

async def _light(face: dict, user: str, spec: dict, b64: str, s: dict, words: list, pins: dict = None) -> str:
    """What the light recognizer (wake_model, quickest search) hears in an utterance, on the machine that fills the hear pipeline's ears role, told the wake words to expect. A machine without that recognizer hears it with the role's own."""
    p, b = await _placed(face, user, "ears", _role_of(spec["hear"], "ears"), pins)
    body = {"audio_b64": b64, "beam_size": 1, "initial_prompt": ", ".join(words) + ".", **({"language": s["language"]} if s["language"] else {})}
    own, light = {**body, **({"model": b["asset"]} if b.get("asset") else {})}, (p["id"], s["wake_model"])
    if not s["wake_model"] or light in NO_LIGHT: r = await C.PROV.run(p, "speech_to_text", own)
    else:
        try: r = await C.PROV.run(p, "speech_to_text", {**body, "model": s["wake_model"]})
        except C.PROV.ProviderError as e:
            NO_LIGHT[light] = str(e)
            print(f"""[CORVID] wake word: {s["wake_model"]} is not usable on {p["id"]} ({e}) - its own recognizer checks instead until Corvid starts again""", flush=True)
            r = await C.PROV.run(p, "speech_to_text", own)
    return str((r["result"] or {}).get("text") or "").strip()

# --- Who is speaking: voiceprints, per login ---
# A person is a name and a few voiceprints (speaker_embed: unit vectors, so their dot product is the cosine). An utterance is matched against every print kept; its best score says who it most likely is: "sure" at or above "match", "likely" (a ? after the name) at or above "guess", otherwise another voice. A sure match of a person with fewer than PRINTS_GROW prints adds that utterance's print to them, so recognition improves with use.

ENROLL: dict = {}   # login -> person id: that login's next utterance is a voice sample for that person, not a turn
PRINTS_GROW, SAMPLE_S = 12, 2.0

def _voices_file(user: str) -> Path: return C.DATA / "voices" / f"""{Path(user).name}.json"""
def _people(user: str) -> dict: return json.loads(f.read_text()).get("people", {}) if (f := _voices_file(user)).exists() else {}
def _people_save(user: str, people: dict):
    _voices_file(user).parent.mkdir(parents=True, exist_ok=True)
    _voices_file(user).with_suffix(".tmp").write_text(json.dumps({"people": people}))
    _voices_file(user).with_suffix(".tmp").replace(_voices_file(user))

async def _print(face: dict, user: str, spec: dict, b64: str, pins: dict = None) -> list:
    """An utterance's voiceprint, from a machine offering speaker_embed (placed as role "speakers"); else from the machine that hears, whose speech program usually offers it too."""
    try: p, _ = await _placed(face, user, "speakers", {"needs": ["speaker_embed"]}, pins)
    except ValueError: p, _ = await _placed(face, user, "ears", _role_of(spec["hear"], "ears"), pins)
    return (await C.PROV.run(p, "speaker_embed", {"audio_b64": b64}))["result"]["embedding"]

def _who(user: str, people: dict, v: list, s: dict) -> dict:
    """The person an utterance's print v most likely is: {"id", "name", "score", "sure", "mine" (this login's own voice), "said" (as the model reads it), "badge" (as the message shows it)}."""
    score, pid = max(((sum(a * b for a, b in zip(v, q)), pid) for pid, per in people.items() for q in per["prints"]), default=(0.0, ""))
    per = people.get(pid) or {"name": ""}
    sure, likely = score >= float(s["match"] or 0.5), score >= float(s["guess"] or 0.35)
    if sure and len(per["prints"]) < PRINTS_GROW: _grow(user, pid, v)
    return {"id": pid, "name": per["name"] if likely else "another voice", "score": round(score, 2), "sure": sure, "mine": bool(per.get("mine")) and sure, "said": per["name"] if sure else f"""{per["name"]}?""" if likely else "another voice", "badge": f"""voice: {per["name"]}{"" if sure else "?"} {score:.2f}""" if likely else f"""voice: not known (closest {per["name"] or "nobody"} {score:.2f})"""}

def _grow(user: str, pid: str, v: list):
    """One more print for a person, read again from the file (a person forgotten in the meantime stays forgotten)."""
    if pid in (people := _people(user)): people[pid]["prints"].append(v) or _people_save(user, people)

async def _enroll(user: str, cid: str, face: dict, spec: dict, pid: str, b64: str, imr, pins: dict = None):
    """A recorded utterance kept as a voice sample of the person being enrolled (at least SAMPLE_S long); said in the status line, never a turn."""
    if len(base64.b64decode(b64.split(",", 1)[-1])) < 44 + 32000 * SAMPLE_S: return await _verdict(user, cid, False, f"too short for a voice sample - talk for {SAMPLE_S:.0f} s or more (press Record a sample again)") or imr
    try: v = await _print(face, user, spec, b64, pins)
    except (ValueError, KeyError, C.PROV.ProviderError) as e: return await _verdict(user, cid, False, f"voice sample not kept: {e}") or imr
    people = _people(user)
    people[pid]["prints"].append(v)
    _people_save(user, people)
    await _verdict(user, cid, False, f"""voice sample kept for {people[pid]["name"]} ({len(people[pid]["prints"])} so far)""")
    return imr

async def _h_voice_person(request, payload, imr):
    """The voices told apart in this login's conversations: verb "new" (a person, then their sample), "sample" (the next utterance is one more sample of pid), "cancel" (no sample awaited), "forget" (a person and their prints - asked first)."""
    user, verb = C._user(request), payload.get("verb")
    people = _people(user)
    if verb == "new":
        if not (name := (payload.get("person_name") or "").strip()): return imr.oob(C._note("Give the person a name first.", True), "cv-voices")
        pid = next(i for i in (C._slug(name) or "voice", *(f"{C._slug(name)}-{n}" for n in range(2, 1000))) if i not in people)   # a free id: a name used twice is two people, never one replaced
        people[pid] = {"name": name, "mine": bool(payload.get("person_mine")), "prints": [], "t": time.time()}
        _people_save(user, people)
        ENROLL[user] = pid
    elif verb == "sample" and payload.get("pid") in people: ENROLL[user] = payload["pid"]
    elif verb == "cancel": ENROLL.pop(user, None)
    elif verb == "forget" and payload.get("pid") in people:
        people.pop(payload["pid"])
        _people_save(user, people)
    return imr.oob(voices_html(user, payload.get("cid", "")) + (_record_js(payload.get("cid", "")) if ENROLL.get(user) and verb in ("new", "sample") else ""), "cv-voices")

SAMPLE_REC_S = 8   # how long Record a sample listens

def _record_js(cid: str) -> str:
    """The browser records the sample at once through the conversation's own microphone (the chat's hold-to-talk, held for SAMPLE_REC_S), counting down in its status line; what it sends arrives as the awaited sample."""
    return f"""<script>(function(){{var b=document.querySelector('.cm-form[data-cm-sid="{C._esc(cid)}"] .cm-mic');if(!b||!window.cmVoice){{alert('No microphone button in this conversation: open it in Lyrebird > Talk');return;}}var n={SAMPLE_REC_S},st=document.getElementById('cm-vad-{C._esc(cid)}');cmVoice.hold(b,{{preventDefault:function(){{}}}});var t=setInterval(function(){{n--;if(st)st.textContent='recording a voice sample - keep talking ('+n+' s)';if(n<=0){{clearInterval(t);cmVoice.release(b);}}}},1000);}})();</script>"""

def voices_html(user: str, cid: str = "") -> str:
    """The people whose voices are told apart, their samples, and the next sample being awaited."""
    people, wait = _people(user), ENROLL.get(user)
    rows = "".join(f"""<div class="row"><span class="grow">{C._esc(per["name"])}{" (my voice)" if per.get("mine") else ""} <span class="cv-dim">{len(per["prints"])} sample(s)</span></span>{"<b>talk now</b>" if wait == pid else C._btn("Record a sample", "voice_person", verb="sample", pid=pid, cid=cid, title="Your next utterance (mic or call, 5-10 s of normal talk) is kept as a sample of this voice instead of being said in the conversation")}{C._btn("Forget", "voice_person", "ui-btn cv-danger", verb="forget", pid=pid, cid=cid, confirm=f"Forget the voice of {per['name']} and its samples? Their messages keep who said them.")}</div>""" for pid, per in people.items())
    new = f"""<form class="row" id="cv-voice-new" onsubmit="return false"><input name="person_name" class="module-input grow" placeholder="name"><label class="cv-dim"><input type="checkbox" name="person_mine" value="1"> my voice</label>{C._btn("Add and record", "voice_person", verb="new", cid=cid, include="#cv-voice-new")}</form>"""
    cancel = C._btn("Not now", "voice_person", verb="cancel", cid=cid) if wait else ""
    return f"""<div class="cv-sec">{rows or C._dim("No voice is known yet: add one, then talk for 5-10 s (hold the microphone, or in a call).")}{new}{f'<div class="row cv-dim">The next utterance is a voice sample. {cancel}</div>' if wait else ""}</div>"""

_MARKS = re.compile(r"```.*?```|[*_`#>|]+|\[([^\]]*)\]\([^)]*\)", re.S)   # what is written for the eye and not said: code blocks, emphasis marks, links (their words are kept)

# --- Speech settings of a conversation ---

SPEECH = {"speak": "", "while_writing": True, "voice": "", "length_scale": None, "language": "", "lang_voices": {}, "min_chars": 12, "listen": "", "wake_word": "", "wake_threshold": 0.5, "attend": "attend", "hold_s": 2.5, "hold_max_s": 10, "recent": 8, "wake_words": "", "wake_window_s": 30, "wake_model": "tiny", "wake_fuzz": 0.75, "identify": False, "match": 0.5, "guess": 0.35}   # "speak": "" = as the face says (all answers, or those to spoken words), "all", "spoken", "off"; "listen": "" = every utterance, "wake" = after a wake word
KINDS = {"lang_voices": "json", "while_writing": "checkbox", "identify": "checkbox", **{k: "number" for k in ("length_scale", "min_chars", "wake_window_s", "wake_fuzz", "match", "guess", "hold_s", "hold_max_s", "recent", "wake_threshold")}}   # how each speech setting is parsed from its form (the rest are text)
_SENT_END = re.compile(r"\n+|(?<=[.!?\u2026])[\"')\]]*[ \t]+|(?<=[\u3002\uff01\uff1f\uff1b])[\u201d\u300d\u300f\uff09]*|(?<=</lang>)")   # a line break; sentence punctuation (plus closing quotes and brackets) followed by a space; Chinese and Japanese sentence ends, which need no space; the end of a language tag
_LANG = re.compile(r"""<lang\b[^>]*?(?:code\s*=\s*)?["']?([A-Za-z]{2,3}(?:[-_][A-Za-z]{2,4})?)["']?\s*>|</lang\s*>""", re.I)   # <lang code="zh"> (also <lang zh>, <lang="zh">) and </lang>: group 1 is the code of an opening tag
_LANG_TAIL = re.compile(r"<(?:/?l(?:a(?:n(?:g[^>]*)?)?)?)?$")   # a tag still being written at the end of streamed text

def plain(text: str) -> str: return _LANG_TAIL.sub("", _LANG.sub("", text))   # an answer as shown: its language tags left out (they only choose voices)

def speech(spec: dict, t: dict) -> dict:
    """How this conversation is spoken and heard: the defaults, the face's own ("speech" in its conversation panel), then the conversation's."""
    return {**SPEECH, **(spec.get("speech") or {}), **(t.get("speech") or {})}

def speaks(spec: dict, t: dict, spoken: bool) -> bool:
    """Whether this turn's answer is spoken: the conversation's choice, else the face's (every answer with "speak_typed", otherwise answers to spoken words)."""
    how = speech(spec, t)["speak"] or ("all" if spec.get("speak_typed") else "spoken")
    return bool(spec.get("speak")) and (how == "all" or (how == "spoken" and spoken))

async def _heard_info(face: dict, user: str, pipeline: str, role: str, info: str, pins: dict = None) -> dict:
    """What the machine that fills a voice role lists of itself (its voices, the languages it hears), from what it last said; {} while that is not known. The conversation's pin for the role decides the machine, else placement."""
    pl = C.AV.lib.get("pipeline", pipeline)
    got = (pins or {}).get(role) or await C.BESIDE["needs_view"].now(pl["id"], role, pl["roles"][role], user, face.get("profiles", []))
    if not got.get("provider"): return {}
    p = C.AV.lib.get("provider", got["provider"])
    return C.AV.seen.get(f"""{p["id"]}:info:{info}""", lambda: C.PROV.machine(p, "GET", f"/info/{info}", timeout=8.0), 60.0)["value"] or {}

async def p_speech(c) -> str:
    """How the open conversation is spoken and heard: whether answers are spoken, sentence by sentence while they are written or once at the end, the voice, its pace, the language listened for, and a voice per language. The speaker button under the conversation mutes this browser without changing any of it."""
    user = C._user(c.request)
    t, spec = C._current(c.request, c.face, c.tab), C._conv_spec(c.face)
    if not spec.get("speak") and not spec.get("hear"): return C._dim("This face neither speaks nor listens.")
    s, voices, langs = speech(spec, t), await _heard_info(c.face, user, spec["speak"], "voice", "voice_list", C._pins(spec, t)) if spec.get("speak") else {}, await _heard_info(c.face, user, spec["hear"], "ears", "stt_languages", C._pins(spec, t)) if spec.get("hear") else {}
    F, as_face = C.BI.SettingField, "every answer" if spec.get("speak_typed") else "answers to spoken words"
    voice_opts = [("", f"""(the machine's own{": " + voices["default"] if voices.get("default") else ""})""")] + [(v, v) for v in voices.get("installed", [])] + ([(s["voice"], s["voice"] + " (not listed now)")] if s["voice"] and s["voice"] not in voices.get("installed", []) else [])
    lang_opts = [("", "(found by listening)")] + [(x, x) for x in langs.get("languages", [])] + ([(s["language"], s["language"])] if s["language"] and s["language"] not in langs.get("languages", []) else [])
    g = C._group([F("speak", "Speak", "select", options=[("", f"as this face does ({as_face})"), ("all", "every answer"), ("spoken", "answers to spoken words"), ("off", "nothing")]),
                  F("while_writing", "Speak while the answer is written", "checkbox", hint="Each finished sentence is spoken while the rest is still being written, and they play one after another: speech starts after the first sentence. Off: the whole answer is spoken once it is complete."),
                  F("voice", "Voice", "select", options=voice_opts, hint="The voices the speaking machine has." if voices.get("installed") else "The speaking machine has not listed its voices yet (it does once its speech program has run)."),
                  F("length_scale", "Pace (1 = the voice's own; above 1 slower)", "number", advanced=True),
                  F("language", "Language listened for", "select", options=lang_opts),
                  *(F(f"lv_{code}", f"Voice for {LANG_NAMES.get(code, code)} ({code})", "select", options=[("", "(the voice above)"), *((v, v) for v in voices.get("installed", [])), *([(s["lang_voices"][code], s["lang_voices"][code] + " (not listed now)")] if s["lang_voices"].get(code) and s["lang_voices"][code] not in voices.get("installed", []) else [])], hint="Text in this language (a <lang> tag, or its writing system) is spoken with this voice; a Kokoro voice speaks with the phonemes of its own language (zf_ Mandarin, jf_ Japanese, ef_ Spanish, ff_ French ...), a clone (Qwen3) is told the language.") for code in _lang_rows(spec, s)),
                  F("lv_new", "Another language (its code, e.g. ko, de, fil)", "text", advanced=True),
                  F("lv_new_voice", "Its voice", "select", options=[("", "-"), *((v, v) for v in voices.get("installed", []))], advanced=True),
                  F("min_chars", "Shortest piece spoken on its own (characters)", "number", step=1, advanced=True, hint="Shorter pieces (Yes. Hi!) wait for the next sentence instead of costing a request each."),
                  F("listen", "Listen to", "select", options=[("", "everything said (in a call)"), ("aware", "what is meant for it (a quick model decides each time)"), ("wake", "only after a wake word")], hint="Aware: each utterance is shown, then a quick decision model (Who answers: judge) reads it with the conversation - answer now, wait for the rest after a pause mid-thought, or leave it (people talking to each other, kept as context). Naming the assistant helps but is not needed in an ongoing exchange. " + "With a wake word, a call listens all the time but each utterance is first checked by a light recognizer; only once the wake word was heard does the full recognizer hear what is said, until the conversation has been quiet for the time below."),
                  F("attend", "Decides what is meant for it (pipeline)", "select", options=[(p["id"], p.get("name") or p["id"]) for p in C.AV.lib.list("pipeline") if any("decide" in (r.get("needs") or []) for r in (p.get("roles") or {}).values())] or [("attend", "attend")], advanced=True, hint="Its role judge is set under Who answers (a small, quick model: it is asked after every utterance); its rules are the pipeline's How to decide."),
                  F("hold_s", "Silence after an unfinished thought before deciding again (s)", "number", advanced=True),
                  F("hold_max_s", "Answer at the latest after (s of waiting)", "number", advanced=True),
                  F("recent", "Messages the decision reads", "number", step=1, advanced=True),
                  F("wake_word", "Wake word model (fast)", "select", options=[("", "none: the light recognizer checks the wake words below"), *((n, f"{_spoken(n)} ({n})") for n in sorted({n for _, n in _wake_words_offered()})), *([(s["wake_word"], s["wake_word"] + " (not offered now)")] if s["wake_word"] and s["wake_word"] not in {n for _, n in _wake_words_offered()} else [])], hint="An openWakeWord model on a speech machine: a few MB, milliseconds per utterance, and nothing else is heard until it fires. The pre-trained ones come with the speech program (Install again with wake words); one of your own (its .onnx) goes into that machine's audio_models/wakeword."),
                  F("wake_threshold", "Wake word sureness needed (0-1)", "number", advanced=True, hint="0.5 is openWakeWord's usual; lower wakes more easily (and more often by mistake). Each utterance's score shows in the status line."),
                  F("wake_words", "Wake words (comma-separated; empty: this face's name)", "text", hint="Add the ways the recognizer mishears the name, e.g. Tessa, Tesa, Tess."),
                  F("wake_window_s", "Stay addressed for (s after a wake word, a turn or an answer)", "number", step=1),
                  F("wake_model", "Light recognizer for the wake word", "select", options=_recognizers(s["wake_model"]), advanced=True, hint="A recognizer the machines offer (the smallest is quickest: tiny, base); none listed: fetch one (Settings, download a whole folder, e.g. Systran/faster-whisper-tiny into audio_models / whisper). Not on the listening machine: its own recognizer checks instead (slower)."),
                  F("wake_fuzz", "Wake word closeness (0-1, 1 = exact)", "number", advanced=True),
                  F("identify", "Tell voices apart", "checkbox", hint="Each spoken message says who it most likely is, with how sure (voice: name 0.72); the model reads it as (name): ... Voices are added below."),
                  F("match", "Same person at or above (0-1)", "number", advanced=True, hint="The same voice usually scores 0.6-0.8, different voices under 0.3."),
                  F("guess", "Likely the person at or above (0-1)", "number", advanced=True, hint="Between this and the line above the name gets a ? for the model.")])
    return f"""<form class="cv-form" id="cv-speech-f" onsubmit="return false">{g.render({**s, **{f"lv_{k}": v for k, v in (s["lang_voices"] or {}).items()}})}<div class="row"><span class="grow"></span>{C._btn("Save", "speech_save", face=c.face["id"], cid=t["id"], include="#cv-speech-f")}</div></form>{C._dim("Every spoken answer keeps its recording: the player on the answer plays it again. The speaker button under the conversation mutes speech in this browser. Saying only stop stops what is being said; with a wake word, go to sleep stops listening.")}<b>Voices told apart</b><div id="cv-voices">{voices_html(user, t["id"])}</div>"""

def _recognizers(now: str) -> list:
    """Every speech-to-text model the machines offer, by name (smallest names first is not known, so in name order), with the conversation's own choice kept even when no machine lists it now."""
    names = sorted({a["name"] for o in C._offers_now() for a in o["assets"] if "speech_to_text" in (a.get("capabilities") or [])})
    return [("", "(the listening machine's own)"), *((n, n) for n in names), *([(now, now + " (not listed now)")] if now and now not in names else [])]

LANG_NAMES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "hi": "Hindi", "fil": "Tagalog"}
LANGS_SHOWN = ["en", "zh", "ja", "ko", "es", "fr"]   # the languages offered a voice of their own; a face's speech "languages" replaces them, and any language given one stays shown

def _lang_rows(spec: dict, s: dict) -> list: return list(dict.fromkeys([*((spec.get("speech") or {}).get("languages") or LANGS_SHOWN), *(s["lang_voices"] or {})]))

async def _h_speech_save(request, payload, imr):
    user = C._user(request)
    t = C._talk(user, payload["cid"])
    spec = C._conv_spec(C.AV.lib.get("face", payload["face"]))
    got = C._group([C.BI.SettingField(k, k, KINDS.get(k, "text")) for k in SPEECH if k != "lang_voices"]).parse(payload)
    got["lang_voices"] = {**{c: payload[f"lv_{c}"] for c in _lang_rows(spec, speech(spec, t)) if payload.get(f"lv_{c}")}, **({payload["lv_new"].strip().lower(): payload["lv_new_voice"]} if (payload.get("lv_new") or "").strip() and payload.get("lv_new_voice") else {})}   # one choice per language; an emptied one goes back to the voice above
    C._talk_save(user, {**t, "speech": {k: v for k, v in got.items() if v != SPEECH[k]}})
    return await C._refresh(request, imr, payload["face"], C._note("Saved: it holds from the next answer."))

# --- Speaking an answer ---

def _script_lang(text: str) -> str:
    """A language code from the writing system when Chinese characters, kana or hangul make up at least half the letters (kana -> ja, hangul -> ko, characters alone -> zh); "" for anything else."""
    letters = len(re.findall(r"[^\W\d_]", text)) or 1
    cjk, kana, hangul = (len(re.findall(r, text)) for r in (r"[\u4e00-\u9fff]", r"[\u3040-\u30ff]", r"[\uac00-\ud7af\u1100-\u11ff]"))
    return "ko" if hangul * 2 >= letters else ("ja" if kana else "zh") if (cjk + kana) * 2 >= letters else ""

def _join_wavs(segments: list) -> str:
    """WAV recordings (base64) joined into one, for playing an answer again; one whose format differs from the first is left out."""
    out, first = io.BytesIO(), None
    with wave.open(out, "wb") as w:
        for b in segments:
            with wave.open(io.BytesIO(base64.b64decode(b.split(",", 1)[-1]))) as r:
                if first is None: first = r.getparams()[:3]; w.setparams(r.getparams())
                if r.getparams()[:3] == first: w.writeframes(r.readframes(r.getnframes()))
    return base64.b64encode(out.getvalue()).decode() if first else ""

class Speaker:
    """An answer spoken while it is written. Text is gathered until a sentence ends; each finished sentence goes to the voice at once - one request at a time, in order - and its recording is sent to the conversation in the browser (a cm-voice-audio trigger {sid, turn, seq, audio_b64, format, text, lang, last}), where the portal's chat interface queues them by seq and plays them back to back, with captions. A sentence that could not be spoken is sent without sound, so the order never stalls. With "while_writing" off the whole answer is one piece. The recordings are also joined into one for the answer's player."""
    def __init__(self, user: str, t: dict, face: dict, spec: dict, turn: str, may: list):
        self.user, self.cid, self.face, self.spec, self.turn, self.may, self.s, self.pins = user, t["id"], face, spec, turn, may, speech(spec, t), C._pins(spec, t)
        self.buf, self.fed, self.seq, self.audio, self.q, self.failed, self.tag = "", False, 0, [], asyncio.Queue(), "", ""   # tag: the language a <lang> tag opened and has not closed yet (it may span sentences)
        self.worker = asyncio.ensure_future(self._work())

    def feed(self, text: str):
        self.fed, self.buf = True, self.buf + text
        if not self.s["while_writing"]: return
        n = int(self.s["min_chars"] or 0)
        while len(self.buf) > n and (m := _SENT_END.search(self.buf, n)): self.q.put_nowait(self.buf[:m.end()]); self.buf = self.buf[m.end():]   # a piece ends only past min_chars

    async def close(self, full: str = "") -> str:
        """Speaks what is left (the whole answer, when none of it came while it was written), waits for every piece, and answers the joined recording (base64 WAV, "" when nothing was spoken)."""
        if not self.fed: self.buf = full
        if self.buf.strip(): self.q.put_nowait(self.buf)
        self.q.put_nowait(None)
        await self.worker
        await self._push({"seq": self.seq, "last": True})
        return _join_wavs(self.audio)

    def cancel(self): self.worker.cancel()

    async def _push(self, detail: dict): await C.ENV["push_to_client"](self.user, {"t": "trigger", "event": "cm-voice-audio", "detail": {"sid": self.cid, "turn": self.turn, **detail}})

    def _runs(self, text: str) -> list:
        """A piece as (text, language) runs: the language tags it opens and closes (carried over to the next piece while open), else the language of its writing system."""
        out, at = [], 0
        for m in _LANG.finditer(text):
            out.append((text[at:m.start()], self.tag))
            self.tag, at = (m.group(1) or "").lower().replace("_", "-"), m.end()
        out.append((text[at:], self.tag))
        return [(x, lang or _script_lang(x)) for x, lang in out]

    def _voice_of(self, lang: str) -> str:
        """The voice for a language: its own (lang_voices, by the full code or its first part: zh-CN -> zh), else the conversation's voice."""
        lv = self.s["lang_voices"] or {}
        return lv.get(lang) or lv.get(lang.split("-")[0]) or self.s["voice"] or ""

    async def _work(self):
        while (text := await self.q.get()) is not None:
            for run, lang in self._runs(text):
                said = _MARKS.sub(lambda m: m.group(1) or "", run).strip()
                if not re.sub(r"[^\w']+", "", said): continue   # marks and punctuation alone: nothing to say
                try:
                    p, b = await _placed(self.face, self.user, "voice", _role_of(self.spec["speak"], "voice"), self.pins)
                    r = (await C.PROV.run(p, "text_to_speech", {k: v for k, v in {**(b.get("body") or {}), "model": b.get("asset", ""), "text": said, "voice": self._voice_of(lang) or None, "language": lang or None, "length_scale": self.s["length_scale"]}.items() if v not in (None, "")}))["result"] or {}
                    self.audio.append(r["audio_b64"])
                    await self._push({"seq": self.seq, "audio_b64": r["audio_b64"], "format": r.get("format") or "wav", "text": said, "lang": lang, "voice": self._voice_of(lang)})
                except (ValueError, KeyError, C.PROV.ProviderError) as e:
                    self.failed = self.failed or str(e)
                    await self._push({"seq": self.seq, "audio_b64": "", "text": said, "lang": lang, "voice": self._voice_of(lang), "error": str(e)})
                self.seq += 1

async def spoken(user: str, t: dict, mid: str, sp: Speaker, text: str):
    """After a spoken answer joined the conversation: what is left is said, the joined recording is kept on the message (its player plays it again; nothing plays twice), and a failure is said in the conversation."""
    joined = await sp.close(text)
    if speech(sp.spec, t)["listen"] == "wake": wake(t["id"], speech(sp.spec, t))   # an answer just spoken: the person may answer it without the wake word
    if sp.failed: await C.WS.send_personal_message(C._note_oob(f"Not all of it was spoken: {sp.failed}"), user)
    if not joined: return
    url, t = _keep_audio(user, f"{mid}.wav", joined), C._talk(user, t["id"])
    for m in t["messages"]:
        if m["id"] == mid: m["audio"] = {"url": url}
    C._talk_save(user, t)
    m = next(m for m in t["messages"] if m["id"] == mid)
    await C.WS.send_personal_message(C._cm(t["face"]).render_message({**m, "audio": {"url": url, "autoplay": False}}).replace(f"""id="cm-msg-{mid}" """, f"""id="cm-msg-{mid}" hx-swap-oob="outerHTML" """, 1), user)

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_speech_save": [_h_speech_save], "corvid_voice_person": [_h_voice_person]})
    C.IM.scripts["corvid_audio"] = [h_audio]   # the chat interface's microphone posts here (ChatManager audio_intent); corvid.py routes /media and /audio to the functions above
