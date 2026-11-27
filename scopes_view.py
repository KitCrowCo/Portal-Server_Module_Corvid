"""scopes_view.py - who may do what, managed: the portal's accounts (people and AI alike), the sub-users made under them, the grants between them, who owns what, and a check that answers "may X do this?" with the reason.
The rules live in the portal core (scope.py, the service "scope"); this panel only shows and changes them through it, so every change is checked there the same way as anywhere else."""
import time

C = None   # corvid.py's live view, given to init
THING_KINDS = ("pool", "pipeline", "machine", "module", "tool", "file", "library")   # what a grant names before the colon; a grant's pattern may use * and covers everything under a path

def init(c):
    global C
    C = c
    C.IM.scripts.update({f"corvid_scope_{n}": [fn] for n, fn in (("grant", _h_grant), ("revoke", _h_revoke), ("owners", _h_owners), ("kind", _h_kind), ("end", _h_end), ("check", _h_check))})

def S() -> dict: return C.ENV["services"]["scope"]

# --- Panel ---
async def p_scopes(c) -> str:
    return f"""<div id="cv-scopes">{_body(C._user(c.request))}</div>"""

def _things() -> list:
    """Things a grant can name, offered while typing: pools, pipelines, machines, modules, the tools that act on others' work, and the top of the file tree."""
    lib = C.AV.lib
    return sorted({*(f"""pool:{p["id"]}""" for p in lib.list("pool")), *(f"""pipeline:{p["id"]}""" for p in lib.list("pipeline")), *(f"""machine:{p.get("name") or p["id"]}""" for p in lib.list("provider")), "pool:*", "pipeline:*", "machine:*", "tool:pause", "tool:stop", "tool:*", "file:/", "library:*"})

def _body(me: str) -> str:
    sc = S()
    accts, admin = sc["accounts"](), sc["admin"](me)
    who = sorted(accts) + sorted(sc["subs"]())
    acct_rows = "".join(_acct_row(n, a, sc, admin) for n, a in sorted(accts.items()))
    gs = [g for g in sc["grants"]() if admin or me in (g["to"], g["by"]) or g["to"].startswith(f"{me}/")]
    grant_rows = "".join(_grant_row(g) for g in sorted(gs, key=lambda g: (g["to"], g["on"]))) or """<tr><td colspan="8" class="cv-dim">no grants yet: an account other than a primary user may do only what it owns</td></tr>"""
    opts = lambda xs: "".join(f"""<option value="{C._esc(x)}">{C._esc(x)}</option>""" for x in xs)
    things = f"""<datalist id="cv-scope-things">{opts(_things())}</datalist>"""
    give = f"""<form id="cv-scope-give" class="row" onsubmit="return false"><select name="to" class="module-select">{opts(who)}</select><input name="on" list="cv-scope-things" class="grow" placeholder="what: kind:path, e.g. pool:ingest, file:/data/notes, pipeline:*"><select name="act" class="module-select">{opts(sc["acts"])}</select><label title="May pass this on to others, its own sub-users included"><input type="checkbox" name="may_grant" value="1"> may pass on</label><input name="hours" type="number" min="0" step="any" style="width:6em" placeholder="hours" title="Ends after this many hours; empty: no end"><input name="note" placeholder="why (shown with the grant)">{C._btn("Grant", "scope_grant", include="#cv-scope-give")}</form>"""
    owned = "".join(f"""<tr><td class="mono">{C._esc(t)}</td><td>{C._esc(", ".join(o))}</td></tr>""" for t, o in sorted(sc["owned"]().items())) or """<tr><td colspan="2" class="cv-dim">no recorded owners: a primary user decides about everything</td></tr>"""
    own_form = f"""<form id="cv-scope-own" class="row" onsubmit="return false"><input name="thing" list="cv-scope-things" class="grow" placeholder="what (pattern)"><input name="owners" class="grow" placeholder="owners, comma separated (empty: none recorded)">{C._btn("Set owners", "scope_owners", include="#cv-scope-own", confirm="Change who owns this? Owners decide about it and must agree to anything that cannot be undone.")}</form>"""
    check = f"""<form id="cv-scope-chk" class="row" onsubmit="return false"><select name="who" class="module-select">{opts(who)}</select><select name="act" class="module-select">{opts(sc["acts"])}</select><input name="thing" list="cv-scope-things" class="grow" placeholder="what">{C._btn("May it?", "scope_check", include="#cv-scope-chk")}</form><div id="cv-scope-said"></div>"""
    return f"""{things}{C._dim("The same rules for people and AI. A primary user (admin) may do everything. Any other account may do what it owns and what it was granted. A sub-user (an AI task, a person working through the AI in Athena) may only do what it was granted and what every account it is bound by may. Acts: see < use < edit (change without asking) < own (decide, remove, grant); each includes the ones before.")}
<b>Accounts and their sub-users</b><table class="cv-tbl"><tr><th>account</th><th>kind</th><th>role</th><th>sub-users</th></tr>{acct_rows}</table>
<b>Grants</b><table class="cv-tbl"><tr><th>to</th><th>what</th><th>act</th><th>may pass on</th><th>given by</th><th>until</th><th>why</th><th></th></tr>{grant_rows}</table>{give}
<b>Owners</b><table class="cv-tbl"><tr><th>what</th><th>owned by</th></tr>{owned}</table>{own_form if admin else ""}
<b>Check</b>{check}"""

