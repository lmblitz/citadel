import json
import logging
import os
import secrets
import sys
import time
from collections import deque
from datetime import datetime, timezone

import discord
from aiohttp import web

STARTED = time.time()

LOGS = deque(maxlen=200)
COMMANDS = deque(maxlen=50)

_LOG_HANDLER = None


def _uptime():
    total = int(time.time() - STARTED)
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h}h {m}m {s}s"


class _LogHandler(logging.Handler):
    def emit(self, record):
        try:
            LOGS.append(
                {
                    "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
            )
        except Exception:
            pass


def _wire_logging():
    global _LOG_HANDLER
    if _LOG_HANDLER is None:
        _LOG_HANDLER = _LogHandler()
        logging.getLogger().addHandler(_LOG_HANDLER)


def _authed(request):
    return request.cookies.get("citadel_auth") == request.app["secret"]


def _read_files():
    files = {}
    for name in ("warnings.json", "honeypot.json", "tournaments.json"):
        try:
            with open(name, encoding="utf-8") as f:
                files[name] = json.load(f)
        except Exception:
            pass
    return files


async def _on_command(ctx):
    COMMANDS.append(
        {
            "time": time.strftime("%H:%M:%S"),
            "name": ctx.command.qualified_name if ctx.command else "unknown",
            "author": str(ctx.author),
            "channel": getattr(getattr(ctx, "channel", None), "name", "?"),
        }
    )


class _FakeMessage:
    def __init__(self, bot, channel, author, content):
        self.id = 0
        self.channel = channel
        self.guild = channel.guild
        self.author = author
        self.content = content
        self.created_at = datetime.now(timezone.utc)
        self.reference = None
        self.mentions = []
        self.role_mentions = []
        self.channel_mentions = []
        self.mention_everyone = False
        self.type = discord.MessageType.default

    def __getattr__(self, name):
        return None


async def _run_command(bot, text):
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty command."}
    try:
        channel_id = int(os.getenv("DASHBOARD_CHANNEL_ID", "0"))
        owner_id = int(os.getenv("DASHBOARD_OWNER_ID", "0"))
    except ValueError:
        channel_id = 0
        owner_id = 0
    channel = bot.get_channel(channel_id) if channel_id else None
    if channel is None:
        return {
            "ok": False,
            "error": "Set DASHBOARD_CHANNEL_ID to a valid channel to use Run Command.",
        }
    author = channel.guild.get_member(owner_id) if owner_id else None
    if author is None:
        return {
            "ok": False,
            "error": "Set DASHBOARD_OWNER_ID to your user id so commands run as you.",
        }
    fake = _FakeMessage(bot, channel, author, text)
    ctx = await bot.get_context(fake)
    if ctx.command is None:
        return {"ok": False, "error": f"Unknown command: {text.split()[0]}."}
    await bot.invoke(ctx)
    return {
        "ok": True,
        "command": text,
        "result": "Executed — check the configured channel for the reply.",
    }


def _exec_self():
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def _index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def _api_login(request):
    data = await request.json()
    code = str(data.get("code", ""))
    if secrets.compare_digest(code, request.app["code"]):
        resp = web.json_response({"ok": True})
        resp.set_cookie(
            "citadel_auth",
            request.app["secret"],
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )
        return resp
    return web.json_response({"ok": False, "error": "Wrong code."}, status=401)


async def _api_logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie("citadel_auth")
    return resp


async def _api_status(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    return web.json_response(
        {
            "ok": True,
            "online": bot.is_ready(),
            "uptime": _uptime(),
            "latency": round(bot.latency * 1000, 1),
            "guilds": len(bot.guilds),
            "members": sum(g.member_count or 0 for g in bot.guilds),
            "cogs": sorted(bot.cogs.keys()),
        }
    )


async def _api_logs(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    return web.json_response(
        {"ok": True, "logs": list(LOGS)[::-1], "commands": list(COMMANDS)[::-1]}
    )


async def _api_data(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    return web.json_response({"ok": True, "files": _read_files()})


async def _api_action(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    data = await request.json()
    action = data.get("action")
    if action == "restart":
        bot.loop.call_later(1.0, _exec_self)
        return web.json_response({"ok": True, "message": "Restarting in 1 second..."})
    if action == "sync":
        try:
            synced = await bot.tree.sync()
            return web.json_response(
                {"ok": True, "message": f"Synced {len(synced)} command(s)."}
            )
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})
    if action == "run":
        result = await _run_command(bot, str(data.get("command", "")))
        return web.json_response(result)
    return web.json_response({"ok": False, "error": "Unknown action."})


async def start(bot):
    try:
        port = int(os.getenv("DASHBOARD_PORT", "9110"))
    except ValueError:
        port = 9110
    if not port:
        print("Dashboard disabled (DASHBOARD_PORT=0).")
        return

    _wire_logging()
    bot.add_listener(_on_command, "on_command")

    app = web.Application()
    app["bot"] = bot
    app["secret"] = secrets.token_hex(16)
    app["code"] = os.getenv("DASHBOARD_CODE", "911")
    app.router.add_get("/", _index)
    app.router.add_post("/api/login", _api_login)
    app.router.add_post("/api/logout", _api_logout)
    app.router.add_get("/api/status", _api_status)
    app.router.add_get("/api/logs", _api_logs)
    app.router.add_get("/api/data", _api_data)
    app.router.add_post("/api/action", _api_action)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Dashboard running on http://0.0.0.0:{port} (code: {app['code']})")


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Citadel Dashboard</title>
<style>
:root{--bg:#0e1116;--card:#171b22;--line:#262c36;--text:#e6e9ef;--muted:#8b93a3;--acc:#5865f2;--ok:#23a55a;--warn:#f0b232;--err:#f23f43}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;min-height:100vh}
a{color:var(--acc)}
header{padding:16px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px;flex-wrap:wrap;background:var(--card)}
header h1{font-size:18px;font-weight:700;letter-spacing:.3px}
header h1 span{color:var(--acc)}
#topstats{margin-left:auto;display:flex;gap:14px;font-size:13px;color:var(--muted)}
#topstats b{color:var(--text);font-weight:600}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}
.dot.off{background:var(--err)}
nav{display:flex;gap:6px;padding:14px 24px 0}
nav button{background:none;border:none;color:var(--muted);padding:8px 16px;font-size:14px;cursor:pointer;border-bottom:2px solid transparent}
nav button.active{color:var(--text);border-bottom-color:var(--acc)}
main{padding:20px 24px;max-width:1000px}
.tab{display:none}
.tab.active{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h3{font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:8px}
.card .num{font-size:26px;font-weight:700}
.card .sub{font-size:12px;color:var(--muted);margin-top:4px}
#coglist{display:flex;flex-wrap:wrap;gap:8px}
#coglist span{background:#20242c;border:1px solid var(--line);padding:4px 10px;border-radius:999px;font-size:12px;font-family:ui-monospace,Consolas,monospace}
.logline{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;padding:6px 10px;border-left:3px solid var(--line);background:#11151b;margin-bottom:6px;border-radius:0 6px 6px 0;overflow-wrap:anywhere}
.logline .t{color:var(--muted);margin-right:8px}
.logline .lv{display:inline-block;min-width:52px;margin-right:8px;font-weight:700}
.lv.INFO{color:var(--ok)} .lv.WARNING{color:var(--warn)} .lv.ERROR,.lv.CRITICAL{color:var(--err)} .lv.DEBUG{color:var(--muted)}
.cmd{display:flex;gap:10px;padding:8px 10px;background:#11151b;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;font-size:13px}
.cmd .n{font-family:ui-monospace,Consolas,monospace;color:var(--acc);font-weight:600}
.cmd .m{margin-left:auto;color:var(--muted);font-size:12px}
button.btn{background:var(--acc);color:#fff;border:none;padding:10px 18px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
button.btn:hover{filter:brightness(1.1)}
button.btn.danger{background:var(--err)}
button.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}
input[type=text]{width:100%;background:#11151b;border:1px solid var(--line);color:var(--text);padding:10px 12px;border-radius:8px;font-size:14px;font-family:ui-monospace,Consolas,monospace}
label{display:block;font-size:12px;color:var(--muted);margin:14px 0 6px;text-transform:uppercase;letter-spacing:.6px}
#result{margin-top:12px;padding:10px 12px;border-radius:8px;font-size:13px;display:none}
#result.ok{display:block;background:#122019;border:1px solid var(--ok);color:var(--ok)}
#result.bad{display:block;background:#201212;border:1px solid var(--err);color:var(--err)}
pre{background:#0a0d12;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto;max-height:420px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;white-space:pre-wrap}
#login{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:50}
#login.hidden{display:none}
.loginbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;width:320px}
.loginbox h2{margin-bottom:6px}
.loginbox p{color:var(--muted);font-size:13px;margin-bottom:18px}
.loginbox input{width:100%;padding:12px;background:#11151b;border:1px solid var(--line);color:var(--text);border-radius:8px;font-size:18px;text-align:center;letter-spacing:6px}
.loginbox .btn{width:100%;margin-top:14px}
#logerr{color:var(--err);font-size:13px;margin-top:10px;min-height:18px}
</style>
</head>
<body>
<div id="login">
  <div class="loginbox">
    <h2>Citadel</h2>
    <p>Enter the access code</p>
    <input type="password" id="code" autocomplete="off">
    <button class="btn" id="loginbtn">Unlock</button>
    <div id="logerr"></div>
  </div>
</div>

<header>
  <h1>Citadel <span>Dashboard</span></h1>
  <div id="topstats">
    <span class="pill"><span class="dot" id="dot"></span><span id="st-online">...</span></span>
    <span>Latency <b id="st-lat">-</b> ms</span>
    <span>Uptime <b id="st-up">-</b></span>
    <button class="btn ghost" id="logout" style="padding:4px 12px;font-size:12px">Logout</button>
  </div>
</header>

<nav>
  <button data-tab="status" class="active">Status</button>
  <button data-tab="logs">Logs</button>
  <button data-tab="commands">Commands</button>
  <button data-tab="actions">Actions</button>
  <button data-tab="data">Data</button>
</nav>

<main>
  <div class="tab active" id="tab-status">
    <div class="grid">
      <div class="card"><h3>Guilds</h3><div class="num" id="guilds">-</div></div>
      <div class="card"><h3>Members</h3><div class="num" id="members">-</div></div>
      <div class="card"><h3>Latency</h3><div class="num" id="latency">-</div><div class="sub">milliseconds</div></div>
      <div class="card"><h3>Uptime</h3><div class="num" id="uptime" style="font-size:20px">-</div></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>Loaded Cogs</h3>
      <div id="coglist"></div>
    </div>
  </div>

  <div class="tab" id="tab-logs">
    <div class="card">
      <h3>Live Logs <span style="color:var(--muted)">(auto-refresh)</span></h3>
      <div id="logs"></div>
    </div>
  </div>

  <div class="tab" id="tab-commands">
    <div class="card">
      <h3>Recent Commands</h3>
      <div id="cmdlist"></div>
    </div>
  </div>

  <div class="tab" id="tab-actions">
    <div class="card">
      <h3>Actions</h3>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn danger" id="btn-restart">Restart Bot</button>
        <button class="btn" id="btn-sync">Sync Slash Commands</button>
      </div>
      <label for="runinput">Run a command (as owner, in the configured channel)</label>
      <input type="text" id="runinput" placeholder="?ping">
      <button class="btn" id="btn-run" style="margin-top:10px">Run</button>
      <div id="result"></div>
    </div>
  </div>

  <div class="tab" id="tab-data">
    <div class="card">
      <h3>Data Files</h3>
      <button class="btn ghost" id="btn-data" style="margin-bottom:12px">Refresh</button>
      <pre id="data"></pre>
    </div>
  </div>
</main>

<script>
let authed = false;

async function api(url, opts) {
  const r = await fetch(url, Object.assign({credentials: "same-origin"}, opts || {}));
  if (r.status === 401) { showLogin(); throw new Error("unauthorized"); }
  return r.json();
}

function showLogin() {
  authed = false;
  document.getElementById("login").classList.remove("hidden");
}
function hideLogin() {
  authed = true;
  document.getElementById("login").classList.add("hidden");
}

document.getElementById("loginbtn").onclick = async () => {
  const code = document.getElementById("code").value;
  const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
  const d = await r.json();
  if (d.ok) { hideLogin(); loadAll(); }
  else { document.getElementById("logerr").textContent = d.error || "Wrong code."; }
};
document.getElementById("code").onkeydown = (e) => { if (e.key === "Enter") document.getElementById("loginbtn").click(); };
document.getElementById("logout").onclick = async () => { await fetch("/api/logout", {method: "POST"}); location.reload(); };

const tabs = document.querySelectorAll("nav button");
tabs.forEach(t => t.onclick = () => {
  tabs.forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.getElementById("tab-" + t.dataset.tab).classList.add("active");
  if (t.dataset.tab === "data") loadData();
});

async function loadStatus() {
  try {
    const d = await api("/api/status");
    document.getElementById("st-online").textContent = d.online ? "Online" : "Offline";
    document.getElementById("dot").classList.toggle("off", !d.online);
    document.getElementById("st-lat").textContent = d.latency;
    document.getElementById("st-up").textContent = d.uptime;
    document.getElementById("guilds").textContent = d.guilds;
    document.getElementById("members").textContent = d.members;
    document.getElementById("latency").textContent = d.latency;
    document.getElementById("uptime").textContent = d.uptime;
    const cl = document.getElementById("coglist");
    cl.innerHTML = "";
    d.cogs.forEach(c => { const s = document.createElement("span"); s.textContent = c; cl.appendChild(s); });
  } catch (e) {}
}

function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }

async function loadLogs() {
  try {
    const d = await api("/api/logs");
    const box = document.getElementById("logs");
    box.innerHTML = d.logs.map(l =>
      '<div class="logline"><span class="t">' + esc(l.time) + '</span><span class="lv">' + esc(l.level) + '</span>' + esc(l.msg) + '</div>'
    ).join("");
    const cmds = document.getElementById("cmdlist");
    cmds.innerHTML = d.commands.map(c =>
      '<div class="cmd"><span class="n">' + esc(c.name) + '</span><span>' + esc(c.author) + '</span><span class="m">' + esc(c.time) + " in #" + esc(c.channel) + '</span></div>'
    ).join("");
  } catch (e) {}
}

async function loadData() {
  try {
    const d = await api("/api/data");
    const pre = document.getElementById("data");
    pre.textContent = Object.keys(d.files).length
      ? JSON.stringify(d.files, null, 2)
      : "(no data files found)";
  } catch (e) {}
}

function showResult(ok, text) {
  const r = document.getElementById("result");
  r.className = ok ? "ok" : "bad";
  r.textContent = text;
}

document.getElementById("btn-restart").onclick = async () => {
  if (!confirm("Restart the bot?")) return;
  const d = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "restart"})});
  showResult(d.ok, d.message || d.error);
};
document.getElementById("btn-sync").onclick = async () => {
  const d = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "sync"})});
  showResult(d.ok, d.message || d.error);
};
document.getElementById("btn-run").onclick = async () => {
  const cmd = document.getElementById("runinput").value;
  if (!cmd) return;
  const d = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "run", command: cmd})});
  showResult(d.ok, (d.result || d.error) + (d.command ? " [" + d.command + "]" : ""));
};
document.getElementById("btn-data").onclick = loadData;

async function loadAll() { loadStatus(); loadLogs(); }
setInterval(loadStatus, 5000);
setInterval(loadLogs, 2000);

loadStatus().then(() => { if (authed) loadAll(); });
</script>
</body>
</html>
"""
