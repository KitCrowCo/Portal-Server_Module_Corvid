"""media.py - Corvid's media parts, beside corvid.py: made files shown in the portal's image gallery (one per space), and voice in conversations.
Voice is two pipelines a face's conversation panel names: "hear" (a recording to words) before a turn, and "speak", whose voice says the answer sentence by sentence while it is written (Speaker). How a conversation is spoken and heard is its own (panel "speech"). The chat's microphone is the portal chat interface's own (hold to talk, call mode); a face turns it on with "chat": {"voice": true}.
C is a live view of corvid.py's globals, set when Corvid starts."""
import io, re, wave, base64, asyncio
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
    """A message as the model that answers reads it: its words, the text of its attached files (each up to FILE_CHARS), and what was read in its pictures."""
    d, parts = _files_dir(user, cid), [str(m.get("content") or "")]
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

async def h_audio(request, payload, imr):
    """The chat's microphone: {cid, audio_b64 = WAV data URL}. The face's "hear" pipeline turns it into words; nothing heard resumes a reply the utterance paused (cm-voice trigger, heard=false). What was heard is said in the conversation like typed words, with the recording kept on the message, and the turn's answer is spoken."""
    user, cid, b64 = C._user(request), payload.get("cid", ""), payload.get("audio_b64", "")
    t = C._talk(user, cid)
    face, spec = C.AV.lib.get("face", t["face"]), C._conv_spec(C.AV.lib.get("face", t["face"]))
    if not b64 or not spec.get("hear") or C._working(t): return imr
    try: state, r = await _quiet(await C.AV.start(spec["hear"], {"audio_b64": b64, **({"language": lang} if (lang := speech(spec, t)["language"]) else {})}, owner=user, profiles=face.get("profiles", []), may=C._may(request), case=face.get("case")))
    except ValueError as e: state, r = "unplaced", type("R", (), {"data": {}, "meta": {"error": str(e)}})()
    heard = (r.data.get("text") or "").strip() if state == "done" else ""
    await C.ENV["push_to_client"](user, {"t": "trigger", "event": "cm-voice", "detail": {"sid": cid, "heard": bool(heard)}})
    if not heard: return imr.raw(C._chat_note(cid, C._esc("Nothing was heard." if state == "done" else f"""Not heard: the listening run is {state}. {r.meta.get("error", "")}""")))   # said in the conversation itself: a face that is a conversation alone has no other place for it
    mine = C._msg("user", heard, user_name=user)
    mine["audio"] = {"url": _keep_audio(user, mine["id"] + ".wav", b64)}
    await C.WS.send_personal_message(C._take(user, t, mine), user)
    asyncio.create_task(C._turn(user, C._talk(user, cid), False, C._may(request), spoken=True))
    return imr

_MARKS = re.compile(r"```.*?```|[*_`#>|]+|\[([^\]]*)\]\([^)]*\)", re.S)   # what is written for the eye and not said: code blocks, emphasis marks, links (their words are kept)

# --- Speech settings of a conversation ---

SPEECH = {"speak": "", "while_writing": True, "voice": "", "length_scale": None, "language": "", "lang_voices": {}, "min_chars": 12}   # "speak": "" = as the face says (all answers, or those to spoken words), "all", "spoken", "off"
_SENT_END = re.compile(r"\n+|(?<=[.!?\u2026])[\"')\]]*[ \t]+")   # a line break, or sentence punctuation (plus closing quotes and brackets) followed by a space

def speech(spec: dict, t: dict) -> dict:
    """How this conversation is spoken and heard: the defaults, the face's own ("speech" in its conversation panel), then the conversation's."""
    return {**SPEECH, **(spec.get("speech") or {}), **(t.get("speech") or {})}

def speaks(spec: dict, t: dict, spoken: bool) -> bool:
    """Whether this turn's answer is spoken: the conversation's choice, else the face's (every answer with "speak_typed", otherwise answers to spoken words)."""
    how = speech(spec, t)["speak"] or ("all" if spec.get("speak_typed") else "spoken")
    return bool(spec.get("speak")) and (how == "all" or (how == "spoken" and spoken))

async def _heard_info(face: dict, user: str, pipeline: str, role: str, info: str) -> dict:
    """What the machine that would fill a voice role lists of itself (its voices, the languages it hears), from what it last said; {} while that is not known."""
    pl = C.AV.lib.get("pipeline", pipeline)
    got = await C.BESIDE["needs_view"].now(pl["id"], role, pl["roles"][role], user, face.get("profiles", []))
    if not got.get("provider"): return {}
    p = C.AV.lib.get("provider", got["provider"])
    return C.AV.seen.get(f"""{p["id"]}:info:{info}""", lambda: C.PROV.machine(p, "GET", f"/info/{info}", timeout=8.0), 60.0)["value"] or {}

