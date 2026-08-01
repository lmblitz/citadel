import sqlite3
import threading

DB_PATH = "messages.db"
_lock = threading.Lock()


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
    if not message.guild or message.author.bot or message.type != 0:
        return
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
    except Exception:
        pass


def mark_deleted(message_id):
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
    except Exception:
        pass


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
