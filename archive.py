import sqlite3
import threading

import discord

DB_PATH = "messages.db"
_lock = threading.Lock()

RECORDED = 0
LAST_ERROR = None


def _conn():
    return sqlite3.connect(DB_PATH)


def init():
    with _lock:
        conn = _conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY,
                        guild_id INTEGER,
                        channel_id INTEGER,
                        author_id INTEGER,
                        content TEXT,
                        created_at REAL,
                        deleted INTEGER DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_author "
                    "ON messages(author_id, guild_id, created_at)"
                )
        finally:
            conn.close()


def record_message(message):
    global RECORDED, LAST_ERROR
    if (
        not message.guild
        or message.author.bot
        or message.type != discord.MessageType.default
    ):
        return False
    try:
        content = message.content or ""
        with _lock:
            conn = _conn()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO messages
                            (id, guild_id, channel_id, author_id, content, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET content = excluded.content
                        """,
                        (
                            message.id,
                            message.guild.id,
                            message.channel.id,
                            message.author.id,
                            content,
                            message.created_at.timestamp(),
                        ),
                    )
            finally:
                conn.close()
        RECORDED += 1
        return True
    except Exception as e:
        LAST_ERROR = str(e)
        return False


def mark_deleted(message_id):
    global LAST_ERROR
    try:
        with _lock:
            conn = _conn()
            try:
                with conn:
                    conn.execute(
                        "UPDATE messages SET deleted = 1 WHERE id = ?",
                        (message_id,),
                    )
            finally:
                conn.close()
    except Exception as e:
        LAST_ERROR = str(e)


def user_messages(author_id, guild_id, limit=100):
    try:
        with _lock:
            conn = _conn()
            try:
                rows = conn.execute(
                    "SELECT id, channel_id, content, created_at, deleted "
                    "FROM messages WHERE author_id = ? AND guild_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (author_id, guild_id, limit),
                ).fetchall()
            finally:
                conn.close()
        return rows
    except Exception:
        return []


def user_stats(author_id, guild_id):
    try:
        with _lock:
            conn = _conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(created_at), MAX(created_at) "
                    "FROM messages WHERE author_id = ? AND guild_id = ?",
                    (author_id, guild_id),
                ).fetchone()
            finally:
                conn.close()
        return {"count": row[0], "first": row[1], "last": row[2]}
    except Exception:
        return {"count": 0, "first": None, "last": None}


def total_rows():
    try:
        with _lock:
            conn = _conn()
            try:
                row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
            finally:
                conn.close()
        return row[0]
    except Exception:
        return 0


def newest_message_id(guild_id, channel_id):
    try:
        with _lock:
            conn = _conn()
            try:
                row = conn.execute(
                    "SELECT MAX(id) FROM messages "
                    "WHERE guild_id = ? AND channel_id = ?",
                    (guild_id, channel_id),
                ).fetchone()
            finally:
                conn.close()
        return row[0] if row else None
    except Exception:
        return None


async def backfill(bot, guild_id, limit_per_channel=1000):
    guild = bot.get_guild(guild_id)
    if guild is None:
        return 0
    total = 0
    channels = [
        c
        for c in guild.channels
        if isinstance(c, (discord.TextChannel, discord.Thread))
    ]
    channels += [t for t in guild.threads if t not in channels]
    for channel in channels:
        newest = newest_message_id(guild_id, channel.id)
        kwargs = {"limit": limit_per_channel}
        if newest is not None:
            kwargs["after"] = discord.Object(id=newest)
        try:
            async for message in channel.history(**kwargs):
                if record_message(message):
                    total += 1
        except (discord.Forbidden, discord.NotFound):
            continue
        except Exception:
            continue
    return total


def diagnostics():
    return {
        "recorded": RECORDED,
        "rows": total_rows(),
        "last_error": LAST_ERROR,
    }
