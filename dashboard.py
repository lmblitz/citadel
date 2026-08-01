import json
import logging
import os
import secrets
import shutil
import sys
import time
from collections import deque
from datetime import datetime, timezone

import discord
from aiohttp import web
from discord.ext import commands

import archive
from commands.moderation import load_warnings

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


class _Tee:
    def __init__(self, original):
        self.original = original

    def write(self, text):
        try:
            if text.strip():
                LOGS.append(
                    {
                        "time": time.strftime("%H:%M:%S"),
                        "level": "CONSOLE",
                        "logger": "console",
                        "msg": text.rstrip(),
                    }
                )
        except Exception:
            pass
        return self.original.write(text)

    def flush(self):
        try:
            self.original.flush()
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


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _sysinfo():
    info = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "host_uptime": None,
        "loadavg": None,
        "memory": None,
        "disk": None,
        "files": [],
    }
    try:
        with open("/proc/uptime") as f:
            up = int(float(f.read().split()[0]))
        info["host_uptime"] = (
            f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m"
        )
    except Exception:
        pass
    try:
        with open("/proc/loadavg") as f:
            info["loadavg"] = f.read().split()[:3]
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f.read().splitlines()[:3]:
                key, _, val = line.partition(":")
                mem[key] = int(val.strip().split()[0]) // 1024
        info["memory"] = mem
    except Exception:
        pass
    try:
        usage = shutil.disk_usage(os.getcwd())
        info["disk"] = {
            "total": _fmt_bytes(usage.total),
            "used": _fmt_bytes(usage.used),
            "free": _fmt_bytes(usage.free),
        }
    except Exception:
        pass
    try:
        for name in sorted(os.listdir(os.getcwd())):
            if name.startswith("."):
                continue
            path = os.path.join(os.getcwd(), name)
            info["files"].append(
                {
                    "name": name,
                    "size": _fmt_bytes(os.path.getsize(path)) if os.path.isfile(path) else None,
                    "dir": os.path.isdir(path),
                }
            )
    except Exception:
        pass
    return info


GUILD_ID = 1532560145895395398
HIDDEN_ROLE_ID = 1532606512982261820
ADMIN_ROLE_ID = 1532569640318931015
MOD_ROLE_ID = 1532569676901646346
TRIAL_MOD_ROLE_ID = 1532571322125910176


def _guild(bot):
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        raise LookupError("Bot is not in the target guild.")
    return guild


def _rank_for(role_ids):
    if ADMIN_ROLE_ID in role_ids:
        return "Admin"
    if MOD_ROLE_ID in role_ids:
        return "Mod"
    if TRIAL_MOD_ROLE_ID in role_ids:
        return "Trial Mod"
    return None


async def _guild_info(bot):
    try:
        guild = _guild(bot)
    except LookupError as e:
        return {"error": str(e)}
    return {
        "name": guild.name,
        "id": guild.id,
        "owner": str(guild.owner) if guild.owner else "?",
        "members": guild.member_count or 0,
        "roles": len(guild.roles),
        "channels": len(guild.channels),
        "created": guild.created_at.strftime("%Y-%m-%d"),
    }


async def _list_bans(bot):
    try:
        guild = _guild(bot)
    except LookupError:
        return []
    bans = []
    async for entry in guild.bans(limit=None):
        bans.append(
            {
                "id": str(entry.user.id),
                "name": str(entry.user),
                "reason": entry.reason,
            }
        )
    return bans


