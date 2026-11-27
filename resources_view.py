"""resources_view.py - Asio's view of the resources (Aviary's resources.py): every machine's parts and the path to it, every distinct model with where its copies are, and each figure as stated beside measured. Tests run from here (the characterizer) and fill the measured side.
Part of Corvid, loaded beside corvid.py (_beside); C is the live view of corvid's globals."""
import json, asyncio
from pathlib import PurePosixPath
from urllib.parse import urlsplit, unquote

C = None
PULLS = set()   # pulls under way: the event loop holds its tasks only weakly
TESTS = {}   # provider id -> {"running": bool, "notes": [...], "result": {...}}: what a test started from this page is doing

def init(c):
    global C
    C = c
    C.IM.scripts.update({"corvid_res_sync": [_h_sync], "corvid_res_test": [_h_test], "corvid_res_test_all": [_h_test_all], "corvid_res_copy": [_h_copy], "corvid_res_bring": [_h_bring], "corvid_res_info": [_h_info], "corvid_res_rename": [_h_rename], "corvid_res_label": [_h_label], "corvid_res_remove": [_h_remove], "corvid_res_pull": [_h_pull], "corvid_res_dl": [_h_dl], "corvid_res_dl_rm": [_h_dl_rm], "corvid_res_naming": [_h_naming], "corvid_res_forget": [_h_forget], "corvid_res_unstore": [_h_unstore]})

# --- Figures as text ---

def _disks(places: list) -> str:
    """Each disk once: its free and total space, how much is used, and the places on it. Places share a disk when the machine says so (dev); a machine that does not say is grouped by equal free and total space."""
    disks = {}
    for p in places: disks.setdefault(p["attrs"].get("dev") or (p["attrs"].get("free_gb"), p["attrs"].get("total_gb")), []).append(p)
    one = lambda ps: f"""<div title="{C._esc(chr(10).join(f'{p["name"]}: {p["attrs"].get("path", "")}' for p in ps))}"><b>{_num(ps[0]["attrs"].get("free_gb"))}</b> free of {_num(ps[0]["attrs"].get("total_gb"))} GB ({_num(round((ps[0]["attrs"].get("total_gb") or 0) - (ps[0]["attrs"].get("free_gb") or 0), 1))} used) <span class="cv-dim">{C._esc(", ".join(p["name"] for p in ps))}</span></div>"""
    return "".join(one(ps) for ps in disks.values()) or '<span class="cv-dim">not read yet</span>'

def _num(v, unit: str = "") -> str: return "-" if v is None else f"""{v:,.1f}{" " + unit if unit else ""}""" if isinstance(v, float) else f"""{v:,}{" " + unit if unit else ""}"""

def _busy(figs: dict, key: str, unit: str) -> str:
    """A speed-test figure, and the latest one taken while the machine was busy beside it (marked; it is not in the measured figure)."""
    b = figs.get(key + "_busy") or {}
    mark = f""" <span class="chip cv-mid" title="{C._esc(b.get("source") or "")}">&#x26A0; {_num(b["stated"], unit)} while busy</span>""" if b.get("stated") is not None else ""
    return _fig(figs.get(key), unit) + mark

def _reached(machine: str, parts: list) -> str:
    """The servers a machine passes work on to (its remote sources: an Ollama on another computer), each a resource reached through it: their machines are not measured, what they hold loaded is in Now."""
    return "".join(f"""<tr><td class="cv-dim">&#x21B3; {C._esc(p["name"])}</td><td colspan="8" class="cv-dim">a server {C._esc(machine)} passes work on to: {C._esc(p["attrs"].get("url") or "")}{" | Ollama " + C._esc(p["attrs"]["version"]) if p["attrs"].get("version") else ""} | {p["attrs"].get("models") or 0} model(s){" | " + C._esc(p["attrs"]["error"]) if p["attrs"].get("error") else ""}. Its machine is not measured (nothing of Magpie runs there); what it holds loaded and what is sent there now are in Now.</td></tr>""" for p in parts if p["kind"] == "source")

def _gpus(parts: list) -> str:
    """Each graphics processor under the memory: its own memory, or for one that shares the system's (an iGPU) the part set aside for it and how much more it may map (GTT) - both are the same RAM."""
    def one(a):
        if a.get("integrated"): return f"""<div class="cv-dim" title="shares the system memory: the part set aside is taken from RAM at boot, and the GTT is more RAM it may map when needed">iGPU {C._esc(a.get("vendor") or "")}: {_num(a.get("vram_gb"), "GB")} set aside + up to {_num(a.get("gtt_gb"), "GB")} shared</div>"""
        return f"""<div class="cv-dim" title="{"its own memory" if a.get("integrated") is False else "whether it has memory of its own is not known (an older Magpie, or a driver that does not say)"}">GPU {C._esc(a.get("vendor") or "")}: {_num(a.get("vram_gb"), "GB")}{" own" if a.get("integrated") is False else ""}</div>"""
    return "".join(one(p["attrs"]) for p in parts if p["kind"] == "gpu" and p.get("attrs"))

def _fig(f: dict, unit: str = "") -> str:
    """One figure: what it was measured to be (how many tests, how sure), beside what it says it is."""
    if not f: return '<span class="cv-dim">-</span>'
    st, me = f.get("stated"), f.get("measured")
    meas = f"""<b>{_num(me, unit)}</b> <span class="cv-dim" title="{f["n"]} test(s); confidence {f["conf"]}">({f["n"]})</span>""" if me is not None else ""
    said = f"""<span class="cv-dim" title="{C._esc(f.get("source") or "")}">says {_num(st, unit)}</span>""" if st is not None else ""
    return f"""{meas} {said}""".strip()

# --- Network: each machine's interfaces and the lanes between machines ---

SHAPING = ("tbf", "htb", "hfsc", "cake", "cbq", "netem")   # queues that limit or delay what an interface sends

def _why_slow(n: dict, sp: int) -> str:
    """Which side holds a wired link below gigabit, from what each end offered when the link was negotiated (Magpie reads it with ethtool, and the NetworkManager profile's own link settings): this machine's settings, the other end (switch port or cable), or neither (the driver or firmware). Without those readings, the three usual causes are named."""
    ours, theirs, top, nm = n.get("offered_max"), n.get("partner_max"), n.get("supported_max"), {k: n[k] for k in ("nm_profile_speed", "nm_profile_duplex", "nm_profile_autoneg") if n.get(k)}
    if nm: return f"""link at {sp} Mbit/s: the NetworkManager profile "{n.get("nm_profile", "")}" sets {", ".join(f"{k[11:]} {v}" for k, v in nm.items())} - clear it (nmcli connection modify "{n.get("nm_profile", "")}" 802-3-ethernet.speed 0 802-3-ethernet.duplex "" 802-3-ethernet.auto-negotiate yes) and reconnect"""
    if n.get("autoneg") == "off": return f"link at {sp} Mbit/s with auto-negotiation off on this machine - a fixed speed is set here (ethtool -s {n['name']} autoneg on)"
    if ours and top and ours <= sp < top: return f"link at {sp} Mbit/s: this machine offers only {ours} though it supports {top} - a setting here limits what it offers (ethtool -s {n['name']} advertise / a udev or systemd .link file / a NetworkManager dispatcher)"
    if theirs and theirs <= sp: return f"link at {sp} Mbit/s: the other end (switch port, or the cable's pairs) offered only {theirs}"
    if ours and theirs and min(ours, theirs) > sp: return f"""link at {sp} Mbit/s though both ends offer {min(ours, theirs)}: the driver ({n.get("driver") or "?"}) or firmware{" - Energy-Efficient Ethernet is " + n["eee"] + ", a common cause with Realtek parts (ethtool --set-eee " + n["name"] + " eee off)" if n.get("eee", "").startswith("enabled") else ""}"""
    return f"link at {sp} Mbit/s (a cable, port or setting holding it below gigabit; this machine's Magpie reads which side once ethtool is installed there)"

