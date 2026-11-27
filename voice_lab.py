"""voice_lab.py - Lyrebird's lab: say a text with any voice of any machine and hear the takes side by side; hear a recording (the microphone or a file) with any recognizer and see what it made of it; make a voice from a recording. Every take and hearing is kept with the settings that made it, so the same text can be said again with one setting changed.
Each machine is asked directly (its text_to_speech, speech_to_text, voice_clone_add), with what it lists of itself (GET /info/voice_list) for the choices. Kept per login: Corvid data voice_lab/<login>.json, the sound files beside the conversations' (media._audio_dir, names lab-...).
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import json, time, base64, secrets
from pathlib import Path

C = None
KEEP = 60   # takes and hearings shown (older ones stay in the file until deleted)

def init(c):
    global C
    C = c
    C.IM.scripts.update({f"corvid_lab_{k}": [f] for k, f in {"say": _h_say, "hear": _h_hear, "clone": _h_clone, "form": _h_form, "drop": _h_drop, "start": _h_start}.items()})

# --- Kept per login ---

def _file(user: str) -> Path: return C.DATA / "voice_lab" / f"""{Path(user).name}.json"""
def _load(user: str) -> dict: return {"takes": [], "hears": [], "say": {}, "hear": {}, "clone": {}, **(json.loads(f.read_text()) if (f := _file(user)).exists() else {})}
def _save(user: str, d: dict):
    _file(user).parent.mkdir(parents=True, exist_ok=True)
    _file(user).with_suffix(".tmp").write_text(json.dumps(d))
    _file(user).with_suffix(".tmp").replace(_file(user))

# --- What the machines offer ---

def _machines(request, cap: str) -> list:
    """[(provider, [its assets that do cap])] for every machine offering cap to this person."""
    return [(o["p"], [a for a in o["assets"] if cap in (a.get("capabilities") or [])]) for o in C._mine(request, C._offers_now()) if any(cap in (a.get("capabilities") or []) for a in o["assets"])]

def _voices(p: dict) -> dict:
    """What a machine says of its voices (installed, default, engines, languages, a note when its speech program has not run), from what it last said."""
    return C.AV.seen.get(f"""{p["id"]}:info:voice_list""", lambda: C.PROV.machine(p, "GET", "/info/voice_list", timeout=8.0), 60.0)["value"] or {}

def _id() -> str: return f"""{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(3)}"""   # a take's or hearing's id, also its sound file's name
def _sel(name: str, pairs: list, on, act: str = "") -> str: return f"""<select name="{name}" class="module-select" {act}>{C._options(pairs, on)}</select>"""
def _langs() -> list: return [("", "(found from the text or by listening)"), *((k, f"{v} ({k})") for k, v in C.MEDIA.LANG_NAMES.items())]
def _num(name: str, v, step: str, title: str) -> str: return f"""<input type="number" name="{name}" class="module-input" step="{step}" value="{C._esc("" if v is None else str(v))}" title="{C._esc(title)}" style="width:6em">"""

# --- The page ---

async def p_lab(c) -> str:
    user = C._user(c.request)
    d = _load(user)
    return f"""<div class="cv-sec"><b>Say</b><div id="cv-lab-say">{_say_form(c.request, d["say"])}</div><div id="cv-lab-takes">{_takes(d)}</div></div><div class="cv-sec"><b>Hear</b><div id="cv-lab-hear">{_hear_form(c.request, d["hear"])}</div><div id="cv-lab-hears">{_hears(d)}</div></div><div class="cv-sec"><b>Make a voice from a recording</b><div id="cv-lab-clone">{_clone_form(c.request, d)}</div></div>{LAB_JS}"""

def _say_form(request, f: dict) -> str:
    ms = _machines(request, "text_to_speech")
    if not ms: return C._dim("No machine offers speaking yet: install a speech program on one (Settings > Machines > its programs).")
    p, assets = next(((p, a) for p, a in ms if p["id"] == f.get("pid")), ms[0])
    v = _voices(p)
    note = f"""<div class="row cv-dim"><span class="grow">{C._esc(v.get("note") or "This machine has not listed its voices yet.")}</span>{C._btn("Start its speech program", "lab_start", pid=p["id"])}</div>""" if not v.get("installed") else ""
    voices = [("", f"""(its default{": " + v["default"] if v.get("default") else ""})"""), *((x, x) for x in v.get("installed", []))]
    change = C._act("lab_form", part="say", include="#cv-lab-say-f") + ' hx-trigger="change"'
    return f"""<form id="cv-lab-say-f" class="cv-form" onsubmit="return false"><textarea name="text" class="module-input" rows="3" style="width:100%" placeholder="what to say">{C._esc(f.get("text", ""))}</textarea>
        <div class="row" style="flex-wrap:wrap"><label>machine {_sel("pid", [(q["id"], q.get("name") or q["id"]) for q, _ in ms], p["id"], change)}</label><label>model {_sel("model", [(a["name"], a["name"]) for a in assets], f.get("model"))}</label><label>voice {_sel("voice", voices, f.get("voice"))}</label><input name="voice_id" class="module-input" value="{C._esc(f.get("voice_id", ""))}" placeholder="or a voice id" title="Any voice the machine has, typed (engine:name, e.g. kokoro:zf_xiaoxiao, qwen3:sky); used instead of the choice"></div>
        <div class="row" style="flex-wrap:wrap"><label>language {_sel("language", _langs(), f.get("language", ""))}</label><label>slower (1 = as made) {_num("length_scale", f.get("length_scale"), "0.05", "Above 1 slower, below 1 quicker; empty: the voice's own pace. Some voices refuse it (they say so).")}</label><span class="grow"></span>{C._btn("Say", "lab_say", include="#cv-lab-say-f")}</div>{note}</form>"""

def _player(name: str) -> str: return f"""<audio controls preload="none" src="{C._P}/audio/{C._esc(name)}"></audio>"""

def _takes(d: dict) -> str:
    rows = "".join(f"""<div class="list-row"><div class="row" style="flex-wrap:wrap">{_player(k["file"]) if k.get("file") else ""}<span class="grow cv-dim">{C._esc(k.get("voice") or "its default")} {C._esc(k.get("language") or "")} {"slower " + C._esc(str(k["length_scale"])) if k.get("length_scale") not in (None, "") else ""} on {C._esc(k.get("machine", ""))} - {k.get("secs", "?")} s of sound in {k.get("took", "?")} s</span>{C._btn("Again", "lab_say", again=k["id"], title="Say it again with exactly these settings")}{C._btn("Into the form", "lab_form", part="say", take=k["id"], title="Put this take's text and settings in the form, to change one thing")}{C._btn("Voice from this", "lab_form", part="clone", take=k["id"], title="Make a voice from this take (its words are known exactly): e.g. an English voice's take, made into a clone that then speaks Chinese in the same voice") if k.get("file") else ""}{C._btn("&#x2715;", "lab_drop", "ui-btn cv-small", kind="takes", id=k["id"], title="Delete this take and its sound file")}</div><div class="pre-wrap">{C._esc(k["text"])}</div>{C._note(C._esc(k["error"]), True) if k.get("error") else ""}</div>""" for k in d["takes"][:KEEP])
    return rows or C._dim("Takes appear here, newest first, each with what made it.")

def _hear_form(request, f: dict) -> str:
    ms = _machines(request, "speech_to_text")
    if not ms: return C._dim("No machine offers listening yet: install a speech program with a recognizer on one.")
    p, assets = next(((p, a) for p, a in ms if p["id"] == f.get("pid")), ms[0])
    change = C._act("lab_form", part="hear", include="#cv-lab-hear-f") + ' hx-trigger="change"'
    return f"""<form id="cv-lab-hear-f" class="cv-form" onsubmit="return false"><div class="row" style="flex-wrap:wrap"><button type="button" class="ui-btn" onpointerdown="cvLab.rec(this)" title="Press to start recording, press again to stop: the recording is then heard with the settings below">&#x1F3A4; Record</button><label class="ui-btn">&#x1F4C2; A sound file<input type="file" accept="audio/*" style="display:none" onchange="cvLab.file(this)"></label><span class="cv-dim grow" id="cv-lab-rec-state"></span>{C._btn("Hear the last one again", "lab_hear", include="#cv-lab-hear-f", again="1", title="The last recording, heard with the settings as they are now")}{C._btn("With every recognizer here", "lab_hear", include="#cv-lab-hear-f", again="1", every="1", title="The last recording, heard by each recognizer this machine has, one after another")}{C._btn("Wake word scores", "lab_hear", include="#cv-lab-hear-f", again="1", wake="1", title="How sure each wake word model (openWakeWord) is that the last recording holds its word: say the word, then this, to find the sureness to ask for") if _machines(request, "wake_detect") else ""}</div>
        <div class="row" style="flex-wrap:wrap"><label>machine {_sel("pid", [(q["id"], q.get("name") or q["id"]) for q, _ in ms], p["id"], change)}</label><label>recognizer {_sel("model", [(a["name"], a["name"]) for a in assets], f.get("model"))}</label><label>language {_sel("language", _langs(), f.get("language", ""))}</label><label>search width {_num("beam_size", f.get("beam_size", 5), "1", "Beam size: 1 is quickest, 5 the recognizers' usual")}</label><label><input type="checkbox" name="vad_filter" value="1"{" checked" if f.get("vad_filter", True) else ""}> skip silence</label><input name="initial_prompt" class="module-input grow" value="{C._esc(f.get("initial_prompt", ""))}" placeholder="words to expect (names, terms)" title="Given to the recognizer as text that came before: it spells these as written"></div></form>"""

def _hears(d: dict) -> str:
    def more(h): return f"""<details><summary class="cv-dim">pieces, with how sure (log probability; silence chance)</summary>{seg(h)}</details>""" if h.get("segments") else ""
    seg = lambda h: "".join(f"""<div class="cv-dim mono">{s["start"]:.1f}-{s["end"]:.1f} s ({s.get("avg_logprob", 0):.2f}, silence {s.get("no_speech_prob", 0):.2f}) {C._esc(s["text"])}</div>""" for s in h.get("segments") or [])
    rows = "".join(f"""<div class="list-row"><div class="row" style="flex-wrap:wrap">{_player(h["file"]) if h.get("file") else ""}<span class="grow cv-dim">{C._esc(h.get("model") or "")} on {C._esc(h.get("machine", ""))}: {C._esc(h.get("language") or "?")} ({h.get("language_probability", "?")}), {h.get("duration_s", "?")} s heard in {h.get("elapsed_s", "?")} s</span>{C._btn("&#x2715;", "lab_drop", "ui-btn cv-small", kind="hears", id=h["id"], title="Delete this hearing (its recording stays while another hearing uses it)")}</div><div class="pre-wrap"><b>{C._esc(h.get("text") or "")}</b></div>{more(h)}{C._note(C._esc(h["error"]), True) if h.get("error") else ""}</div>""" for h in d["hears"][:KEEP])
    return rows or C._dim("Record or pick a sound file: what each recognizer heard appears here, newest first.")

def _source(d: dict):
    """What a voice is made from: the take chosen (Voice from this), else the newest hearing's recording; None before either."""
    take = next((k for k in d["takes"] if k["id"] == d["clone"].get("take") and k.get("file")), None)
    return {**take, "take": True} if take else next((h for h in d["hears"] if h.get("file")), None)