async def _list_members(bot):
    try:
        guild = _guild(bot)
    except LookupError:
        return []
    warnings_data = load_warnings().get(str(guild.id), {})
    owner_id = guild.owner_id
    members = []
    for m in guild.members:
        if any(role.id == HIDDEN_ROLE_ID for role in m.roles):
            continue
        role_ids = {role.id for role in m.roles}
        rank = _rank_for(role_ids)
        members.append(
            {
                "id": str(m.id),
                "name": str(m),
                "bot": m.bot,
                "status": str(m.status),
                "avatar": m.display_avatar.url,
                "warnings": len(warnings_data.get(str(m.id), [])),
                "rank": rank,
                "owner": m.id == owner_id,
                "can_moderate": not (
                    m.bot or m.id == owner_id or ADMIN_ROLE_ID in role_ids
                ),
            }
        )
    members.sort(key=lambda m: m["name"].lower())
    return members


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


class _CaptureContext(commands.Context):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._captured = []

    async def send(self, content=None, *, embed=None, embeds=None, **kwargs):
        out = []
        if content:
            out.append(str(content))
        for e in ([embed] if embed else []) + (embeds or []):
            if e:
                title = e.title or ""
                desc = e.description or ""
                out.append((title + "\n" if title else "") + desc)
        if out:
            self._captured.append("\n".join(out))
        if self._echo:
            await super().send(content=content, embed=embed, embeds=embeds, **kwargs)
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
    if not channel_id:
        return {
            "ok": False,
            "error": "Set DASHBOARD_CHANNEL_ID to a valid channel to use Run Command.",
        }
    if not owner_id:
        return {
            "ok": False,
            "error": "Set DASHBOARD_OWNER_ID to your user id so commands run as you.",
        }
    try:
        channel = await bot.fetch_channel(channel_id)
    except Exception:
        return {
            "ok": False,
            "error": "Could not find the channel for DASHBOARD_CHANNEL_ID.",
        }
    try:
        author = await channel.guild.fetch_member(owner_id)
    except discord.HTTPException:
        return {
            "ok": False,
            "error": "DASHBOARD_OWNER_ID is not a member of that guild.",
        }
    fake = _FakeMessage(bot, channel, author, text)
    ctx = await bot.get_context(fake, cls=_CaptureContext)
    if ctx.command is None:
        return {"ok": False, "error": f"Unknown command: {text.split()[0]}."}
    ctx._echo = os.getenv("DASHBOARD_ECHO", "").lower() in ("1", "true", "yes")
    try:
        await ctx.command.invoke(ctx)
        output = "\n".join(ctx._captured) or "(no output)"
        return {"ok": True, "command": text, "result": output}
    except commands.CommandError as e:
        return {"ok": False, "command": text, "error": str(e)}
    except Exception as e:
        return {
            "ok": False,
            "command": text,
            "error": f"{type(e).__name__}: {e}",
        }


def _exec_self():
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def _run_backfill(bot):
    try:
        limit = int(os.getenv("ARCHIVE_BACKFILL_LIMIT", "1000"))
    except ValueError:
        limit = 1000
    count = await archive.backfill(bot, GUILD_ID, limit)
    print(f"Backfill complete: {count} message(s) recorded")


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
            "archive": archive.diagnostics(),
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