def _net_notes(n: dict, mates: list = ()) -> list:
    """What about one interface usually explains a slow path: a link that negotiated below gigabit, half duplex, a shaping queue, errors or drops counted since boot; with the machine's other interfaces (mates): a connected wired link with no address, or the default route going out a slower link than another that is up."""
    sp, out = n.get("speed_mbit"), []
    if n.get("default_route") and sp and (fast := max((m for m in mates if m is not n and m.get("state") == "up" and (m.get("speed_mbit") or 0) > sp), key=lambda m: m["speed_mbit"], default=None)): out.append(f"""default route goes out here at {sp} Mbit/s while {fast["name"]} is up at {fast["speed_mbit"]}""")
    if n.get("kind") == "ethernet" and n.get("state") == "up" and not n.get("addrs"): out.append("connected but has no address: nothing is sent through it")
    if n.get("kind") == "ethernet" and sp and sp < 1000: out.append(_why_slow(n, sp))
    if n.get("duplex") == "half": out.append("half duplex (a mismatch with the other end slows one direction most)")
    if n.get("qdisc") in SHAPING: out.append(f"""sends through a {n["qdisc"]} queue (it limits or delays what leaves)""")
    if (e := n.get("rx_errors", 0) + n.get("tx_errors", 0)): out.append(f"{e} errors since boot")
    if (d := n.get("tx_dropped", 0)): out.append(f"{d} sends dropped since boot")
    return out

def net_html(R, machines: list, figs: dict) -> str:
    """Interfaces per machine (as each reported at the last read), then each lane measured between two machines."""
    def irow(g, n):
        a = n["attrs"]
        notes = _net_notes(a, [x["attrs"] for x in R.parts(g["id"]) if x["kind"] == "net"])
        sp = f"""{a["speed_mbit"]} Mbit/s""" if a.get("speed_mbit") else ("-" if a.get("state") == "up" else a.get("state") or "-")
        flag = f"""<span class="chip cv-bad" title="{C._esc("; ".join(notes))}">{C._esc(notes[0])}{f" (+{len(notes) - 1})" if len(notes) > 1 else ""}</span>""" if notes else '<span class="chip cv-ok">ok</span>' if a.get("state") == "up" else ""
        return f"""<tr><td><b>{C._esc(g["name"])}</b></td><td class="mono">{C._esc(a["name"])}</td><td>{C._esc(a.get("kind") or "")}</td><td class="cv-dim">{C._esc(a.get("driver") or "")}</td><td>{C._esc(sp)}</td><td>{C._esc(a.get("duplex") or "")}</td><td>{a.get("mtu") or ""}</td><td class="cv-dim">{C._esc(a.get("qdisc") or "")}</td><td class="mono">{C._esc(", ".join(a.get("addrs") or []))}</td><td>{flag}</td></tr>"""
    rows = "".join(irow(g, n) for g in machines for n in R.parts(g["id"]) if n["kind"] == "net")
    ifs = f"""<b>Network interfaces</b> <span class="cv-dim">as each machine reported at the last read; a red chip names what usually slows a path (hover for all)</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>machine</th><th>interface</th><th>kind</th><th>driver</th><th>link</th><th>duplex</th><th>MTU</th><th>queue</th><th>addresses</th><th></th></tr>{rows}</table></div>""" if rows else C._dim("No interfaces reported yet (a machine reports them once its Magpie is updated, then Read the machines again).")
    lanes = [ln for g in machines for ln in R.parts(g["id"]) if ln["kind"] == "lane"]
    def lrow(ln):
        f = figs.get(ln["id"], {})
        return f"""<tr><td>{C._esc(ln["name"])}</td><td class="mono cv-dim">{C._esc(ln["attrs"].get("a_addr"))} &#x2192; {C._esc(ln["attrs"].get("b_addr"))}</td><td>{_fig(f.get("to_mb_s"), "MB/s")}</td><td>{_fig(f.get("from_mb_s"), "MB/s")}</td><td>{_fig(f.get("rtt_ms"), "ms")}</td></tr>"""
    lt = f"""<b>Lanes between machines</b> <span class="cv-dim">each network two machines share, measured on its own (sent from the first machine's address there); a lane much slower one way than the other points at that direction's interface</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>lane</th><th>addresses</th><th>to</th><th>from</th><th>round trip</th></tr>{"".join(lrow(ln) for ln in lanes)}</table></div>""" if lanes else ""
    return f"""<details><summary><b>Network</b> <span class="cv-dim">interfaces and lanes</span></summary>{ifs}{lt}</details>"""

# --- Panel ---