def _clone_form(request, d: dict) -> str:
    ms = _machines(request, "voice_clone_add")
    if not ms: return C._dim("No machine makes voices yet: install the speech_torch program (Qwen3-TTS: one voice across Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian) on a machine that can run PyTorch.")
    last, f = _source(d), d["clone"]
    said = (f"""From the take "{C._esc(last["text"][:60])}" ({last.get("secs", "?")} s): its words are known exactly. """ + C._btn("Use the last recording instead", "lab_form", part="clone", take="-") if last.get("take") else f"""From the last recording above ({last.get("duration_s", "?")} s): 3 to 15 s of one clear voice works best; its words are what was heard, corrected by you.""") if last else "Record (or pick a file) under Hear first, or press Voice from this on a take: that sound is what the voice is made from."
    return f"""<form id="cv-lab-clone-f" class="cv-form" onsubmit="return false">{C._dim(said)}<textarea name="text" class="module-input" rows="2" style="width:100%" placeholder="the exact words of the recording">{C._esc(f.get("text") or (last or {}).get("text", ""))}</textarea><div class="row" style="flex-wrap:wrap"><input name="name" class="module-input" placeholder="voice name (letters, digits, - and _)" value=""><label>machine {_sel("pid", [(q["id"], q.get("name") or q["id"]) for q, _ in ms], f.get("pid"))}</label><span class="grow"></span>{C._btn("Make the voice", "lab_clone", include="#cv-lab-clone-f") if last else ""}</div></form>"""

