import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

DEFAULT_MAX_STORAGE_PER_GROUP = 300


class Storage:
    def __init__(self, db_path: Path, max_items_per_group: int = DEFAULT_MAX_STORAGE_PER_GROUP) -> None:
        self.db_path = db_path
        self.max_items_per_group = int(max_items_per_group) if max_items_per_group and max_items_per_group > 0 else DEFAULT_MAX_STORAGE_PER_GROUP
        # Use RLock because some ops (prune -> delete) can be nested.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                position INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                content_type TEXT DEFAULT 'text',
                content_text TEXT,
                content_blob BLOB,
                preview_text TEXT,
                preview_blob BLOB,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                pinned INTEGER NOT NULL DEFAULT 0,
                pinned_at INTEGER,
                group_id INTEGER NOT NULL,
                FOREIGN KEY (group_id) REFERENCES groups (id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_items_group ON items(group_id)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_pinned_time ON items(pinned, pinned_at, created_at)"
        )
        self.conn.commit()
        self._migrate_groups_table()
        self._migrate_items_table()
        self._init_subitems_table()
        self._init_settings_table()
        if not self.get_group_by_name("Default"):
            self.create_group("Default")

    def _migrate_groups_table(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(groups)")
        cols = {row[1] for row in cur.fetchall()}
        if "position" not in cols:
            cur.execute("ALTER TABLE groups ADD COLUMN position INTEGER")
            self.conn.commit()
        cur.execute("UPDATE groups SET position=id WHERE position IS NULL")
        self.conn.commit()

    def _migrate_items_table(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(items)")
        cols = {row[1] for row in cur.fetchall()}
        if "content_type" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN content_type TEXT DEFAULT 'text'")
        if "content_text" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN content_text TEXT")
        if "content_blob" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN content_blob BLOB")
        if "preview_text" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN preview_text TEXT")
        if "preview_blob" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN preview_blob BLOB")
        if "last_used_at" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN last_used_at INTEGER")
        if "pinned_at" not in cols:
            cur.execute("ALTER TABLE items ADD COLUMN pinned_at INTEGER")
        # Backfill legacy content into content_text.
        cur.execute("UPDATE items SET content_text=content WHERE content_text IS NULL")
        cur.execute(
            """
            UPDATE items
            SET pinned_at=created_at
            WHERE pinned=1 AND pinned_at IS NULL
            """
        )
        cur.execute("DROP INDEX IF EXISTS idx_items_pinned_time")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_pinned_time ON items(pinned, pinned_at, created_at)"
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_items_last_used
            ON items(last_used_at, created_at)
            """
        )
        self.conn.commit()

    def _init_subitems_table(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subitems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                icons TEXT,
                tag TEXT,
                created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_subitems_item ON subitems(item_id)")
        cur.execute("PRAGMA table_info(subitems)")
        cols = {row[1] for row in cur.fetchall()}
        if "tag" not in cols:
            cur.execute("ALTER TABLE subitems ADD COLUMN tag TEXT")
        self.conn.commit()

    def _init_settings_table(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def create_group(self, name: str) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM groups")
            next_pos = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO groups (name, position) VALUES (?, ?)", (name, next_pos)
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def rename_group(self, group_id: int, name: str) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("UPDATE groups SET name=? WHERE id=?", (name, group_id))
            self.conn.commit()

    def delete_group(self, group_id: int) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM subitems WHERE item_id IN (SELECT id FROM items WHERE group_id=?)",
                (group_id,),
            )
            cur.execute("DELETE FROM items WHERE group_id=?", (group_id,))
            cur.execute("DELETE FROM groups WHERE id=?", (group_id,))
            self.conn.commit()

    def list_groups(self) -> Iterable[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, name, position FROM groups ORDER BY position ASC, id ASC"
        )
        return cur.fetchall()

    def update_group_positions(self, ordered_ids: list[int]) -> None:
        with self._lock:
            cur = self.conn.cursor()
            data = [(idx + 1, gid) for idx, gid in enumerate(ordered_ids)]
            cur.executemany("UPDATE groups SET position=? WHERE id=?", data)
            self.conn.commit()
            # Debug print order to stdout; safe for CLI usage.
            ordered_names = []
            if ordered_ids:
                cur.execute(
                    f"SELECT id, name FROM groups WHERE id IN ({','.join('?' for _ in ordered_ids)})",
                    ordered_ids,
                )
                rows = {int(r["id"]): r["name"] for r in cur.fetchall()}
                ordered_names = [rows.get(gid, str(gid)) for gid in ordered_ids]
            print("Group order updated:", ordered_names)

    def get_group_by_name(self, name: str) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT id, name FROM groups WHERE name=?", (name,))
        return cur.fetchone()

    def get_group_by_id(self, group_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT id, name FROM groups WHERE id=?", (group_id,))
        return cur.fetchone()

    def group_exists(self, group_id: int) -> bool:
        return self.get_group_by_id(group_id) is not None

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()

    def add_item(
        self,
        content_type: str,
        content_text: str,
        content_blob: Optional[bytes],
        preview_text: Optional[str],
        preview_blob: Optional[bytes],
        created_at: int,
        group_id: int,
    ) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO items
                    (content, content_type, content_text, content_blob, preview_text, preview_blob, created_at, pinned, pinned_at, group_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
                """,
                (
                    content_text,
                    content_type,
                    content_text,
                    content_blob,
                    preview_text,
                    preview_blob,
                    created_at,
                    group_id,
                ),
            )
            self.conn.commit()
            new_id = int(cur.lastrowid)
            self._prune_group_items(group_id, self.max_items_per_group)
            return new_id

    def list_items(
        self, group_id: Optional[int], query: Optional[str], previews_only: bool = False
    ) -> Iterable[sqlite3.Row]:
        cur = self.conn.cursor()
        if previews_only:
            # Keep full draw.io payload so preview generation still works while collapsed.
            content_text_expr = (
                "CASE WHEN content_type='drawio' THEN content_text "
                "ELSE COALESCE(preview_text, content_text) END"
            )
            content_blob_expr = (
                "CASE "
                "WHEN content_type='html' THEN content_blob "  # keep html body for bg/color extraction
                "WHEN preview_blob IS NULL THEN content_blob "
                "ELSE NULL END"
            )
            has_full_expr = (
                "CASE "
                "WHEN content_type='html' THEN 1 "
                "WHEN preview_blob IS NULL AND preview_text IS NULL THEN 1 "
                "ELSE 0 END"
            )
            length_expr = "COALESCE(LENGTH(content_text), 0)"
        else:
            content_text_expr = "content_text"
            content_blob_expr = "content_blob"
            has_full_expr = "1"
            length_expr = "COALESCE(LENGTH(content_text), 0)"
        params: Tuple[object, ...]
        base = """
            SELECT id,
                   content,
                   content_type,
                   {content_text_expr} AS content_text,
                   {content_blob_expr} AS content_blob,
                   preview_text,
                   preview_blob,
                   {length_expr} AS content_length,
                   last_used_at,
                   created_at,
                   pinned,
                   pinned_at,
                   group_id,
                   {has_full_expr} AS has_full_content
            FROM items
        """
        base = base.format(
            content_text_expr=content_text_expr,
            content_blob_expr=content_blob_expr,
            has_full_expr=has_full_expr,
            length_expr=length_expr,
        )
        where = []
        if group_id is not None:
            where.append("group_id=?")
        if query:
            where.append("content_text LIKE ?")
        if where:
            base += " WHERE " + " AND ".join(where)
        # Pinned items are ordered by pin time (oldest pinned first); unpinned stay newest-first by created_at.
        base += """
            ORDER BY
                pinned DESC,
                CASE WHEN pinned=1 THEN COALESCE(pinned_at, created_at) END ASC,
                CASE WHEN pinned=1 THEN id END ASC,
                CASE WHEN pinned=0 THEN COALESCE(last_used_at, created_at) END DESC,
                CASE WHEN pinned=0 THEN id END DESC
        """
        if group_id is not None and query:
            params = (group_id, f"%{query}%")
        elif group_id is not None:
            params = (group_id,)
        elif query:
            params = (f"%{query}%",)
        else:
            params = ()
        cur.execute(base, params)
        return cur.fetchall()

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT group_id FROM items WHERE id=?", (item_id,))
            row = cur.fetchone()
            group_id = int(row["group_id"]) if row else None
            pin_ts = int(time.time()) if pinned else None
            cur.execute(
                "UPDATE items SET pinned=?, pinned_at=? WHERE id=?",
                (1 if pinned else 0, pin_ts, item_id),
            )
            self.conn.commit()
            if group_id is not None and not pinned:
                self._prune_group_items(group_id, self.max_items_per_group)

    def move_item_to_group(self, item_id: int, group_id: int) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("UPDATE items SET group_id=? WHERE id=?", (group_id, item_id))
            self.conn.commit()
            self._prune_group_items(group_id, self.max_items_per_group)

    def refresh_item_timestamp(self, item_id: int, ts: Optional[int] = None) -> None:
        """Deprecated: kept for compatibility; updates last_used_at instead of created_at."""
        self.touch_item_last_used(item_id, ts)

    def touch_item_last_used(self, item_id: int, ts: Optional[int] = None) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE items SET last_used_at=? WHERE id=?",
                (int(ts if ts is not None else time.time()), item_id),
            )
            self.conn.commit()

    def delete_item(self, item_id: int) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM subitems WHERE item_id=?", (item_id,))
            cur.execute("DELETE FROM items WHERE id=?", (item_id,))
            self.conn.commit()

    def get_item(self, item_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, content, content_type, content_text, content_blob,
                   preview_text, preview_blob,
                   COALESCE(LENGTH(content_text), 0) AS content_length,
                   created_at, last_used_at, pinned, pinned_at, group_id,
                   1 AS has_full_content
            FROM items
            WHERE id=?
            """,
            (item_id,),
        )
        row = cur.fetchone()
        return row

    def add_subitem(
        self,
        item_id: int,
        text: str,
        icons: Optional[list[str]] = None,
        tag: Optional[str] = None,
    ) -> int:
        with self._lock:
            cur = self.conn.cursor()
            icons_json = json.dumps(icons or [])
            cur.execute(
                """
                INSERT INTO subitems (item_id, text, icons, tag)
                VALUES (?, ?, ?, ?)
                """,
                (item_id, text, icons_json, tag),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def delete_subitem(self, subitem_id: int) -> None:
        if subitem_id is None or subitem_id < 0:
            return
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM subitems WHERE id=?", (int(subitem_id),))
            self.conn.commit()

    def delete_subitems_by_tag(self, item_id: int, tag: str) -> None:
        if not tag:
            return
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                DELETE FROM subitems
                WHERE item_id=? AND LOWER(tag)=LOWER(?)
                """,
                (item_id, tag),
            )
            self.conn.commit()

    def list_subitems(self, item_id: int) -> Iterable[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, item_id, text, icons, tag
            FROM subitems
            WHERE item_id=?
            ORDER BY created_at ASC, id ASC
            """,
            (item_id,),
        )
        return cur.fetchall()

    def _prune_group_items(self, group_id: int, limit: int) -> None:
        if limit <= 0:
            return
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM items
            WHERE group_id=? AND pinned=0
            ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC
            """,
            (group_id,),
        )
        rows = cur.fetchall()
        ids = [int(row["id"]) for row in rows]
        if len(ids) <= limit:
            return
        for stale_id in ids[limit:]:
            self.delete_item(stale_id)

    def update_preview(
        self,
        item_id: int,
        preview_text: Optional[str],
        preview_blob: Optional[bytes],
    ) -> None:
        if "xxx" in preview_text:
            print("Updating preview for item", item_id)
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE items
                SET preview_text=?, preview_blob=?
                WHERE id=?
                """,
                (preview_text, preview_blob, item_id),
            )
            self.conn.commit()

    def get_latest_item(self, group_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, content, content_type, content_text, content_blob,
                   preview_text, preview_blob,
                   COALESCE(LENGTH(content_text), 0) AS content_length,
                   created_at, last_used_at, pinned, pinned_at, group_id,
                   1 AS has_full_content
            FROM items
            WHERE group_id=?
            ORDER BY COALESCE(last_used_at, created_at) DESC
            LIMIT 1
            """,
            (group_id,),
        )
        return cur.fetchone()