async def p_resources(c) -> str:
    R, admin = C.AV.resources, C._admin(c.request)
    if not R.groups(): await R.sync()
    figs, provs = R.figures(prefix=True), {p["id"]: p for p in C.AV.lib.list("provider")}
    machines, servers = [g for g in R.groups() if g["kind"] == "machine"], [g for g in R.groups() if g["kind"] == "server"]
    def sline(g):   # a server that does not speak the node contract (an Ollama) is a resource too: what it holds is known, its machine is not
        n, files = len([1 for m in R.models() for cp in m["copies"] if cp["grp"] == g["id"]]), next((p["attrs"].get("count") for p in R.parts(g["id"]) if p["kind"] == "files"), None)
        holds = f"""{files} file(s) of its own (assets, not models: they are not listed with the models)""" if files is not None else f"""{n} model(s) (below); what it has loaded is in Now"""
        return f"""<tr><td><b>{C._esc(g["name"])}</b></td><td colspan="8" class="cv-dim">a server that speaks {C._esc((provs.get(g.get("provider") or g["id"]) or {}).get("speaks") or "its own language")}, not Magpie: it says nothing of its machine (threads, memory, disks) and is not tested here. It holds {holds}. A Magpie on that machine would measure it.</td></tr>"""
    def mline(g):
        gid, parts = g["id"], R.parts(g["id"])
        cpu, ram = figs.get(f"{gid}/cpu", {}), figs.get(f"{gid}/ram", {})
        store = _disks([p for p in parts if p["kind"] == "storage"])
        link = figs.get(f"portal~{gid}", {})
        t = TESTS.get(gid, {})
        test = f"""<span class="cv-dim">{C._esc(t["notes"][-1] if t.get("notes") else "testing ...")}</span>""" if t.get("running") else C._btn("Test", "res_test", "ui-btn cv-small", face=c.face["id"], pid=gid, title="Measures the machine (processor, memory, disk), the path to it from this portal and to each other machine, and each chat model on it (speed, and memory held once loaded). Models load one after another; work running there waits its turn.") if admin and gid in provs else ""
        clear = C._btn("&#x2715; results", "res_forget", "ui-btn cv-small", face=c.face["id"], grp=gid, confirm=f"""Clear the test results of {g["name"]} (the machine, its models' speeds there, its paths)? What it says of itself stays; the next Test starts them again.""", title="Clears its measured figures, for results taken before a change that made them wrong") if admin else ""
        return f"""<tr><td><b>{C._esc(g["name"])}</b></td><td>{_fig(cpu.get("threads"))}</td><td>{_fig(cpu.get("cpu_mb_s_all"), "MB/s")}</td><td>{_fig(ram.get("total_gb"), "GB")}{_gpus(parts)}</td><td>{_busy(ram, "mem_gb_s", "GB/s")}</td><td>{_fig(figs.get(f"{gid}/storage/models", {}).get("disk_read_gb_s"), "GB/s")}</td><td>{_fig(link.get("to_mb_s"), "MB/s")} / {_fig(link.get("from_mb_s"), "MB/s")}{" | " + _fig(link.get("rtt_ms"), "ms") if link.get("rtt_ms") else ""}</td><td class="cv-dim">{store}</td><td>{test}{clear}</td></tr>{_reached(g["name"], parts)}"""
    head = """<tr><th>machine</th><th>threads</th><th title="SHA-256 hashing on every thread at once, in MB of data hashed per second: a rough comparison of the machines' integer speed. Not the arithmetic models use, and not a memory figure.">processor (hashing)</th><th>memory</th><th title="Copying between two buffers on up to 8 threads, read and written counted both (as STREAM counts): roughly half to two thirds of the memory's rated peak. Work running there at the time (a loaded model answering) shares the bus and makes it read low: such a result is marked and kept apart.">memory rate (copy)</th><th>disk read (models)</th><th>path from / to this portal | round trip</th><th>storage free / total</th><th></th></tr>"""
    ms = R.models()
    def speed(m, g):
        here = figs.get(f"""{m["id"]}@{g["id"]}""", {})
        f, mem = here.get("decode_tps"), here.get("ram_gb_loaded")
        held = f"""<br><span class="cv-dim" title="memory held once loaded ({C._esc(mem.get("source") or "")})">{_num(mem["measured"], "GB")} loaded</span>""" if mem and mem.get("measured") is not None else ""
        if f and f.get("measured") is not None: return _fig(f, "t/s") + held
        if "chat" not in m["facts"].get("capabilities", []): return '<span class="cv-dim" title="decode speed is a figure of chat models; this one does other work">n/a</span>'
        e = R.estimate(m["id"], g["id"])
        return f"""<span class="cv-dim" title="estimate from {C._esc(e.get("from", ""))}">~{_num(e["decode_tps"])}</span>""" if e else '<span class="cv-dim">-</span>'
    def manage(m):
        """Copy or move to a machine without a copy; remove one copy (the last only by its own button)."""
        have, mid = {cp["grp"]: cp["name"] for cp in m["copies"]}, m["id"]
        to = [g for g in machines if g["id"] not in have]
        pick = f"""<select name="dst" class="module-select" style="width:auto">{"".join(f'<option value="{g["id"]}">{C._esc(g["name"])}</option>' for g in to)}</select>""" if to else ""
        src = next(iter(have))
        moves = f"""<form class="row" onsubmit="return false" id="cv-mv-{abs(hash(mid))}">{pick}{C._btn("Copy", "res_copy", "ui-btn cv-small", face=c.face["id"], mid=mid, src=src, include=f"#cv-mv-{abs(hash(mid))}", title="A copy sent straight from the machine that has it; checked once there")}{C._btn("Move", "res_copy", "ui-btn cv-small", face=c.face["id"], mid=mid, src=src, move="1", include=f"#cv-mv-{abs(hash(mid))}", title="Copied, checked, then removed where it was")}</form>""" if pick else ""
        def rm(g, n):
            last = len(have) == 1
            return C._btn(f"""Remove {"the last copy" if last else "copy"} on {C._esc(next((x["name"] for x in machines if x["id"] == g), g))}""", "res_remove", "ui-btn cv-small", face=c.face["id"], mid=mid, grp=g, name=n, last="1" if last else "", confirm=f"""Remove the ONLY copy of {n}? Nothing else holds this model; it would have to be downloaded again.""" if last else f"""Remove the copy of {n} on that machine? Other copies stay.""")
        return f"""<details class="cv-dim"><summary>manage</summary>{moves}<div class="row" style="flex-wrap:wrap">{"".join(rm(g, n) for g, n in have.items())}</div><div class="cv-dim">To bring a new model onto a machine: Settings &gt; Machines &gt; Download a model file onto a machine.</div></details>"""
    def mrow(m):
        fx, here = m["facts"], {cp["grp"] for cp in m["copies"]}
        names = ", ".join(sorted({cp["name"] for cp in m["copies"]}))
        kv = figs.get(m["id"], {}).get("kv_bytes_per_token_f16", {})
        cells = "".join(f"""<td{' class="cv-dim"' if g["id"] not in here else ""} title="{"a copy is here" if g["id"] in here else "no copy here: it would be carried first"}">{speed(m, g)}</td>""" for g in machines)
        unread = f"""<br><span class="cv-dim" title="{C._esc(fx["unread"])}">header not read (hover: why)</span>""" if fx.get("unread") else ""
        return f"""<tr><td class="mono">{C._esc(names)}{unread}{manage(m) if admin else ""}</td><td>{C._esc(str(fx.get("general.architecture") or "-"))}</td><td>{_num(fx.get("params_b"), "B")}{f' <span class="cv-dim">{fx["experts_used"]}/{fx["experts"]} experts</span>' if fx.get("experts") else ""}</td><td>{_num(fx.get("bpw"))}</td><td>{_num(round(m["size"] / 1e9, 1), "GB")}</td><td>{_fig(kv, "B") if kv else "-"}</td><td>{_num(fx.get("context_length"))}</td>{cells}</tr>"""
    mhead = f"""<tr><th>model (names it has)</th><th>architecture</th><th>parameters</th><th>bits/weight</th><th>size</th><th title="computed from the header for an f16 cache; to be verified by test">KV per token</th><th>trained context</th>{"".join(f'<th>{C._esc(g["name"])} t/s</th>' for g in machines)}</tr>"""
    def path(a, b):
        if a["id"] == b["id"]: return '<td class="cv-dim">-</td>'
        f = figs.get(f"""{a["id"]}~{b["id"]}""", {}).get("to_mb_s") or figs.get(f"""{b["id"]}~{a["id"]}""", {}).get("from_mb_s")
        lag = figs.get(f"""{a["id"]}~{b["id"]}""", {}).get("rtt_ms") or figs.get(f"""{b["id"]}~{a["id"]}""", {}).get("rtt_ms")   # a round trip is the same both ways
        return f"<td>{_fig(f, 'MB/s')}{' | ' + _fig(lag, 'ms') if lag else ''}</td>" if f else '<td class="cv-dim" title="not tested yet: Test on either machine measures it">-</td>'
    paths = f"""<b>Paths between machines</b> <span class="cv-dim">row to column, as measured by Test on either one; after the bar: the round trip of a small request (the delay alone)</span><div class="scroll-pane"><table class="cv-tbl"><tr><th>from &#x2192; to</th>{"".join(f'<th>{C._esc(g["name"])}</th>' for g in machines)}</tr>{"".join(f'<tr><td><b>{C._esc(a["name"])}</b></td>{"".join(path(a, b) for b in machines)}</tr>' for a in machines)}</table></div>""" if len(machines) > 1 else ""
    poll = f"""<div id="cv-res-tests" hx-get="{C._P}/res_tests" hx-trigger="load, every 3s" hx-swap="innerHTML"></div>""" if TESTS else ""
    every = C._btn("Test every machine", "res_test_all", face=c.face["id"], title="Each machine in turn, never two at once (so one test's traffic does not slow another's): the machine, its paths, its chat models. Takes a while; work running on a machine waits its turn while its models are tested.") if admin and not any(t.get("running") for t in TESTS.values()) else ""
    some = f"""<details><summary class="cv-dim">Test a set of machines (the paths among them)</summary><form class="row" style="flex-wrap:wrap" id="cv-test-set" onsubmit="return false">{"".join(f'<label class="chip"><input type="checkbox" name="ids" value="{C._esc(g["provider"])}"> {C._esc(g["name"])}</label>' for g in machines if g.get("provider") and C.AV.lib.has("provider", g["provider"]) and not C.AV.lib.get("provider", g["provider"]).get("speaks"))}<label class="cv-dim" title="Also load and time each ticked machine's chat models (slow); without it only the machines and the paths between them are measured"><input type="checkbox" name="models" value="1"> their models too</label>{C._btn("Test these", "res_test_all", "ui-btn cv-small", face=c.face["id"], include="#cv-test-set")}</form>{C._dim("For a group that will work together (one split model, a pipeline across machines): each ticked machine in turn measures its path to every other ticked one, so the table below fills for that group only.")}</details>""" if every else ""
    forget = C._btn("Clear every test result", "res_forget", "ui-btn cv-danger", face=c.face["id"], confirm="Clear the test results of every machine, model and path? What the machines say of themselves stays; Test measures again.", title="For results taken before changes that made them wrong") if admin else ""
    top = f"""<div class="row">{C._btn("Read the machines again", "res_sync", face=c.face["id"], title="Asks every machine for its parts, places and models. Measurements are kept.")}{every}<span class="grow"></span>{forget}</div>{some}"""
    return f"""{poll}{top}{C._dim("Bold: measured (number of tests). Grey 'says': what it reports or what follows from its labels. ~: an estimate from what was measured elsewhere. A test replaces nothing: each one is added to the figures.")}
               <div class="scroll-pane"><table class="cv-tbl cv-roomy">{head}{"".join(mline(g) for g in machines) or '<tr><td colspan="9" class="cv-dim">no machine yet</td></tr>'}{"".join(sline(g) for g in servers)}</table></div>
               {paths}
               {net_html(R, machines, figs)}
               <b>Models</b> <span class="cv-dim">one row per distinct file, under every name it has; a column per machine: decode speed there</span>
               <div class="scroll-pane"><table class="cv-tbl">{mhead}{"".join(mrow(m) for m in ms) or '<tr><td class="cv-dim">no models listed</td></tr>'}</table></div>"""