async def p_speech(c) -> str:
    """How the open conversation is spoken and heard: whether answers are spoken, sentence by sentence while they are written or once at the end, the voice, its pace, the language listened for, and a voice per language. The speaker button under the conversation mutes this browser without changing any of it."""
    user = C._user(c.request)
    t, spec = C._current(c.request, c.face, c.tab), C._conv_spec(c.face)
    if not spec.get("speak") and not spec.get("hear"): return C._dim("This face neither speaks nor listens.")
    s, voices, langs = speech(spec, t), await _heard_info(c.face, user, spec["speak"], "voice", "voice_list") if spec.get("speak") else {}, await _heard_info(c.face, user, spec["hear"], "ears", "stt_languages") if spec.get("hear") else {}
    F, as_face = C.BI.SettingField, "every answer" if spec.get("speak_typed") else "answers to spoken words"
    voice_opts = [("", f"""(the machine's own{": " + voices["default"] if voices.get("default") else ""})""")] + [(v, v) for v in voices.get("installed", [])] + ([(s["voice"], s["voice"] + " (not listed now)")] if s["voice"] and s["voice"] not in voices.get("installed", []) else [])
    lang_opts = [("", "(found by listening)")] + [(x, x) for x in langs.get("languages", [])] + ([(s["language"], s["language"])] if s["language"] and s["language"] not in langs.get("languages", []) else [])
    g = C._group([F("speak", "Speak", "select", options=[("", f"as this face does ({as_face})"), ("all", "every answer"), ("spoken", "answers to spoken words"), ("off", "nothing")]),
                  F("while_writing", "Speak while the answer is written", "checkbox", hint="Each finished sentence is spoken while the rest is still being written, and they play one after another: speech starts after the first sentence. Off: the whole answer is spoken once it is complete."),
                  F("voice", "Voice", "select", options=voice_opts, hint="The voices the speaking machine has." if voices.get("installed") else "The speaking machine has not listed its voices yet (it does once its speech program has run)."),
                  F("length_scale", "Pace (1 = the voice's own; above 1 slower)", "number", advanced=True),
                  F("language", "Language listened for", "select", options=lang_opts),
                  F("lang_voices", "Voice per language (JSON: code -> voice)", "json", advanced=True, hint='For example {"es": "es_MX-claude-high", "zh": "zh_CN-huayan-medium"}. A sentence written in another writing system (Chinese, Japanese, Korean) is spoken with that language\'s voice.'),
                  F("min_chars", "Shortest piece spoken on its own (characters)", "number", step=1, advanced=True, hint="Shorter pieces (Yes. Hi!) wait for the next sentence instead of costing a request each.")])
    return f"""<form class="cv-form" id="cv-speech-f" onsubmit="return false">{g.render(s)}<div class="row"><span class="grow"></span>{C._btn("Save", "speech_save", face=c.face["id"], cid=t["id"], include="#cv-speech-f")}</div></form>{C._dim("Every spoken answer keeps its recording: the player on the answer plays it again. The speaker button under the conversation mutes speech in this browser.")}"""

async def _h_speech_save(request, payload, imr):
    user = C._user(request)
    t = C._talk(user, payload["cid"])
    got = C._group([C.BI.SettingField(k, k, "json" if k == "lang_voices" else "checkbox" if k == "while_writing" else "number" if k in ("length_scale", "min_chars") else "text") for k in SPEECH]).parse(payload)
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
        self.user, self.cid, self.face, self.spec, self.turn, self.may, self.s = user, t["id"], face, spec, turn, may, speech(spec, t)
        self.buf, self.fed, self.seq, self.audio, self.q, self.bound, self.failed = "", False, 0, [], asyncio.Queue(), None, ""
        self.worker = asyncio.ensure_future(self._work())

    def feed(self, text: str):
        self.fed, self.buf = True, self.buf + text
        if not self.s["while_writing"]: return
        n = int(self.s["min_chars"] or 0)
        while (m := _SENT_END.search(self.buf, n if len(self.buf) > n else len(self.buf))): self.q.put_nowait(self.buf[:m.end()]); self.buf = self.buf[m.end():]

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

    async def _voice(self) -> tuple:
        """(provider, the role as placed) for the face's speaking pipeline: placed once for the answer, as any run of it would be."""
        if not self.bound:
            pl = C.AV.lib.get("pipeline", self.spec["speak"])
            b = await C.ROLES.place(C.AV.lib, "voice", pl["roles"]["voice"], C._cands("voice", self.face.get("profiles", [])), None, self.face.get("case") or {}, self.user)
            self.bound = (C.AV.lib.get("provider", b["provider"]), b)
        return self.bound

    async def _work(self):
        while (text := await self.q.get()) is not None:
            said = _MARKS.sub(lambda m: m.group(1) or "", text).strip()
            if not re.sub(r"[^\w']+", "", said): continue   # marks and punctuation alone: nothing to say
            lang = _script_lang(said)
            try:
                p, b = await self._voice()
                r = (await C.PROV.run(p, "text_to_speech", {k: v for k, v in {**(b.get("body") or {}), "model": b.get("asset", ""), "text": said, "voice": (self.s["lang_voices"] or {}).get(lang) or self.s["voice"] or None, "length_scale": self.s["length_scale"]}.items() if v not in (None, "")}))["result"] or {}
                self.audio.append(r["audio_b64"])
                await self._push({"seq": self.seq, "audio_b64": r["audio_b64"], "format": r.get("format") or "wav", "text": said, "lang": lang})
            except (ValueError, KeyError, C.PROV.ProviderError) as e:
                self.failed = self.failed or str(e)
                await self._push({"seq": self.seq, "audio_b64": "", "text": said, "lang": lang, "error": str(e)})
            self.seq += 1

async def spoken(user: str, t: dict, mid: str, sp: Speaker, text: str):
    """After a spoken answer joined the conversation: what is left is said, the joined recording is kept on the message (its player plays it again; nothing plays twice), and a failure is said in the conversation."""
    joined = await sp.close(text)
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
    C.IM.scripts.update({"corvid_speech_save": [_h_speech_save]})
    C.IM.scripts["corvid_audio"] = [h_audio]   # the chat interface's microphone posts here (ChatManager audio_intent); corvid.py routes /media and /audio to the functions above
