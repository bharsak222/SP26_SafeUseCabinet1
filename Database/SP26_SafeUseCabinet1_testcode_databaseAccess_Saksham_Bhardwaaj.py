import os
import sqlite3
from typing import List

DB_FILENAME = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_conn():
    return sqlite3.connect(DB_FILENAME)


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
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
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM rooms WHERE name = ? LIMIT 1", (name,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_room(name: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
        conn.commit()
        room_id = cur.lastrowid
        # initialize room_items for any existing items
        cur.execute("SELECT id FROM items")
        item_ids = [r[0] for r in cur.fetchall()]
        for iid in item_ids:
            cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, iid))
        conn.commit()
    except sqlite3.IntegrityError:
        # already exists
        pass
    finally:
        conn.close()


def seed_items(items: List[str]):
    conn = get_conn()
    cur = conn.cursor()
    for it in items:
        try:
            cur.execute("INSERT INTO items (name) VALUES (?)", (it,))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    # ensure existing rooms have entries for the new items
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
    """Print the full database contents: rooms, items, and counts per room."""
    conn = get_conn()
    cur = conn.cursor()
    # Print items
    print("\n--- ITEMS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    for iid, name in cur.fetchall():
        print(f"{iid}: {name}")

    # Print rooms
    print("\n--- ROOMS ---")
    cur.execute("SELECT id, name FROM rooms ORDER BY id")
    rooms = cur.fetchall()
    for rid, rname in rooms:
        print(f"{rid}: {rname}")

    # Print counts matrix
    print("\n--- ROOM x ITEM COUNTS ---")
    # fetch all items ordered by id
    cur.execute("SELECT id, name FROM items ORDER BY id")
    items = cur.fetchall()
    if not items:
        print("No items defined.")
    else:
        # header
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
    """Return the full database contents as a string (items, rooms, counts)."""
    parts = []
    conn = get_conn()
    cur = conn.cursor()
    # Items
    parts.append("--- ITEMS ---")
    cur.execute("SELECT id, name FROM items ORDER BY id")
    for iid, name in cur.fetchall():
        parts.append(f"{iid}: {name}")

    # Rooms
    parts.append("\n--- ROOMS ---")
    cur.execute("SELECT id, name FROM rooms ORDER BY id")
    rooms = cur.fetchall()
    for rid, rname in rooms:
        parts.append(f"{rid}: {rname}")

    # Matrix
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
    """Increment the count for (room_name, item_id) by amount and return the new count.

    item_id is the numeric id from the `items` table (1-based auto increment id).
    Raises ValueError if room or item id is not found.
    """
    conn = get_conn()
    cur = conn.cursor()
    # find room id
    cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise ValueError(f"Room not found: {room_name}")
    room_id = r[0]
    # verify item exists
    cur.execute("SELECT id FROM items WHERE id = ?", (item_id,))
    it = cur.fetchone()
    if not it:
        conn.close()
        raise ValueError(f"Item id not found: {item_id}")
    # ensure row exists in room_items
    cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, item_id))
    # update
    cur.execute("UPDATE room_items SET count = count + ? WHERE room_id = ? AND item_id = ?", (amount, room_id, item_id))
    conn.commit()
    cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (room_id, item_id))
    new_count = cur.fetchone()[0]
    conn.close()
    return new_count


def get_total_count_for_item(item_id: int) -> int:
    """Return the total count across all rooms for a given item_id."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(count) FROM room_items WHERE item_id = ?", (item_id,))
    r = cur.fetchone()
    conn.close()
    if not r or r[0] is None:
        return 0
    return int(r[0])


def get_all_items_with_totals():
    """Return a list of (id, name, total_taken) for all items ordered by id."""
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
    """Set the count to zero for the given item_id across all rooms.

    Returns the number of rows updated (number of room rows that were reset).
    Raises ValueError if the item_id does not exist in the items table.
    """
    conn = get_conn()
    cur = conn.cursor()
    # verify item exists
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
    """Set the count to zero for the item with the given name across all rooms.

    Returns the number of rows updated. Raises ValueError if the named item
    does not exist.
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