def tests_html() -> str:
    """What the tests started from this page are doing, or what they ended with."""
    rows = "".join(f"""<div class="row"><b class="grow">{C._esc(pid)}</b><span class="chip {"cv-mid" if t["running"] else "cv-ok"}">{"testing" if t["running"] else "done: read again to see the figures"}</span></div><div class="cv-dim" style="margin:0 0 .3rem 1em;overflow-wrap:anywhere">{C._esc(" | ".join(t["notes"][-3:]))}</div>""" for pid, t in TESTS.items())   # what each test answered on a line of its own: beside the name it squeezed both
    return rows

# --- Handlers ---

def _p(gid: str) -> dict: return C.AV.lib.get("provider", gid)

async def p_models(c) -> str:
    """Models as a resource of the whole set-up rather than of one machine: one row per distinct file (under every name it has), a column per machine - a copy is there or not - and, for an admin, in each cell: copy it there, move it there, or remove that copy. What a model can do and its size come from what the machines list; where it runs is placement's choice among the machines that hold it or can be given it. A filter hides what is not looked for (image LoRAs and the like are off by default), and the places a copy sits are shown only when asked."""
    R, admin = C.AV.resources, C._admin(c.request)
    if not R.groups(): await R.sync()
    machines, ms, names = [g for g in R.groups() if g["kind"] in ("machine", "server")], R.models(), {g["id"]: g["name"] for g in R.groups()}   # server: one that does not speak the node contract (an Ollama); its models are shown, and are its own to move or remove
    does, kinds_of = {}, {g["id"]: g["kind"] for g in R.groups()}
    for o in C._offers_now():
        for a in o["assets"]: does.setdefault(a["name"], set()).update(a.get("capabilities") or [])
    def cell(m, g):
        cp = next((x for x in m["copies"] if x["grp"] == g["id"]), None)
        if g["kind"] == "server":
            if not cp: return """<td class="cv-dim" title="A server that keeps its own files: a model comes onto it by its own pull (above the table)">-</td>"""
            rm = C._btn("remove", "res_remove", "ui-btn cv-small cv-danger", face=c.face["id"], mid=m["id"], grp=g["id"], name=cp["name"], last="1" if len(m["copies"]) == 1 else "", confirm=f"""Remove {cp["name"]} from {g["name"]}? The server deletes it itself.{" This is the only copy anywhere." if len(m["copies"]) == 1 else ""}""") if admin else ""
            return f"""<td><span class="chip cv-ok" title="{C._esc(cp["location"])}">here</span> {rm}</td>"""
        if cp:
            only = len(m["copies"]) == 1
            rm = C._btn("remove", "res_remove", "ui-btn cv-small cv-danger", face=c.face["id"], mid=m["id"], grp=g["id"], name=cp["name"], last="1" if only else "", confirm=f"""Remove {cp["name"]} from {g["name"]}?{" This is the only copy anywhere: it will be gone." if only else " Other copies stay."}""") if admin else ""
            return f"""<td><span class="chip cv-ok" title="{C._esc(cp.get("location") or "")}">here</span> {rm}</td>"""
        if not admin or not m["copies"]: return """<td class="cv-dim">-</td>"""
        if not any(kinds_of.get(x["grp"]) == "machine" for x in m["copies"]): return """<td class="cv-dim" title="Held only by a server that keeps its own files: it cannot send them from here">-</td>"""
        return f"""<td class="cv-dim">- {C._btn("bring here ...", "res_bring", "ui-btn cv-small", face=c.face["id"], mid=m["id"], dst=g["id"], title="Copy or move it here, from a machine that has it (chosen in the window)")}</td>"""
    rules = R.naming()
    named = sorted(((R.name_of(min(cp["name"] for cp in m["copies"]), m["facts"], rules), m) for m in ms), key=lambda x: (x[0][0], x[0][1], x[1]["size"]))
    def row(i, bv, m):
        nm = sorted({cp["name"] for cp in m["copies"]})
        kinds = sorted({k for n in nm for k in does.get(n, [])})
        first = i == 0 or named[i - 1][0][0] != bv[0]
        locs = {C._esc(names.get(cp["grp"], cp["grp"])): C._esc(cp.get("location") or "") for cp in m["copies"]}
        loc = "<br>".join(f"""<span class="cv-key">{w}</span> {p or "-"}""" for w, p in locs.items())
        return f"""<tr class="cv-mrow" data-kinds="{C._esc(" ".join(kinds))}" data-size="{m["size"]}" data-copies="{len(m["copies"])}" data-name="{C._esc(bv[0].lower())}"><td class="mono"><b>{C._esc(bv[0]) if first else ""}</b></td><td class="mono">{C._esc(bv[1] or "-")}</td><td class="mono cv-dim" style="overflow-wrap:anywhere">{C._esc(", ".join(nm))} {C._btn("&#x2139;", "res_info", "ui-btn cv-small", face=c.face["id"], mid=m["id"], title="Where each copy's files are, what its header says, and renaming it")}</td><td class="cv-dim">{C._esc(", ".join(kinds) or "-")}</td><td>{_num(round(m["size"] / 1e9, 1), "GB")}</td><td class="cv-loc cv-dim mono" style="overflow-wrap:anywhere">{loc}</td>{"".join(cell(m, g) for g in machines)}</tr>"""
    poll = f"""<div id="cv-res-tests" hx-get="{C._P}/res_tests" hx-trigger="load, every 3s" hx-swap="innerHTML"></div>""" if TESTS else ""
    head = f"""<thead><tr><th title="the base name: files of one model in other quantizations are together">model</th><th title="quantization: the file header's, the server's, or the name's">variant</th><th>names it has</th><th>does</th><th>size</th><th title="where each copy sits">place</th>{"".join(f"<th>{C._esc(g['name'])}</th>" for g in machines)}</tr></thead>"""
    servers = [g for g in machines if g["kind"] == "server"]
    pulls = "".join(f"""<form class="row" style="flex-wrap:wrap" onsubmit="return false" id="cv-pull-{n}"><span class="cv-key">{C._esc(g["name"])}</span><input name="model" class="module-select" placeholder="model name, as its registry names it" title="For example qwen3:8b. The server fetches it itself, from the registry it is set to use (an outside server unless it was pointed elsewhere).">{C._btn("Pull", "res_pull", "ui-btn cv-small", face=c.face["id"], grp=g["id"], include=f"#cv-pull-{n}")}<span class="cv-dim">or on that machine: <span class="mono">ollama pull &lt;name&gt;</span> | <span class="mono">ollama rm &lt;name&gt;</span></span></form>""" for n, g in enumerate(servers)) if admin else ""
    limits = f"""<div class="sec">Servers that are not nodes</div>{C._dim("They list their models and run them; from here a model can be removed or pulled. They do not say where their files are, so nothing is copied to or from them, and their memory and loading are their own.")}{pulls}""" if servers else ""
    body = f"""<tbody id="cv-mb">{"".join(row(i, bv, m) for i, (bv, m) in enumerate(named)) or '<tr><td class="cv-dim">no models listed yet: Read the machines again</td></tr>'}</tbody>"""
    kinds = sorted({k for v in does.values() for k in v})
    ctl = f"""<div class="row" style="flex-wrap:wrap"><input id="cv-mf" class="module-select" placeholder="find (name or what it does)" style="width:12em" title="Rows whose name or what they do does not hold this are hidden; remembered on this page"><select id="cv-mk" class="module-select" title="Only models that do this"><option value="">does anything</option>{"".join(C._option(k, k, "") for k in kinds)}</select><label class="cv-dim" title="LoRAs and other add-ons that are not models on their own"><input type="checkbox" id="cv-mlora" checked> hide LoRAs</label><select id="cv-ms" class="module-select" title="Order of the rows"><option value="name">by name</option><option value="size">largest first</option><option value="copies">fewest copies first</option></select><span class="grow"></span><button type="button" class="ui-btn cv-small" id="cv-loc">places</button></div>"""
    js = """<script>(function () {
      var mb = document.getElementById('cv-mb'); if (!mb) return;
      var tb = mb.closest('table');
      var f = document.getElementById('cv-mf'), l = document.getElementById('cv-loc'), k = document.getElementById('cv-mk'), lo = document.getElementById('cv-mlora'), so = document.getElementById('cv-ms');
      var keep = function (id, el, prop) { try { var v = sessionStorage.getItem(id); if (v !== null) el[prop] = prop === 'checked' ? v === '1' : v; } catch (e) {} };
      keep('cv-models-q', f, 'value'); keep('cv-models-k', k, 'value'); keep('cv-models-lora', lo, 'checked'); keep('cv-models-s', so, 'value');
      function go() {
        var q = f.value.trim().toLowerCase(), kind = k.value, rows = Array.prototype.slice.call(mb.rows);
        try { sessionStorage.setItem('cv-models-q', f.value); sessionStorage.setItem('cv-models-k', kind); sessionStorage.setItem('cv-models-lora', lo.checked ? '1' : '0'); sessionStorage.setItem('cv-models-s', so.value); } catch (e) {}
        rows.forEach(function (r) {
          var ks = (r.dataset.kinds || '').split(' '), t = (r.textContent || '').toLowerCase();
          var lora = ks.length && ks.every(function (x) { return x.indexOf('lora') >= 0; });
          r.style.display = (!q || t.indexOf(q) >= 0) && (!kind || ks.indexOf(kind) >= 0) && !(lo.checked && lora) ? '' : 'none';
        });
        var by = so.value, num = function (r, a) { return parseFloat(r.dataset[a] || '0'); };
        rows.sort(function (a, b) { return by === 'size' ? num(b, 'size') - num(a, 'size') : by === 'copies' ? num(a, 'copies') - num(b, 'copies') : 0; });
        if (by !== 'name') rows.forEach(function (r) { mb.appendChild(r); });
      }
      [f, k, lo, so].forEach(function (el) { el.addEventListener(el === f ? 'input' : 'change', go); }); go();
      var cols = tb.querySelectorAll('tr > :nth-child(6)'), on = false;
      function places() {
        for (var i = 0; i < cols.length; i++) cols[i].style.display = on ? '' : 'none';
        l.textContent = on ? 'places: shown' : 'places: hidden';
      }
      l.addEventListener('click', function () { on = !on; places(); });
      places();
    })();</script>"""
    return f"""{poll}{await downloads_html(c.face["id"]) if admin else ""}
                <div class="row">{C._btn("Read the machines again", "res_sync", face=c.face["id"], title="Asks every machine for its models now")}<span class="grow"></span></div>
                {C._dim("Every model the machines hold, and where each copy is. A model is one file however many names it has. Which machine runs a piece of work is chosen when the work starts, among the machines that hold the model; who may use which is set under Access.")}
                {ctl}
                <div class="scroll-pane"><table class="cv-tbl">{head}{body}</table></div>{limits}{_naming_form(c.face["id"], rules) if admin else ""}{js}"""