# --- Intents ---

async def _h_form(request, payload, imr):
    """A form drawn again for another machine (its voices and models), or filled from a take ("take")."""
    user, part = C._user(request), payload["part"]
    d = _load(user)
    if part == "clone": d["clone"] = {**d["clone"], "take": payload.get("take") if payload.get("take") != "-" else "", "text": next((k["text"] for k in d["takes"] if k["id"] == payload.get("take")), "")}
    elif payload.get("take"): d["say"] = {k: v for k, v in next(k for k in d["takes"] if k["id"] == payload["take"]).items() if k in ("text", "pid", "model", "voice", "voice_id", "language", "length_scale")}
    else: d[part] = {**d[part], **{k: v for k, v in payload.items() if k not in ("type", "branch", "lvl", "part")}}
    _save(user, d)
    return imr.oob(_say_form(request, d["say"]) if part == "say" else _hear_form(request, d["hear"]) if part == "hear" else _clone_form(request, d), f"cv-lab-{part}")

async def _h_start(request, payload, imr):
    """A machine's speech program started, so it lists its voices (the path its own note names, else speech)."""
    p = C.AV.lib.get("provider", payload["pid"])
    note = _voices(p).get("note", "")
    path = note[note.index("/services/"):].split()[0] if "/services/" in note else "/services/speech/start"
    try: await C.PROV.machine(p, "POST", path, {}, timeout=600.0)
    except C.PROV.ProviderError as e: return imr.oob(C._note(C.older(e, "start its speech program"), True), "cv-lab-say")
    C.AV.seen.forget(f"""{p["id"]}:info:voice_list""")   # asked again: the list fills once the program answers
    return imr.oob(_say_form(request, _load(C._user(request))["say"]), "cv-lab-say")

