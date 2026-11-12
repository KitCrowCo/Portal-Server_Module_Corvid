"""media.py - Corvid's media parts, beside corvid.py: made files shown in the portal's image gallery (one per space), and voice in conversations.
Voice is two pipelines a face's conversation panel names: "hear" (a recording to words) before a turn, "speak" (words to a recording) after it. The chat's microphone is the portal chat interface's own (hold to talk, call mode); a face turns it on with "chat": {"voice": true}.
C is a live view of corvid.py's globals, set when Corvid starts."""
import base64, asyncio, re
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

async def h_audio(request, payload, imr):
    """The chat's microphone: {cid, audio_b64 = WAV data URL}. The face's "hear" pipeline turns it into words; nothing heard resumes a reply the utterance paused (cm-voice trigger, heard=false). What was heard is said in the conversation like typed words, with the recording kept on the message, and the turn's answer is spoken."""
    user, cid, b64 = C._user(request), payload.get("cid", ""), payload.get("audio_b64", "")
    t = C._talk(user, cid)
    face, spec = C.AV.lib.get("face", t["face"]), C._conv_spec(C.AV.lib.get("face", t["face"]))
    if not b64 or not spec.get("hear") or C._working(t): return imr
    try: state, r = await _quiet(await C.AV.start(spec["hear"], {"audio_b64": b64}, owner=user, profiles=face.get("profiles", []), may=C._may(request), case=face.get("case")))
    except ValueError as e: state, r = "unplaced", type("R", (), {"data": {}, "meta": {"error": str(e)}})()
    heard = (r.data.get("text") or "").strip() if state == "done" else ""
    await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cm-voice", "detail": {"sid": cid, "heard": bool(heard)}})
    if not heard: return imr.oob(C._note("Nothing was heard." if state == "done" else f"""Not heard: the listening run is {state}. {r.meta.get("error", "")}""", state != "done"), "cv-msg")
    mine = C._msg("user", heard, user_name=user)
    mine["audio"] = {"url": _keep_audio(user, mine["id"] + ".wav", b64)}
    await C.WS.send_personal_message(C._take(user, t, mine), user)
    asyncio.create_task(C._turn(user, C._talk(user, cid), False, C._may(request), spoken=True))
    return imr

_MARKS = re.compile(r"```.*?```|[*_`#>|]+|\[([^\]]*)\]\([^)]*\)", re.S)   # what is written for the eye and not said: code blocks, emphasis marks, links (their words are kept)

async def say(user: str, t: dict, mid: str, text: str, may: list):
    """The face's "speak" pipeline says an answer; the recording joins the message, and the copy pushed now plays at once."""
    face = C.AV.lib.get("face", t["face"])
    spec = C._conv_spec(face)
    try: state, r = await _quiet(await C.AV.start(spec["speak"], {"text": _MARKS.sub(lambda m: m.group(1) or "", text).strip() or "..."}, owner=user, profiles=face.get("profiles", []), may=may, case=face.get("case")))
    except ValueError as e: return await C.WS.send_personal_message(C._note_oob(f"Not spoken: {e}"), user)
    if state != "done" or not r.data.get("audio_b64"): return await C.WS.send_personal_message(C._note_oob(f"""Not spoken: the speaking run is {state}. {r.meta.get("error", "")}"""), user)
    url = _keep_audio(user, f"""{mid}.{r.data.get("format") or "wav"}""", r.data["audio_b64"])
    t = C._talk(user, t["id"])
    for m in t["messages"]:
        if m["id"] == mid: m["audio"] = {"url": url}
    C._talk_save(user, t)
    m = next(m for m in t["messages"] if m["id"] == mid)
    html = C._cm(t["face"]).render_message({**m, "audio": {"url": url, "autoplay": True}}).replace(f"""id="cm-msg-{mid}" """, f"""id="cm-msg-{mid}" hx-swap-oob="outerHTML" """, 1)
    await C.WS.send_personal_message(html, user)

def init(c):
    global C
    C = c
    C.IM.scripts["corvid_audio"] = [h_audio]   # the chat interface's microphone posts here (ChatManager audio_intent); corvid.py routes /media and /audio to the functions above