async def _h_copy(request, payload, imr):
    """A copy (or a move: copy, check, then remove where it was) in the background, followed on this page."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin copies or moves models.", True), "cv-msg")
    R, mid, src, dst = C.AV.resources, payload["mid"], _p(payload["src"]), _p(payload["dst"])
    name = next(cp["name"] for cp in R.copies(mid) if cp["grp"] == src["id"])
    TESTS[f"model {name}"] = t = {"running": True, "notes": [f"""{"moving" if payload.get("move") else "copying"} to {dst.get("name") or dst["id"]}"""]}
    async def go():
        try:
            got = await R.copy(mid, src, name, dst, t["notes"].append)
            if payload.get("move") and got["copied"]: t["notes"].append(f"""removed where it was: {(await R.remove(mid, src, name))}""")
        except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
        t["running"] = False
    asyncio.create_task(go())
    return await C._refresh(request, imr, payload["face"], C._note(f"""{"Moving" if payload.get("move") else "Copying"} {C._esc(name)}: this page follows it."""))

async def _h_bring(request, payload, imr):
    """The window that brings a model to a machine: from which machine that holds it (each with where its copy sits), copied or moved."""
    R, names = C.AV.resources, {g["id"]: g["name"] for g in C.AV.resources.groups()}
    srcs, dst = [x for x in R.copies(payload["mid"]) if (next((g for g in R.groups() if g["id"] == x["grp"]), {}).get("kind") == "machine")], payload["dst"]
    opts = "".join(f"""<option value="{C._esc(x["grp"])}">{C._esc(names.get(x["grp"], x["grp"]))} - {C._esc(x.get("location") or "")}</option>""" for x in srcs)
    fid = "cv-bring-f"
    form = f"""<form id="{fid}" class="cv-form" onsubmit="return false"><label class="row"><span class="cv-dim">from</span><select name="src" class="module-select grow">{opts}</select></label><div class="row"><span class="grow"></span>{C._btn("Copy here", "res_copy", face=payload["face"], mid=payload["mid"], dst=dst, include="#" + fid, title="Sent straight from that machine; checked by size and header once there")}{C._btn("Move here", "res_copy", face=payload["face"], mid=payload["mid"], dst=dst, move="1", include="#" + fid, confirm="It is removed from where it was once the copy is checked.")}</div></form>"""
    return imr.oob(C.UI.modal("cv-bring", f"""{C._esc(next((x["name"] for x in srcs), payload["mid"]))} to {C._esc(names.get(dst, dst))}""", form, width="95%", max_width="36rem"), "cv-modal")

async def _h_info(request, payload, imr):
    """One model's window: each copy (machine, name there, where its files are), what the first readable header says, and renaming - one copy, or every copy to one name (names standardized across machines)."""
    R, names = C.AV.resources, {g["id"]: g for g in C.AV.resources.groups()}
    copies, facts, rows = R.copies(payload["mid"]), {}, []
    for cp in copies:
        g = names.get(cp["grp"], {})
        if not (g.get("provider") and C.AV.lib.has("provider", g["provider"])): rows.append(f"""<tr><td>{C._esc(g.get("name") or cp["grp"])}</td><td class="mono">{C._esc(cp["name"])}</td><td class="cv-dim">no connection to ask</td></tr>"""); continue
        try: got = await R.info(C.AV.lib.get("provider", g["provider"]), cp["name"])
        except C.PROV.ProviderError as e: got = {"error": str(e)}
        facts = facts or got.get("facts") or {}
        files = "<br>".join(f"""{C._esc(f["location"])}/{C._esc(f["path"])} ({f["size"] / 1e9:.2f} GB)""" for f in (got.get("where") or {}).get("files", [])) or C._esc(got.get("error") or got.get("facts_error") or "kept by its server")
        out = C._btn("Leave the Ollama store", "res_unstore", "ui-btn cv-small", face=payload["face"], mid=payload["mid"], grp=cp["grp"], name=cp["name"], confirm=f"""Make {cp["name"]} plain files on {g.get("name") or cp["grp"]} (gguf_local)? Its store entry is removed; Ollama is not needed for it afterwards. What Ollama kept beside the weights (its template, its settings) is left behind.""", title="Moves its file out of the Ollama store to gguf_local, where llama reads it directly (a vision projector beside it); a file another stored model shares is copied instead") if (got.get("where") or {}).get("unstore") and C._admin(request) else ""
        rows.append(f"""<tr><td>{C._esc(g.get("name") or cp["grp"])}</td><td class="mono">{C._esc(cp["name"])}{out}</td><td class="mono cv-dim" style="overflow-wrap:anywhere">{files}</td></tr>""")
    head = "".join(f"""<tr><td>{C._esc(k)}</td><td class="mono">{C._esc(v)}</td></tr>""" for k, v in facts.items() if k not in ("name", "size", "source", "files") and isinstance(v, (str, int, float)) and v not in ("", None)) or """<tr><td class="cv-dim">no header read (not a GGUF, or no machine answered)</td></tr>"""
    opts = "".join(C._option(cp["grp"] + "|" + cp["name"], f"""{names.get(cp["grp"], {}).get("name") or cp["grp"]}: {cp["name"]}""", "") for cp in copies)
    form = f"""<form id="cv-ren-f" class="cv-form" onsubmit="return false"><div class="row"><select name="which" class="module-select grow"><option value="*">every copy</option>{opts}</select><input name="to" class="module-select grow" placeholder="new name" value="{C._esc(copies[0]["name"] if copies else "")}" title="Letters, digits, . _ + - (and one : for an Ollama tag). The file (or Ollama tag) is renamed on that machine; programs then list it under the new name"></div><div class="row"><span class="grow"></span>{C._btn("Rename", "res_rename", face=payload["face"], mid=payload["mid"], include="#cv-ren-f", confirm="Rename it? Pipelines, pools or groups that name the old name must be pointed at the new one.")}</div></form>"""
    lab = next((v for cp in copies if (v := C.AV.resources.naming().get("names", {}).get(cp["name"]))), {})
    label = f"""<form id="cv-lab-f" class="cv-form" onsubmit="return false"><div class="row"><input name="base" class="module-select grow" placeholder="what it is called here, e.g. qwen3.8-9b" value="{C._esc(lab.get("base", ""))}" title="The name it is shown and chosen by in the portal (Models, every choice of a model). The files keep their own names, so where it came from stays traceable."><input name="variant" class="module-select" style="width:8em" placeholder="variant, e.g. Q6_K" value="{C._esc(lab.get("variant", ""))}"></div><div class="row"><span class="cv-dim grow">Every copy's name ({C._esc(", ".join(sorted({cp["name"] for cp in copies})))}) gets this label; empty both to take it off.</span>{C._btn("Label it", "res_label", face=payload["face"], mid=payload["mid"], include="#cv-lab-f")}</div></form>""" if C._admin(request) else ""
    body = f"""<div id="cv-ren-msg"></div><table class="cv-tbl"><tr><th>machine</th><th>name there</th><th>its files</th></tr>{"".join(rows)}</table><b>Header</b><table class="cv-tbl">{head}</table><b>Label (the files keep their names)</b>{label}<b>Rename the files</b>{form}{C._dim("Facts that do not belong in a name (quantization, who made it) are read from the header and the naming rules (Advanced, below the table), so a short name loses nothing.")}"""
    return imr.oob(C.UI.modal("cv-res-info", "Model", body, width="95%", max_width="48rem"), "cv-modal")