async def _h_say(request, payload, imr):
    """A take: the text said with the form's settings (or exactly those of take "again"), kept with them."""
    user = C._user(request)
    d = _load(user)
    f = {k: v for k, v in next(k for k in d["takes"] if k["id"] == payload["again"]).items()} if payload.get("again") else {k: payload.get(k, "") for k in ("text", "pid", "model", "voice", "voice_id", "language", "length_scale")}
    if not payload.get("again"): d["say"] = f
    if not str(f.get("text", "")).strip(): return imr.oob(C._note("Write what to say first.", True), "cv-lab-takes")
    p, kid, t0 = C.AV.lib.get("provider", f["pid"]), _id(), time.time()
    voice = (f.get("voice_id") or "").strip() or f.get("voice") or ""
    body = {k: v for k, v in {"text": f["text"], "model": f.get("model"), "voice": voice, "language": f.get("language"), "length_scale": float(f["length_scale"]) if f.get("length_scale") not in (None, "") else None}.items() if v not in (None, "")}
    take = {"id": kid, **{k: f.get(k) for k in ("text", "pid", "model", "voice", "voice_id", "language", "length_scale")}, "voice": voice, "machine": p.get("name") or p["id"]}
    try:
        r = (await C.PROV.run(p, "text_to_speech", body))["result"] or {}
        take.update(file=Path(C.MEDIA._keep_audio(user, f"lab-say-{kid}.{r.get('format') or 'wav'}", r["audio_b64"])).name, secs=r.get("duration_s"), took=round(time.time() - t0, 1))
    except (KeyError, C.PROV.ProviderError) as e: take.update(error=str(e), took=round(time.time() - t0, 1))
    d["takes"].insert(0, take)
    _save(user, d)
    return imr.oob(_takes(d), "cv-lab-takes")

