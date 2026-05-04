# databaseAccess.py
# SQLite database access layer for the SafeUseCabinet inventory system.
# Provides CRUD helpers that RasberryPiCode and SkeletonCode import at runtime.
#
# Schema (3 tables):
#   items      — catalog of dispensable item types (id, name)
#   rooms      — list of valid room numbers (id, name)
#   room_items — per-room count of how many of each item have been taken
#                (room_id, item_id, count)
#
# All functions open and close their own connection so callers don't need to
# manage connection state. SQLite is used because the Pi has no network DB
# and the dataset is small (dozens of rooms, ~12 item types).

import os
import sqlite3
from typing import List

# Database file lives next to this module inside the Database/ directory
DB_FILENAME = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_conn():
    """Return a new SQLite connection to the inventory database."""
    return sqlite3.connect(DB_FILENAME)


def init_db():
    """Create the items, rooms, and room_items tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    # Items catalog — each dispensable product type gets one row
    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    # Room registry — only rooms in this table can trigger a dispensing run
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    # Cross-reference table tracking how many of each item a room has received
    cur.execute("""
    CREATE TABLE IF NOT EXISTS room_items (
        room_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (room_id, item_id)
    )
    """)
    conn.commit()
    conn.close()


def room_exists(name: str) -> bool:
    """Return True if the given room name exists in the rooms table."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM rooms WHERE name = ? LIMIT 1", (name,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_room(name: str):
    """
    Insert a new room and create room_items rows (count=0) for all existing items.
    Silently ignores duplicate room names.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
        conn.commit()
        room_id = cur.lastrowid
        # Pre-populate room_items so every room immediately has a count row for
        # each item — avoids INSERT-or-UPDATE logic in increment_item_by_id
        cur.execute("SELECT id FROM items")
        item_ids = [r[0] for r in cur.fetchall()]
        for iid in item_ids:
            cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, iid))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Room already exists — no-op
    finally:
        conn.close()


def seed_items(items: List[str]):
    """
    Bulk-insert a list of item names, ignoring duplicates.
    Also creates room_items rows for any existing rooms so every room keeps a
    complete count entry for every item.
    """
    conn = get_conn()
    cur = conn.cursor()
    for it in items:
        try:
            cur.execute("INSERT INTO items (name) VALUES (?)", (it,))
        except sqlite3.IntegrityError:
            pass  # Item already exists — skip
    conn.commit()
    # Ensure all room × item combinations have a row in room_items
    cur.execute("SELECT id FROM rooms")
    rooms = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT id FROM items")
    item_ids = [r[0] for r in cur.fetchall()]
    for rid in rooms:
        for iid in item_ids:
            cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (rid, iid))
    conn.commit()
    conn.close()


def print_database():
    """Print the full database contents (items, rooms, and a counts matrix) to stdout."""
    conn = get_conn()
    cur = conn.cursor()
    # --- Items ---
    print("\n--- ITEMS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    for iid, name in cur.fetchall():
        print(f"{iid}: {name}")

    # --- Rooms ---
    print("\n--- ROOMS ---")
    cur.execute("SELECT id, name FROM rooms ORDER BY id")
    rooms = cur.fetchall()
    for rid, rname in rooms:
        print(f"{rid}: {rname}")

    # --- Room × Item count matrix ---
    print("\n--- ROOM x ITEM COUNTS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    items = cur.fetchall()
    if not items:
        print("No items defined.")
    else:
        # Header row: "Room" followed by each item name
        header = ["Room"] + [name for (_id, name) in items]
        print("\t".join(header))
        for rid, rname in rooms:
            row = [rname]
            for iid, _name in items:
                cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (rid, iid))
                rr = cur.fetchone()
                row.append(str(rr[0]) if rr else "0")
            print("\t".join(row))

    conn.close()


def dump_database_text() -> str:
    """Return the full database contents as a formatted string (for email bodies)."""
    parts = []
    conn = get_conn()
    cur = conn.cursor()

    # --- Items section ---
    parts.append("--- ITEMS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    for iid, name in cur.fetchall():
        parts.append(f"{iid}: {name}")

    # --- Rooms section ---
    parts.append("\n--- ROOMS ---")
    cur.execute("SELECT id, name FROM rooms ORDER BY id")
    rooms = cur.fetchall()
    for rid, rname in rooms:
        parts.append(f"{rid}: {rname}")

    # --- Count matrix section ---
    parts.append("\n--- ROOM x ITEM COUNTS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    items = cur.fetchall()
    if not items:
        parts.append("No items defined.")
    else:
        header = ["Room"] + [name for (_id, name) in items]
        parts.append("\t".join(header))
        for rid, rname in rooms:
            row = [rname]
            for iid, _name in items:
                cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (rid, iid))
                rr = cur.fetchone()
                row.append(str(rr[0]) if rr else "0")
            parts.append("\t".join(row))

    conn.close()
    return "\n".join(parts)


def increment_item_by_id(room_name: str, item_id: int, amount: int = 1) -> int:
    """
    Increment the dispensing count for (room_name, item_id) by amount.
    Returns the new count after incrementing.
    Raises ValueError if the room name or item id is not found.
    item_id is the 1-based autoincrement id from the items table.
    """
    conn = get_conn()
    cur = conn.cursor()
    # Resolve room name to its primary key
    cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise ValueError(f"Room not found: {room_name}")
    room_id = r[0]
    # Verify the item exists in the catalog
    cur.execute("SELECT id FROM items WHERE id = ?", (item_id,))
    it = cur.fetchone()
    if not it:
        conn.close()
        raise ValueError(f"Item id not found: {item_id}")
    # Ensure a room_items row exists before updating
    cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, item_id))
    cur.execute("UPDATE room_items SET count = count + ? WHERE room_id = ? AND item_id = ?", (amount, room_id, item_id))
    conn.commit()
    cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (room_id, item_id))
    new_count = cur.fetchone()[0]
    conn.close()
    return new_count


def get_total_count_for_item(item_id: int) -> int:
    """Return the total count across all rooms for a given item_id (for stock limit checks)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(count) FROM room_items WHERE item_id = ?", (item_id,))
    r = cur.fetchone()
    conn.close()
    if not r or r[0] is None:
        return 0
    return int(r[0])


def get_all_items_with_totals():
    """
    Return a list of (id, name, total_taken) for all items ordered by id.
    Used by MainSkeleton to compute which items need restocking before emailing.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT items.id, items.name, COALESCE(SUM(room_items.count), 0) as total
        FROM items
        LEFT JOIN room_items ON items.id = room_items.item_id
        GROUP BY items.id
        ORDER BY items.id
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def reset_item_counts(item_id: int) -> int:
    """
    Set the dispensing count to zero for item_id across all rooms.
    Returns the number of room rows that were reset.
    Raises ValueError if item_id is not in the items table.
    """
    conn = get_conn()
    cur = conn.cursor()
    # Guard: make sure the item exists before issuing a potentially no-op UPDATE
    cur.execute("SELECT 1 FROM items WHERE id = ? LIMIT 1", (item_id,))
    if cur.fetchone() is None:
        conn.close()
        raise ValueError(f"Item id not found: {item_id}")

    cur.execute("UPDATE room_items SET count = 0 WHERE item_id = ?", (item_id,))
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return int(updated)


def reset_item_counts_by_name(item_name: str) -> int:
    """
    Set the count to zero for the named item across all rooms.
    Returns the number of rows updated.
    Raises ValueError if the item name is not found.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM items WHERE name = ?", (item_name,))
    r = cur.fetchone()
    conn.close()
    if not r:
        raise ValueError(f"Item not found: {item_name}")
    item_id = r[0]
    return reset_item_counts(item_id)