async def _h_label(request, payload, imr):
    """A model's label: the naming rules' exact entry ("names") for every name its copies have - what Settings, Models and every choice of a model show; the files are not touched. Both fields empty: the entries go."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin labels models.", True), "cv-ren-msg")
    R = C.AV.resources
    rules, base, variant = R.naming(), (payload.get("base") or "").strip(), (payload.get("variant") or "").strip()
    names = {cp["name"] for cp in R.copies(payload["mid"])}
    R.set_naming({**rules, "names": {**{k: v for k, v in (rules.get("names") or {}).items() if k not in names}, **({n: {"base": base, **({"variant": variant} if variant else {})} for n in names} if base else {})}})
    return imr.oob(C._note(f"""{"Labelled " + base + (" " + variant if variant else "") if base else "Label taken off"} for {", ".join(sorted(names))}. Read the machines again (or reopen the page) to see it in the table; choices of a model show it at once."""), "cv-ren-msg")

async def _h_rename(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin renames models.", True), "cv-ren-msg")
    R, names, to = C.AV.resources, {g["id"]: g for g in C.AV.resources.groups()}, (payload.get("to") or "").strip()
    targets = [(cp["grp"], cp["name"]) for cp in R.copies(payload["mid"])] if payload.get("which") in (None, "", "*") else [tuple(payload["which"].split("|", 1))]
    said = []
    for grp, name in targets:
        g = names.get(grp, {})
        if name == to: continue
        try: said.append(f"""{g.get("name") or grp}: {(await R.rename(C.AV.lib.get("provider", g["provider"]), name, to))["to"]}""")
        except (C.PROV.ProviderError, KeyError) as e: said.append(f"""{g.get("name") or grp}: not renamed - {e}""")
    return imr.oob(C._note("Renamed. " + "; ".join(said) if said else "Nothing to rename: every copy has that name.", any("not renamed" in x for x in said)), "cv-ren-msg")

async def _h_unstore(request, payload, imr):
    """One copy taken out of its machine's Ollama store (Resources.unstore); the window is shown again with where it is now."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin moves model files.", True), "cv-ren-msg")
    g = next((x for x in C.AV.resources.groups() if x["id"] == payload["grp"]), {})
    try: await C.AV.resources.unstore(C.AV.lib.get("provider", g["provider"]), payload["name"])
    except (C.PROV.ProviderError, KeyError) as e: return imr.oob(C._note(f"""{payload["name"]}: not moved - {e}""", True), "cv-ren-msg")
    return await _h_info(request, payload, imr)   # the same file is the same model (its id is its header and size), now listed under its file name