async def _h_hear(request, payload, imr):
    """A hearing: a new recording ("audio_b64", WAV from the page), or the last one again ("again"), with the form's settings - by its recognizer, or by every recognizer of that machine ("every")."""
    user = C._user(request)
    d = _load(user)
    f = {k: payload.get(k, "") for k in ("pid", "model", "language", "beam_size", "initial_prompt")} | {"vad_filter": bool(payload.get("vad_filter"))}
    d["hear"] = f
    if payload.get("audio_b64"): name = Path(C.MEDIA._keep_audio(user, f"""lab-rec-{_id()}.wav""", payload["audio_b64"])).name
    else: name = next((h["file"] for h in d["hears"] if h.get("file")), "")
    if not name: return imr.oob(C._note("Record or pick a sound file first.", True), "cv-lab-hears")
    audio = base64.b64encode((C.MEDIA._audio_dir(user) / name).read_bytes()).decode()
    if payload.get("wake"):   # every wake word of a machine that has them (this one when it does), scored on the recording
        wm = _machines(request, "wake_detect")
        p = next((q for q, _ in wm if q["id"] == f["pid"]), wm[0][0])
        h = {"id": _id(), "file": name, "model": "wake words", "machine": p.get("name") or p["id"]}
        try: r = (await C.PROV.run(p, "wake_detect", {"audio_b64": audio}))["result"] or {}
        except C.PROV.ProviderError as e: r = {"error": str(e)}
        h.update(text="; ".join(f"{k} {v:.2f}" for k, v in sorted((r.get("scores") or {}).items(), key=lambda x: -x[1])) or "", **({"error": r["error"]} if r.get("error") else {"elapsed_s": round((r.get("ms") or 0) / 1000, 3), "duration_s": r.get("seconds")}))
        d["hears"].insert(0, h)
        _save(user, d)
        return imr.oob(_hears(d), "cv-lab-hears")
    p = C.AV.lib.get("provider", f["pid"])
    models = [a["name"] for q, assets in _machines(request, "speech_to_text") if q["id"] == p["id"] for a in assets] if payload.get("every") else [f.get("model")]
    for m in models:
        body = {k: v for k, v in {"audio_b64": audio, "model": m, "language": f["language"], "beam_size": int(f["beam_size"]) if str(f["beam_size"]).strip() else None, "vad_filter": f["vad_filter"], "initial_prompt": f["initial_prompt"]}.items() if v not in (None, "")}
        h = {"id": _id(), "file": name, "model": m, "machine": p.get("name") or p["id"], **{k: f[k] for k in ("language", "beam_size", "initial_prompt", "vad_filter")}}
        try: h.update({k: v for k, v in ((await C.PROV.run(p, "speech_to_text", body))["result"] or {}).items() if k in ("text", "segments", "language", "language_probability", "duration_s", "elapsed_s")})
        except C.PROV.ProviderError as e: h["error"] = str(e)
        d["hears"].insert(0, h)
    _save(user, d)
    imr.oob(_clone_form(request, d), "cv-lab-clone")   # its words follow the newest hearing
    return imr.oob(_hears(d), "cv-lab-hears")