def _acct_row(name: str, a: dict, sc: dict, admin: bool) -> str:
    subs = sc["subs"](name)
    kinds = "".join(f"""<option value="{k}"{" selected" if a["kind"] == k else ""}>{k}</option>""" for k in ("person", "ai"))
    kind = f"""<form class="row" onsubmit="return false"><input type="hidden" name="name" value="{C._esc(name)}"><select name="kind" class="module-select" hx-trigger="change" {C._act("scope_kind", include="closest form")}>{kinds}</select></form>""" if admin else C._esc(a["kind"])
    sub = " ".join(f"""<span class="chip" title="{C._esc(s.get("note") or "")}{" | also bound by " + C._esc(", ".join(s["also"])) if s.get("also") else ""}">{C._esc(i.split("/", 1)[1])}{" (kept)" if s["kept"] else ""} {C._btn("&#x2715;", "scope_end", cls="ui-btn cv-small", title="End this sub-user and its grants", sid=i, confirm=f"End {i} and every grant it holds?")}</span>""" for i, s in sorted(subs.items()))
    return f"""<tr><td class="mono">{C._esc(name)}</td><td>{kind}</td><td>{C._esc(a["role"])}</td><td>{sub or '<span class="cv-dim">none</span>'}</td></tr>"""

def _grant_row(g: dict) -> str:
    until, ask = time.strftime("%Y-%m-%d %H:%M", time.localtime(g["until"])) if g.get("until") else "no end", f"""End the grant of {g["act"]} on {g["on"]} to {g["to"]}?"""
    return f"""<tr{"" if g["live"] else ' class="cv-dim"'}><td class="mono">{C._esc(g["to"])}</td><td class="mono">{C._esc(g["on"])}</td><td>{g["act"]}</td><td>{"yes" if g.get("may_grant") else "-"}</td><td>{C._esc(g["by"])}</td><td>{until}{"" if g["live"] else " (ended)"}</td><td class="cv-dim">{C._esc(g.get("note") or "")}</td><td>{C._btn("&#x2715;", "scope_revoke", cls="ui-btn cv-small", title="End this grant", gid=g["id"], confirm=ask)}</td></tr>"""

# --- Intent handlers: every change goes through the core, which refuses with its reason ---
def _redraw(imr, me: str, said: str = "", bad: bool = False): return imr.oob(_body(me), "cv-scopes").oob(C._note(said, bad), "cv-msg") if said else imr.oob(_body(me), "cv-scopes")

def _do(request, imr, fn, ok: str):
    me = C._user(request)
    try: fn(me)
    except (PermissionError, ValueError, KeyError) as e: return _redraw(imr, me, str(e), True)
    return _redraw(imr, me, ok)

async def _h_grant(request, payload, imr):
    h = float(payload.get("hours") or 0)
    return _do(request, imr, lambda me: S()["grant"](me, payload["to"], str(payload.get("on") or "").strip(), payload["act"], may_grant=bool(payload.get("may_grant")), until=time.time() + h * 3600 if h else None, note=str(payload.get("note") or "")), f"""Granted {payload["act"]} on {payload.get("on")} to {payload["to"]}.""")

async def _h_revoke(request, payload, imr): return _do(request, imr, lambda me: S()["revoke"](me, payload["gid"]), "Grant ended.")
async def _h_owners(request, payload, imr): return _do(request, imr, lambda me: S()["set_owners"](me, str(payload["thing"]).strip(), [o.strip() for o in str(payload.get("owners") or "").split(",") if o.strip()]), f"""Owners of {payload["thing"]} set.""")
async def _h_kind(request, payload, imr): return _do(request, imr, lambda me: S()["set_kind"](me, payload["name"], payload["kind"]), f"""{payload["name"]} is now a {payload["kind"]} account.""")
async def _h_end(request, payload, imr): return _do(request, imr, lambda me: S()["end"](me, payload["sid"]), f"""{payload["sid"]} ended.""")

async def _h_check(request, payload, imr):
    ok, how = S()["why"](payload["who"], str(payload.get("thing") or "").strip(), payload["act"])
    return imr.oob(C._note(f"""{"Yes" if ok else "No"}: {how}""", not ok), "cv-scope-said")