async def _h_remove(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin removes models.", True), "cv-msg")
    try: got = await C.AV.resources.remove(payload["mid"], _p(payload["grp"]), payload["name"], bool(payload.get("last")))
    except C.PROV.ProviderError as e: got = {"removed": False, "why": str(e)}
    return await C._refresh(request, imr, payload["face"], C._note(f"""Removed: {got["freed_gb"]} GB freed.""" if got["removed"] else f"""Not removed: {got["why"]}""", not got["removed"]))

async def _h_pull(request, payload, imr):
    """A model pulled onto a server that fetches its own, in the background, followed on this page."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin brings models onto a server.", True), "cv-msg")
    p, name = _p(payload["grp"]), payload.get("model", "").strip()
    if not name: return imr.oob(C._note("Name the model to pull.", True), "cv-msg")
    TESTS[f"model {name}"] = t = {"running": True, "notes": [f"""{p.get("name") or p["id"]} is pulling it; nothing is shown of how far it is until it is done"""]}
    async def go():
        try: t["notes"].append(f"""done: {await C.AV.resources.pull(p, name)}""")
        except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
        t["running"] = False
    PULLS.add(task := asyncio.create_task(go()))
    task.add_done_callback(PULLS.discard)
    return await C._refresh(request, imr, payload["face"], C._note(f"Pulling {C._esc(name)}: this page follows it."))

async def _h_sync(request, payload, imr):
    C.PROV.forget()   # asked by a person: machines that were silent are tried again now
    got = await C.AV.resources.sync()
    bad = [f"""{r["group"]}: {r["error"]}""" for r in got if r.get("error")]
    return await C._refresh(request, imr, payload["face"], C._note("Read again." + (" Not reached: " + "; ".join(bad) if bad else ""), bool(bad)))

def _models_on(p: dict) -> list:
    """The chat models on a machine that are on (not standby), as (name there, model id)."""
    return [(cp["name"], m["id"]) for m in C.AV.resources.models() for cp in m["copies"] if cp["grp"] == p["id"] and "chat" in m["facts"].get("capabilities", []) and not cp["location"]]

async def _run(p: dict, among: list = None, models: bool = True):
    """One machine's tests, followed in TESTS; a stop keeps what was measured before it. among: only the paths to these machines; models False: no model is loaded (paths and the machine only)."""
    ms = _models_on(p) if models else []
    TESTS[p["id"]] = t = {"running": True, "notes": [f"""testing: the machine, its paths{f" to {len(among)} other(s)" if among is not None else ""}, {len(ms)} model(s)"""]}
    try: t["result"] = await C.AV.resources.characterize(p, ms, t["notes"].append, among)
    except C.PROV.ProviderError as e: t["notes"].append(f"stopped: {e}")
    t["running"] = False

async def _h_forget(request, payload, imr):
    """Test results cleared, of one machine or of all (Resources.forget)."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin clears test results.", True), "cv-msg")
    n = C.AV.resources.forget(payload.get("grp") or "")
    return await C._refresh(request, imr, payload["face"], C._note(f"""Cleared {n} test figure(s){" of " + C._esc(payload["grp"]) if payload.get("grp") else ""}."""))

async def _h_test(request, payload, imr):
    """A machine's tests started in the background; the page follows them."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin starts tests: they load models on the machine.", True), "cv-msg")
    p = C.AV.lib.get("provider", payload["pid"])
    asyncio.create_task(_run(p))
    return await C._refresh(request, imr, payload["face"], C._note(f"""Testing {C._esc(p.get("name") or p["id"])}: this page follows it."""))

async def _h_test_all(request, payload, imr):
    """Every machine that speaks the node contract, one after another, in the background - or only those ticked ("ids"), with the paths among them alone, and their models only when asked ("models")."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin starts tests: they load models on the machines.", True), "cv-msg")
    ids = payload.get("ids") or []
    ids = [ids] if isinstance(ids, str) else ids
    ps = [p for p in C.AV.lib.list("provider") if not p.get("speaks") and (not ids or p["id"] in ids)]
    if ids and len(ps) < 2: return imr.oob(C._note("Tick at least two machines: the test measures the paths between them.", True), "cv-msg")
    for p in ps: TESTS[p["id"]] = {"running": True, "notes": ["waiting its turn"]}
    async def go():
        await C.AV.resources.sync()
        for p in ps: await (_run(p, [q["id"] for q in ps], bool(payload.get("models"))) if ids else _run(p))
    asyncio.create_task(go())
    return await C._refresh(request, imr, payload["face"], C._note(f"""Testing {len(ps)} machine(s) one after another: this page follows them."""))

# --- Downloads onto nodes (their downloads program: asset kind "download") ---

async def _dl_nodes() -> list:
    """[(group, provider, its downloads or None when the program is not active there, error)] for every node."""
    async def one(g):
        p = _p(g["provider"])
        try:
            if "download" not in (await C.PROV.manage(p, "GET")).get("kinds", {}): return (g, p, None, "")
            return (g, p, (await C.PROV.manage(p, "GET", "download"))["assets"], "")
        except C.PROV.ProviderError as e: return (g, p, None, str(e))
    return await asyncio.gather(*(one(g) for g in C.AV.resources.groups() if g["kind"] == "machine"))

def _dl_row(face_id: str, g: dict, p: dict, d: dict) -> str:
    bar = f"""<progress max="{d["size"]}" value="{d["got"]}" style="width:8em"></progress> {d["got"] / 1e9:.2f} of {d["size"] / 1e9:.2f} GB""" if d.get("live") and d.get("size") else C._esc(d["status"])
    again = C._btn("continue", "res_dl", "ui-btn cv-small", face=face_id, pid=p["id"], name=d["name"], url=d["url"], location=d["location"], folder=d["folder"], title="Asks for it again: it continues from where it stopped") if not d.get("live") and d["status"] not in ("here",) else ""
    forget = C._btn("forget", "res_dl_rm", "ui-btn cv-small", face=face_id, pid=p["id"], name=d["name"], forget="1", title="Takes this line off the list only: the file stays where it is, as any other model file (Models above)") if not d.get("live") else ""
    rm = C._btn("stop and delete the file" if d.get("live") else "delete the file", "res_dl_rm", "ui-btn cv-small cv-danger", face=face_id, pid=p["id"], name=d["name"], confirm=f"""Delete the FILE {d["name"]} from {g["name"]} ({d["path"]})? The model file this download brought is removed{", and the download stopped" if d.get("live") else ""}. To clear only this line and keep the file, use forget.""") if d["status"] != "the file is gone from its place" else ""
    return f"""<tr><td>{C._esc(g["name"])}</td><td class="mono" style="overflow-wrap:anywhere" title="{C._esc(d["url"])}">{C._esc(d["name"])}</td><td class="mono cv-dim">{C._esc(d["location"])}/{C._esc(d["folder"])}</td><td>{bar}</td><td>{again}{forget}{rm}</td></tr>"""

async def downloads_html(face_id: str) -> str:
    """Bringing a file onto a node from an address, and every download the nodes hold, followed every 3 s while one is under way."""
    nodes = await _dl_nodes()
    on, off = [(g, p) for g, p, ds, _ in nodes if ds is not None], [(g, e) for g, p, ds, e in nodes if ds is None]
    live = any(d.get("live") or d["status"] == "starting" for _, _, ds, _ in nodes for d in ds or [])
    rows = "".join(_dl_row(face_id, g, p, d) for g, p, ds, _ in nodes for d in ds or [])
    poll = f"""hx-get="{C._P}/downloads?face={C.quote(face_id)}" hx-trigger="every 3s" hx-swap="outerHTML" """ if live else ""
    opts = "".join(f"""<option value="{C._esc(p["id"])}">{C._esc(g["name"])}</option>""" for g, p in on)
    form = f"""<form id="cv-dl-f" class="row" style="flex-wrap:wrap" onsubmit="return false"><select name="pid" class="module-select">{opts}</select><input name="url" class="module-select grow" placeholder="https://huggingface.co/<owner>/<repository>/resolve/main/<file>.gguf" title="The file itself. The Catalog (Asio) finds models and fills this in with Get."><input name="name" class="module-select" placeholder="name there (the file's own)" title="Empty: the file's name in the address"><input name="location" class="module-select" style="width:8em" value="text_models" title="One of the machine's places: text_models, image_models, audio_models, models"><input name="folder" class="module-select" style="width:8em" value="gguf_local" title="The folder inside it the program looks in: gguf_local for GGUF models"><input name="token" type="password" class="module-select" style="width:8em" placeholder="access token" title="Only for a repository that asks for one: used for this download, not kept">{C._btn("Download", "res_dl", "ui-btn", face=face_id, include="#cv-dl-f")}</form>""" if on else ""
    why = "; ".join(f"""{g["name"]}: {"not reached - " + e if e else "its downloads program is not active (Settings, Machines, " + g["name"] + ", its programs: activate downloads)"}""" for g, e in off)
    ended = "".join(C._btn(f"""forget finished on {g["name"]}""", "res_dl_rm", "ui-btn cv-small", face=face_id, pid=p["id"], done="1", title="Takes off the list every download of this machine whose file is here or gone; the files stay (stopped or failed ones stay listed, to continue or delete)") for g, p, ds, _ in nodes if any(not d.get("live") and d["status"] in ("here", "the file is gone from its place") for d in ds or []))
    table = f"""<div class="row" style="flex-wrap:wrap">{ended}</div><div class="scroll-pane"><table class="cv-tbl"><tr><th>machine</th><th>file</th><th>into</th><th>state</th><th></th></tr>{rows}</table></div>""" if rows else ""
    return f"""<div id="cv-dl" {poll}><div class="sec">Bring a model onto a machine</div>{C._dim("The machine fetches the file itself from the address (an outside server: the address given, nothing else), continuing a download that stopped; nothing that exists is replaced. Ollama servers fetch their own: Pull, above.")}{form}{C._dim(C._esc(why))}{table}</div>"""

def _dl_name(url: str) -> str: return unquote(PurePosixPath(urlsplit(url).path).name)

async def _h_dl(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin downloads onto machines.", True), "cv-msg")
    url = str(payload.get("url") or "").strip()
    name = str(payload.get("name") or "").strip() or _dl_name(url)
    if not (url and payload.get("pid")): return imr.oob(C._note("Give the address of the file and the machine.", True), "cv-msg")
    try: await C.PROV.manage(_p(payload["pid"]), "PUT", "download", name, {"url": url, **{k: str(payload.get(k) or "").strip() for k in ("location", "folder", "token") if str(payload.get(k) or "").strip()}})
    except C.PROV.ProviderError as e: return imr.oob(C._note(str(e), True), "cv-msg")
    return _both(imr, C._note(f"Downloading {name}: its progress shows below."), await downloads_html(payload["face"]))

async def _h_dl_rm(request, payload, imr):
    """A download's line forgotten (forget: the file stays), every finished line of a machine forgotten (done: its downloads whose file is here, or gone), or the download stopped and its file deleted."""
    if not C._admin(request): return imr.oob(C._note("Only a portal admin deletes downloads.", True), "cv-msg")
    p, said = _p(payload["pid"]), []
    try:
        names = [d["name"] for d in (await C.PROV.manage(p, "GET", "download"))["assets"] if not d.get("live") and (d["status"] in ("here", "the file is gone from its place") or payload.get("all_ended"))] if payload.get("done") else [payload["name"]]
        for n in names:
            await C.PROV.manage(p, "DELETE", "download", n, query="?confirm=1" + ("&forget=1" if payload.get("forget") or payload.get("done") else ""))
            said.append(n)
    except C.PROV.ProviderError as e: return _both(imr, C._note(f"""{str(e)}{" (done before it: " + ", ".join(said) + ")" if said else ""}""", True), await downloads_html(payload["face"]))
    how = "Forgot (files kept)" if payload.get("forget") or payload.get("done") else "Deleted the file of"
    return _both(imr, C._note(f"""{how}: {", ".join(said) or "nothing to forget"}."""), await downloads_html(payload["face"]))

def _both(imr, note: str, dl: str):
    imr.oob(note, "cv-msg")
    return imr.oob(dl, "cv-dl", swap="outerHTML")

# --- Naming rules (Aviary resources.py NAMING) ---

def _naming_form(face_id: str, rules: dict) -> str:
    shown = json.dumps({k: v for k, v in rules.items() if k != "_doc"}, indent=1)
    return f"""<details class="sec"><summary class="cv-dim">Advanced: how models are named</summary>{C._dim(C._esc(rules["_doc"]) + " prefixes: taken off the front; owner: true drops the part before the last /; drop: words taken out anywhere (any case); lower: base names in lower case; names: one name set exactly, e.g. {&quot;bge-m3:latest&quot;: {&quot;base&quot;: &quot;bge-m3&quot;, &quot;variant&quot;: &quot;F16&quot;}}.")}<form id="cv-naming-f" onsubmit="return false"><textarea name="rules" class="module-select mono" rows="10" style="width:100%">{C._esc(shown)}</textarea>{C._btn("Save the naming rules", "res_naming", face=face_id, include="#cv-naming-f")}</form></details>"""

async def _h_naming(request, payload, imr):
    if not C._admin(request): return imr.oob(C._note("Only a portal admin changes the naming rules.", True), "cv-msg")
    try: rules = json.loads(payload.get("rules") or "{}")
    except json.JSONDecodeError as e: return imr.oob(C._note(f"Not saved: the rules are not JSON ({e}).", True), "cv-msg")
    if not isinstance(rules, dict): return imr.oob(C._note("Not saved: the rules are one JSON object.", True), "cv-msg")
    if bad := [k for k in rules if k not in C.AV.resources.naming()]: return imr.oob(C._note(f"""Not saved: unknown keys {", ".join(bad)}.""", True), "cv-msg")
    C.AV.resources.set_naming(rules)
    return await C._refresh(request, imr, payload["face"], C._note("Naming rules saved."))