async def _h_clone(request, payload, imr):
    """A voice made from the last recording and its words, on the chosen machine (voice_clone_add: a name already there is refused, nothing is replaced)."""
    user = C._user(request)
    d = _load(user)
    d["clone"] = {**d["clone"], "text": payload.get("text", ""), "pid": payload.get("pid", "")}
    _save(user, d)
    last = _source(d)
    if not (last and payload.get("name", "").strip() and payload.get("text", "").strip()): return imr.oob(C._note("A recording, a name and its exact words are needed.", True), "cv-lab-clone")
    p = C.AV.lib.get("provider", payload["pid"])
    try: r = (await C.PROV.run(p, "voice_clone_add", {"name": payload["name"].strip(), "audio_b64": base64.b64encode((C.MEDIA._audio_dir(user) / last["file"]).read_bytes()).decode(), "text": payload["text"].strip()}))["result"] or {}
    except C.PROV.ProviderError as e: return imr.oob(_clone_form(request, d) + C._note(str(e), True), "cv-lab-clone")
    C.AV.seen.forget(f"""{p["id"]}:info:voice_list""")
    return imr.oob(_clone_form(request, d) + C._note(f"""Made {C._esc(r.get("voice", ""))} ({r.get("seconds", "?")} s of reference). {C._esc(r.get("note", ""))} Say something with it above (machine {C._esc(p.get("name") or p["id"])}, voice id {C._esc(r.get("voice", ""))}), in any of its languages: the same voice speaks each.""", False), "cv-lab-clone")

async def _h_drop(request, payload, imr):
    """A take or a hearing deleted, with its sound file when nothing else kept uses it."""
    user, kind = C._user(request), payload["kind"]
    d = _load(user)
    gone = next((x for x in d[kind] if x["id"] == payload["id"]), None)
    d[kind] = [x for x in d[kind] if x["id"] != payload["id"]]
    if gone and gone.get("file") and not any(x.get("file") == gone["file"] for x in d["takes"] + d["hears"]): (C.MEDIA._audio_dir(user) / gone["file"]).unlink(missing_ok=True)
    _save(user, d)
    return imr.oob(_takes(d) if kind == "takes" else _hears(d), f"cv-lab-{kind}")

# --- The page's recorder: the microphone or a file, sent as 24 kHz mono WAV (what every recognizer and voice maker takes) ---

LAB_JS = """<script>
window.cvLab = window.cvLab || (function () {
    var R = null, chunks = [];
    function say(t) { var e = document.getElementById('cv-lab-rec-state'); if (e) e.textContent = t; }
    async function wav(buf) {
        var a = await new AudioContext().decodeAudioData(buf), n = Math.ceil(a.duration * 24000), o = new OfflineAudioContext(1, n, 24000), s = o.createBufferSource();
        s.buffer = a; s.connect(o.destination); s.start();
        var x = (await o.startRendering()).getChannelData(0), v = new DataView(new ArrayBuffer(44 + x.length * 2));
        var w = function (p, t) { for (var i = 0; i < t.length; i++) v.setUint8(p + i, t.charCodeAt(i)); };
        w(0, 'RIFF'); v.setUint32(4, 36 + x.length * 2, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 24000, true); v.setUint32(28, 48000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, x.length * 2, true);
        for (var i = 0; i < x.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, x[i])) * 32767, true);
        var b = new Uint8Array(v.buffer), out = '';
        for (var k = 0; k < b.length; k += 32768) out += String.fromCharCode.apply(null, b.subarray(k, k + 32768));
        return 'data:audio/wav;base64,' + btoa(out);
    }
    async function send(buf) {
        say('sending ...');
        var f = document.getElementById('cv-lab-hear-f'), v = Object.fromEntries(new FormData(f).entries());
        v.type = 'corvid_lab_hear'; v.lvl = 1; v.audio_b64 = await wav(buf);
        htmx.ajax('POST', '/im/in', {values: v, swap: 'none'}).then(function () { say(''); });
    }
    return {
        rec: async function (btn) {
            if (R) { R.stop(); return; }
            var st = await navigator.mediaDevices.getUserMedia({audio: true});
            R = new MediaRecorder(st); chunks = [];
            R.ondataavailable = function (e) { chunks.push(e.data); };
            R.onstop = async function () { st.getTracks().forEach(function (t) { t.stop(); }); R = null; btn.classList.remove('active'); send(await new Blob(chunks).arrayBuffer()); };
            R.start(); btn.classList.add('active'); say('recording - press again to stop');
        },
        file: async function (inp) { if (inp.files[0]) send(await inp.files[0].arrayBuffer()); inp.value = ''; }
    };
})();
</script>"""