async def _api_server(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    return web.json_response(
        {
            "ok": True,
            "system": _sysinfo(),
            "guild": await _guild_info(bot),
        }
    )


async def _api_bans(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    return web.json_response({"ok": True, "bans": await _list_bans(request.app["bot"])})


async def _api_members(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    return web.json_response(
        {"ok": True, "members": await _list_members(request.app["bot"])}
    )


async def _api_user(request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    try:
        user_id = int(request.query.get("user_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Invalid user id."})
    if not user_id:
        return web.json_response({"ok": False, "error": "Missing user_id."})

    try:
        guild = _guild(bot)
    except LookupError as e:
        return web.json_response({"ok": False, "error": str(e)})

    member = guild.get_member(user_id)
    if member is not None:
        user = member
    else:
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.HTTPException as e:
                return web.json_response(
                    {"ok": False, "error": f"User not found: {e}"}
                )

    profile = {
        "id": str(user.id),
        "name": str(user),
        "avatar": user.display_avatar.url,
        "bot": user.bot,
        "created": user.created_at.strftime("%Y-%m-%d"),
    }

    if member:
        role_ids = {role.id for role in member.roles}
        profile.update(
            {
                "nickname": member.nick,
                "joined": member.joined_at.strftime("%Y-%m-%d"),
                "status": str(member.status),
                "rank": _rank_for(role_ids),
                "owner": member.id == guild.owner_id,
                "roles": [role.name for role in member.roles[1:]][::-1],
            }
        )
    else:
        profile.update(
            {
                "nickname": None,
                "joined": None,
                "status": "not in server",
                "rank": None,
                "owner": False,
                "roles": [],
            }
        )

    warnings_list = load_warnings().get(str(guild.id), {}).get(str(user_id), [])
    warnings_out = [
        {
            "reason": w.get("reason", "?"),
            "moderator": w.get("moderator", "?"),
            "timestamp": w.get("timestamp", "?"),
        }
        for w in warnings_list
    ]

    stats = archive.user_stats(user_id, guild.id)
    channel_names = {c.id: c.name for c in guild.channels}
    messages_out = [
        {
            "channel": channel_names.get(channel_id, f"<{channel_id}>"),
            "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            if ts
            else "?",
            "content": content,
            "deleted": bool(deleted),
        }
        for (mid, channel_id, content, ts, deleted) in archive.user_messages(
            user_id, guild.id, 100
        )
    ]

    return web.json_response(
        {
            "ok": True,
            "user": profile,
            "warnings": warnings_out,
            "stats": {
                "messages": stats["count"],
                "first": datetime.fromtimestamp(stats["first"]).strftime(
                    "%Y-%m-%d"
                )
                if stats["first"]
                else None,
                "last": datetime.fromtimestamp(stats["last"]).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if stats["last"]
                else None,
            },
            "messages": messages_out,
        }
    )


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
    if action == "backfill":
        bot.loop.create_task(_run_backfill(bot))
        return web.json_response(
            {"ok": True, "message": "Backfill started — watch the Console tab."}
        )
    if action == "run":
        result = await _run_command(bot, str(data.get("command", "")))
        return web.json_response(result)
    if action == "unban":
        try:
            user_id = int(data.get("user_id", 0))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "Invalid user id."})
        try:
            guild = _guild(bot)
        except LookupError as e:
            return web.json_response({"ok": False, "error": str(e)})
        try:
            user = await bot.fetch_user(user_id)
            await guild.unban(user, reason="Unbanned from dashboard")
        except discord.HTTPException as e:
            return web.json_response({"ok": False, "error": str(e)})
        return web.json_response({"ok": True, "message": f"Unbanned {user}."})
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
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)

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
    app.router.add_get("/api/server", _api_server)
    app.router.add_get("/api/bans", _api_bans)
    app.router.add_get("/api/members", _api_members)
    app.router.add_get("/api/user", _api_user)
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
.row{display:flex;gap:10px;align-items:center;padding:9px 12px;background:#11151b;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;font-size:13px}
.row .id{color:var(--muted);font-size:11px;font-family:ui-monospace,Consolas,monospace}
.row .reason{color:var(--warn);font-size:12px;flex:1;overflow-wrap:anywhere}
.row .meta{color:var(--muted);font-size:12px;margin-left:auto;white-space:nowrap}
.row button{background:transparent;border:1px solid var(--err);color:var(--err);border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}
.row button:hover{background:var(--err);color:#fff}
.row button.kick{border-color:var(--warn);color:var(--warn)}
.row button.kick:hover{background:var(--warn);color:#111}
.row button.warn{border-color:var(--acc);color:var(--acc)}
.row button.warn:hover{background:var(--acc);color:#fff}
.warncount{display:inline-block;background:#20242c;border:1px solid var(--line);color:var(--warn);border-radius:999px;padding:2px 8px;font-size:11px;font-weight:600}
.avatar{width:26px;height:26px;border-radius:50%;object-fit:cover;flex-shrink:0}
.st-online{color:var(--ok)} .st-idle{color:var(--warn)} .st-dnd{color:var(--err)} .st-offline{color:var(--muted)}
.rankb{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.4px}
.rk-owner{background:#3a2f00;border:1px solid #d4af37;color:#d4af37}
.rk-admin{background:#2e0d0d;border:1px solid var(--err);color:var(--err)}
.rk-mod{background:#101a2e;border:1px solid var(--acc);color:#7d8dff}
.rk-trial{background:#221a2e;border:1px solid #a06bff;color:#a06bff}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--line);color:var(--muted)}
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
#modal{position:fixed;inset:0;z-index:40}
#modal.hidden{display:none}
.backdrop{position:absolute;inset:0;background:rgba(0,0,0,.6)}
.panel{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:min(720px,92vw);max-height:88vh;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;overflow:auto}
.mclose{position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer;z-index:1}
.mclose:hover{color:var(--text)}
.phead{display:flex;align-items:center;gap:14px;margin-bottom:16px}
.phead img.avatar{width:64px;height:64px;border-radius:50%}
.phead .pname{font-size:20px;font-weight:700}
.pgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.pgrid .card{padding:12px}
.pgrid .card h3{font-size:11px;margin-bottom:4px}
.pgrid .card .val{font-size:14px;font-weight:600;overflow-wrap:anywhere}
.psec h3{font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin:14px 0 8px}
.pmsg{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:#11151b;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px}
.pmsg .pm-meta{color:var(--muted);font-size:11px;margin-bottom:2px}
.pmsg.deleted{border-left:3px solid var(--err)}
.pmsg .pm-d{display:inline-block;color:var(--err);font-weight:700;font-size:10px;margin-left:6px;letter-spacing:.5px}
.pwarn{background:#221a12;border:1px solid var(--warn);border-radius:8px;padding:8px 10px;margin-bottom:6px;font-size:13px}
.pwarn .pm-meta{color:var(--muted);font-size:11px;margin-top:2px}
.pwarn .mod{color:var(--acc)}
.empty{color:var(--muted);font-size:13px}
.clickable{cursor:pointer}
.clickable:hover{text-decoration:underline}
.loginbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;width:320px}
.loginbox h2{margin-bottom:6px}
.loginbox p{color:var(--muted);font-size:13px;margin-bottom:18px}
.loginbox input{width:100%;padding:12px;background:#11151b;border:1px solid var(--line);color:var(--text);border-radius:8px;font-size:18px;text-align:center;letter-spacing:6px}
.loginbox .btn{width:100%;margin-top:14px}
#logerr{color:var(--err);font-size:13px;margin-top:10px;min-height:18px}
</style>
</head>
<body>
<div id="modal" class="hidden">
  <div class="backdrop" id="modalback"></div>
  <div class="panel">
    <button class="mclose" id="modclose">&times;</button>
    <div id="modbody"><div class="idle">Loading...</div></div>
  </div>
</div>

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
  <button data-tab="console">Console</button>
  <button data-tab="server">Server</button>
  <button data-tab="bans">Bans</button>
  <button data-tab="members">Members</button>
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
      <h3>Message Archive <span id="archerr" style="color:var(--err)"></span></h3>
      <div class="sub" id="archinfo">-</div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>Loaded Cogs</h3>
      <div id="coglist"></div>
    </div>
  </div>

  <div class="tab" id="tab-console">
    <div class="card">
      <h3>Console <span style="color:var(--muted)">(bot + hosting output, auto-refresh)</span></h3>
      <div id="logs"></div>
    </div>
  </div>

  <div class="tab" id="tab-server">
    <div class="grid">
      <div class="card"><h3>Platform</h3><div class="num" style="font-size:18px" id="sv-platform">-</div></div>
      <div class="card"><h3>Python</h3><div class="num" style="font-size:18px" id="sv-python">-</div></div>
      <div class="card"><h3>Host Uptime</h3><div class="num" style="font-size:18px" id="sv-hostup">-</div></div>
      <div class="card"><h3>Load</h3><div class="num" style="font-size:18px" id="sv-load">-</div></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>Memory / Disk</h3>
      <div id="sv-mem"></div>
    </div>
    <div class="grid" style="margin-top:14px">
      <div class="card"><h3>Guild</h3><div class="num" style="font-size:18px" id="sv-guild">-</div><div class="sub" id="sv-guildsub"></div></div>
      <div class="card"><h3>Members</h3><div class="num" id="sv-guildmembers">-</div></div>
      <div class="card"><h3>Roles</h3><div class="num" id="sv-roles">-</div></div>
      <div class="card"><h3>Channels</h3><div class="num" id="sv-channels">-</div></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>Container Files</h3>
      <div id="sv-files" style="font-family:ui-monospace,Consolas,monospace;font-size:12.5px"></div>
    </div>
  </div>

  <div class="tab" id="tab-bans">
    <div class="card">
      <h3>Bans <span id="bancount" style="color:var(--muted)"></span></h3>
      <div id="banlist"></div>
    </div>
  </div>

  <div class="tab" id="tab-members">
    <div class="card">
      <h3>Members <span id="memcount" style="color:var(--muted)"></span></h3>
      <input type="text" id="memsearch" placeholder="Filter..." style="margin-bottom:12px">
      <div id="memresult"></div>
      <div id="memlist"></div>
    </div>
  </div>

  <div class="tab" id="tab-actions">
    <div class="card">
      <h3>Actions</h3>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn danger" id="btn-restart">Restart Bot</button>
        <button class="btn" id="btn-sync">Sync Slash Commands</button>
        <button class="btn ghost" id="btn-backfill">Backfill Messages</button>
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
  if (t.dataset.tab === "server") loadServer();
  if (t.dataset.tab === "bans") loadBans();
  if (t.dataset.tab === "members") loadMembers();
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
    if (d.archive) {
      document.getElementById("archinfo").textContent =
        d.archive.rows + " messages archived (" + d.archive.recorded + " recorded since start)";
      document.getElementById("archerr").textContent = d.archive.last_error ? "last error: " + d.archive.last_error : "";
    }
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

async function loadServer() {
  try {
    const d = await api("/api/server");
    const s = d.system;
    document.getElementById("sv-platform").textContent = s.platform;
    document.getElementById("sv-python").textContent = s.python;
    document.getElementById("sv-hostup").textContent = s.host_uptime || "n/a";
    document.getElementById("sv-load").textContent = s.loadavg ? s.loadavg.join("  ") : "n/a";
    const mem = document.getElementById("sv-mem");
    mem.innerHTML = s.memory
      ? '<div class="row"><span>MemTotal</span><span class="id">' + s.memory.MemTotal + ' MB</span><span class="meta">MemFree ' + s.memory.MemFree + ' MB</span></div>' +
        (s.disk ? '<div class="row"><span>Disk</span><span class="meta">' + s.disk.used + " used / " + s.disk.free + " free of " + s.disk.total + '</span></div>' : '')
      : (s.disk ? '<div class="row"><span>Disk</span><span class="meta">' + s.disk.used + " / " + s.disk.total + '</span></div>' : "n/a");
    const g = d.guild || {};
    document.getElementById("sv-guild").textContent = g.name || "-";
    document.getElementById("sv-guildsub").textContent = g.error || ("ID " + (g.id || "?") + " · owner " + (g.owner || "?") + " · created " + (g.created || "?"));
    document.getElementById("sv-guildmembers").textContent = g.members ?? "-";
    document.getElementById("sv-roles").textContent = g.roles ?? "-";
    document.getElementById("sv-channels").textContent = g.channels ?? "-";
    const files = document.getElementById("sv-files");
    files.innerHTML = s.files.length
      ? s.files.map(f => '<div class="row"><span>' + esc(f.dir ? "📁 " : "") + esc(f.name) + '</span><span class="meta">' + (f.dir ? "dir" : f.size) + '</span></div>').join("")
      : "(empty)";
  } catch (e) {}
}

async function loadBans() {
  try {
    const d = await api("/api/bans");
    document.getElementById("bancount").textContent = d.bans.length + " total";
    const box = document.getElementById("banlist");
    box.innerHTML = d.bans.length
      ? d.bans.map(b => '<div class="row"><span>' + esc(b.name) + '</span><span class="id">' + esc(String(b.id)) + '</span><span class="reason">' + esc(b.reason || "no reason") + '</span><button data-uid="' + b.id + '">Unban</button></div>').join("")
      : "(no bans)";
    box.querySelectorAll("button").forEach(btn => btn.onclick = async () => {
      if (!confirm("Unban this user?")) return;
      const r = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "unban", user_id: btn.dataset.uid})});
      alert(r.message || r.error);
      if (r.ok) loadBans();
    });
  } catch (e) {}
}

let allMembers = [];
async function loadMembers() {
  try {
    const d = await api("/api/members");
    allMembers = d.members;
    renderMembers();
  } catch (e) {}
}

function showMemResult(ok, text) {
  const r = document.getElementById("memresult");
  r.innerHTML = '<div class="row" style="border-left:3px solid ' + (ok ? "var(--ok)" : "var(--err)") + '">' + esc(text) + '</div>';
  r.style.display = "block";
}

async function runMemberAction(action, member) {
  const reason = prompt(action.toUpperCase() + " " + member.name + " — reason:");
  if (reason === null) return;
  showMemResult(true, action + "ing " + member.name + "...");
  const d = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "run", command: "?" + action + " " + member.id + " " + reason})});
  showMemResult(d.ok, (d.ok ? d.result : d.error) || "(no output)");
  if (d.ok) { setTimeout(loadMembers, 1200); loadBans(); }
}

function renderMembers() {
  const q = document.getElementById("memsearch").value.toLowerCase();
  const list = allMembers.filter(m => !q || m.name.toLowerCase().includes(q));
  document.getElementById("memcount").textContent = list.length + " of " + allMembers.length;
  const box = document.getElementById("memlist");
  box.innerHTML = list.length
    ? list.map(m => {
      const badge = m.owner
        ? '<span class="rankb rk-owner">OWNER</span> '
        : m.rank === "Admin"
          ? '<span class="rankb rk-admin">ADMIN</span> '
          : m.rank === "Mod"
            ? '<span class="rankb rk-mod">MOD</span> '
            : m.rank === "Trial Mod"
              ? '<span class="rankb rk-trial">TRIAL MOD</span> '
              : "";
      const actions = m.can_moderate
        ? '<button class="kick" data-m="' + m.id + '" data-a="kick">Kick</button><button class="warn" data-m="' + m.id + '" data-a="warn">Warn</button><button data-m="' + m.id + '" data-a="ban">Ban</button>'
        : "";
      return '<div class="row"><img class="avatar" src="' + esc(m.avatar) + '" alt="">' +
        '<span class="clickable" data-u="' + m.id + '" title="View profile">' + (m.bot ? '<span class="badge">BOT</span> ' : "") + esc(m.name) + '</span>' +
        badge +
        '<span class="id">' + esc(String(m.id)) + '</span>' +
        (m.warnings ? '<span class="warncount">' + m.warnings + ' warn' + (m.warnings > 1 ? "s" : "") + '</span>' : "") +
        '<span class="meta st-' + esc(m.status) + '">' + esc(m.status) + '</span>' +
        actions +
        '</div>';
    }).join("")
    : "(no members)";
  box.querySelectorAll("button").forEach(btn => btn.onclick = () => runMemberAction(btn.dataset.a, allMembers.find(x => x.id == btn.dataset.m)));
  box.querySelectorAll(".clickable").forEach(el => el.onclick = () => openProfile(el.dataset.u));
}

function openProfile(userId) {
  const modal = document.getElementById("modal");
  const body = document.getElementById("modbody");
  modal.classList.remove("hidden");
  body.innerHTML = '<div class="idle">Loading...</div>';
  api("/api/user?user_id=" + userId).then(d => {
    if (!d.ok) { body.innerHTML = '<div class="idle">' + esc(d.error || "Error") + '</div>'; return; }
    const u = d.user;
    const badge = u.owner
      ? '<span class="rankb rk-owner">OWNER</span> '
      : u.rank === "Admin" ? '<span class="rankb rk-admin">ADMIN</span> '
      : u.rank === "Mod" ? '<span class="rankb rk-mod">MOD</span> '
      : u.rank === "Trial Mod" ? '<span class="rankb rk-trial">TRIAL MOD</span> '
      : "";
    const warns = d.warnings.length
      ? d.warnings.map(w =>
        '<div class="pwarn"><div>' + esc(w.reason) + '</div><div class="pm-meta">by <span class="mod">&lt;@' + esc(w.moderator) + '&gt;</span> · ' + esc(w.timestamp) + '</div></div>'
      ).join("")
      : '<div class="empty">No warnings.</div>';
    const msgs = d.messages.length
      ? d.messages.map(m =>
        '<div class="pmsg' + (m.deleted ? " deleted" : "") + '"><div class="pm-meta">#' + esc(m.channel) + ' · ' + esc(m.time) + (m.deleted ? '<span class="pm-d">DELETED</span>' : "") + '</div>' + esc(m.content || "(empty)") + '</div>'
      ).join("")
      : '<div class="empty">No recorded messages.</div>';
    const roles = u.roles && u.roles.length
      ? u.roles.map(esc).join(", ")
      : "none";
    body.innerHTML =
      '<div class="phead"><img class="avatar" src="' + esc(u.avatar) + '" alt=""><div><div class="pname">' + esc(u.name) + badge + '</div><div class="meta st-' + esc(u.status) + '">' + esc(u.status) + '</div></div></div>' +
      '<div class="pgrid">' +
        '<div class="card"><h3>User ID</h3><div class="val">' + esc(String(u.id)) + '</div></div>' +
        '<div class="card"><h3>Account Created</h3><div class="val">' + esc(u.created) + '</div></div>' +
        '<div class="card"><h3>Server Joined</h3><div class="val">' + esc(u.joined || "not in server") + '</div></div>' +
        '<div class="card"><h3>Nickname</h3><div class="val">' + esc(u.nickname || "—") + '</div></div>' +
        '<div class="card"><h3>Messages</h3><div class="val">' + d.stats.messages + '</div></div>' +
        '<div class="card"><h3>First / Last Seen</h3><div class="val" style="font-size:11px">' + esc(d.stats.first || "—") + ' / ' + esc(d.stats.last || "—") + '</div></div>' +
        '<div class="card"><h3>Roles</h3><div class="val" style="font-size:12px">' + roles + '</div></div>' +
      '</div>' +
      '<div class="psec"><h3>Warnings (' + d.warnings.length + ')</h3>' + warns + '</div>' +
      '<div class="psec"><h3>Messages (last ' + d.messages.length + ')</h3>' + msgs + '</div>';
  }).catch(() => {
    body.innerHTML = '<div class="idle">Failed to load profile.</div>';
  });
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
}
document.getElementById("modclose").onclick = closeModal;
document.getElementById("modalback").onclick = closeModal;
document.getElementById("memsearch").oninput = renderMembers;

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
document.getElementById("btn-backfill").onclick = async () => {
  const d = await api("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "backfill"})});
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
