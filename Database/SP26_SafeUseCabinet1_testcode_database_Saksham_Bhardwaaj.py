# database.py
# Command-line tool for managing the SafeUseCabinet SQLite inventory database.
# Provides subcommands to initialize the schema, add items/rooms, increment
# dispensing counts, query totals, seed item lists, and reset the database from
# a JSON template. Intended for developer/admin use on the Raspberry Pi terminal.
#
# Usage examples:
#   python database.py --init
#   python database.py --add-item "Narcan" --add-room "101"
#   python database.py --increment 101 Narcan 1
#   python database.py --get-counts 101
#   python database.py --seed Condoms Bandaids Narcan
#   python database.py --list-items

import argparse
import os
import sqlite3
import sys
import json
from typing import List, Tuple

# Database file lives in the same directory as this script
DB_FILENAME = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_conn():
    """Return a new SQLite connection to the inventory database."""
    return sqlite3.connect(DB_FILENAME)


def init_db():
    """
    Create the three core tables if they don't exist.
    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
    """
    conn = get_conn()
    cur = conn.cursor()
    # items: catalog of dispensable product types
    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    # rooms: registry of valid room numbers
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    # room_items: cross-reference tracking how many of each item each room has received
    cur.execute("""
    CREATE TABLE IF NOT EXISTS room_items (
        room_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (room_id, item_id),
        FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
        FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    conn.close()
    print(f"Initialized DB at: {DB_FILENAME}")


def add_item(name: str):
    """Insert a new item into the catalog. Prints a message if it already exists."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO items (name) VALUES (?)", (name,))
        conn.commit()
        print(f"Added item: {name}")
    except sqlite3.IntegrityError:
        print(f"Item already exists: {name}")
    finally:
        conn.close()


def add_room(name: str):
    """
    Insert a new room and create room_items rows (count=0) for all existing items
    so that every room has a complete inventory record from the start.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
        conn.commit()
        room_id = cur.lastrowid
        # Initialize counts for any items that exist before this room was added
        cur.execute("SELECT id FROM items")
        item_ids = [r[0] for r in cur.fetchall()]
        for iid in item_ids:
            cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, iid))
        conn.commit()
        print(f"Added room: {name}")
    except sqlite3.IntegrityError:
        print(f"Room already exists: {name}")
    finally:
        conn.close()


def list_items():
    """Print all item names to stdout."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM items ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No items. Add with --add-item <name>")
        return
    print("Items:")
    for r in rows:
        print(" -", r[0])


def list_rooms():
    """Print all room names to stdout."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM rooms ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No rooms. Add with --add-room <name>")
        return
    print("Rooms:")
    for r in rows:
        print(" -", r[0])


def ensure_room_item_pair(cur: sqlite3.Cursor, room_id: int, item_id: int):
    """Insert a room_items row with count=0 if one doesn't already exist."""
    cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, item_id))


def increment_item(room_name: str, item_name: str, amount: int = 1):
    """
    Increment the dispensing count for (room_name, item_name) by amount.
    Prints the new count on success, or an error if the room/item is not found.
    """
    conn = get_conn()
    cur = conn.cursor()
    # Look up room by name
    cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
    r = cur.fetchone()
    if not r:
        conn.close()
        print(f"Room not found: {room_name}")
        return
    room_id = r[0]
    # Look up item by name
    cur.execute("SELECT id FROM items WHERE name = ?", (item_name,))
    it = cur.fetchone()
    if not it:
        conn.close()
        print(f"Item not found: {item_name}")
        return
    item_id = it[0]
    ensure_room_item_pair(cur, room_id, item_id)
    cur.execute("UPDATE room_items SET count = count + ? WHERE room_id = ? AND item_id = ?", (amount, room_id, item_id))
    conn.commit()
    # Read back the updated count to confirm
    cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (room_id, item_id))
    new_count = cur.fetchone()[0]
    conn.close()
    print(f"Updated {item_name} for room {room_name}: +{amount} -> {new_count}")


def get_counts(room_name: str):
    """Print the dispensing count for every item in the given room."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
    r = cur.fetchone()
    if not r:
        print(f"Room not found: {room_name}")
        conn.close()
        return
    room_id = r[0]
    # LEFT JOIN ensures items with no room_items row still appear (as 0)
    cur.execute("""
    SELECT items.name, COALESCE(room_items.count, 0) FROM items
    LEFT JOIN room_items ON items.id = room_items.item_id AND room_items.room_id = ?
    ORDER BY items.name
    """, (room_id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No items defined. Add items with --add-item <name>")
        return
    print(f"Counts for room: {room_name}")
    for name, count in rows:
        print(f" - {name}: {count}")


def seed_items(items: List[str]):
    """
    Bulk-insert a list of item names, ignoring duplicates.
    Ensures all existing rooms have room_items rows for the new items.
    """
    conn = get_conn()
    cur = conn.cursor()
    for it in items:
        try:
            cur.execute("INSERT INTO items (name) VALUES (?)", (it,))
        except sqlite3.IntegrityError:
            pass  # Skip duplicates silently
    conn.commit()
    # Fill room_items for any existing rooms × newly added items
    cur.execute("SELECT id FROM rooms")
    rooms = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT id FROM items")
    item_ids = [r[0] for r in cur.fetchall()]
    for rid in rooms:
        for iid in item_ids:
            cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (rid, iid))
    conn.commit()
    conn.close()
    print(f"Seeded {len(items)} items (duplicates ignored)")


def find_item_names() -> List[str]:
    """Return a list of all item names in the catalog (for autocomplete / validation)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM items ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def parse_args(argv=None):
    """Build and parse the argument parser for the CLI."""
    p = argparse.ArgumentParser(description="Track counts of items taken per room (SQLite)")
    p.add_argument("--init",       action="store_true", help="Initialize the DB")
    p.add_argument("--add-item",   metavar="NAME",      help="Add a new item")
    p.add_argument("--add-room",   metavar="NAME",      help="Add a new room")
    p.add_argument("--increment",  nargs=3, metavar=("ROOM","ITEM","AMOUNT"), help="Increment item count for room")
    p.add_argument("--get-counts", metavar="ROOM",      help="Show counts for a room")
    p.add_argument("--list-items", action="store_true", help="List all items")
    p.add_argument("--list-rooms", action="store_true", help="List all rooms")
    p.add_argument("--seed",       nargs="*", metavar="ITEM", help="Seed a list of items (space-separated)")
    return p.parse_args(argv)


def main(argv=None):
    """Parse CLI arguments and dispatch to the appropriate database function."""
    args = parse_args(argv)
    if args.init:
        init_db()
    if args.add_item:
        add_item(args.add_item)
    if args.add_room:
        add_room(args.add_room)
    if args.increment:
        room, item, amount = args.increment
        try:
            amt = int(amount)
        except ValueError:
            print("Amount must be an integer")
            return
        increment_item(room, item, amt)
    if args.get_counts:
        get_counts(args.get_counts)
    if args.list_items:
        list_items()
    if args.list_rooms:
        list_rooms()
    if args.seed is not None:
        seed_items(args.seed)


if __name__ == "__main__":
    main()


def reset_from_template(template_path: str | None = None):
    """
    Wipe and rebuild the database from a JSON template file.

    The template JSON format:
      {
        "items": [{"id": 1, "name": "Narcan"}, ...],
        "rooms": [{"name": "101"}, ...],
        "room_items": [{"room": "101", "item_id": 1, "count": 5}, ...]
      }

    - Deletes all existing rows from room_items, rooms, and items.
    - Resets AUTOINCREMENT counters so IDs start at 1 again.
    - Inserts items and rooms from the template.
    - Initializes every room × item pair with count=0.
    - Applies any explicit counts from the "room_items" section.
    """
    if template_path is None:
        # Default template lives next to this file
        template_path = os.path.join(os.path.dirname(__file__), 'database_reset_template.json')
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")

    with open(template_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = get_conn()
    cur = conn.cursor()
    # Ensure tables exist before wiping them (handles fresh DB case)
    init_db()

    # Clear all existing data
    cur.execute('DELETE FROM room_items')
    cur.execute('DELETE FROM rooms')
    cur.execute('DELETE FROM items')
    conn.commit()

    # Reset AUTOINCREMENT counters so the first inserted rows get id=1
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('items','rooms')")
        conn.commit()
    except Exception:
        pass  # sqlite_sequence doesn't exist if no AUTOINCREMENT rows were ever inserted

    # Insert items from template (ignore any id hints — use SQLite's AUTOINCREMENT)
    tpl_items = data.get('items', [])
    for it in tpl_items:
        name = it.get('name')
        if not name:
            continue
        try:
            cur.execute('INSERT INTO items (name) VALUES (?)', (name,))
        except sqlite3.IntegrityError:
            pass

    # Insert rooms from template
    tpl_rooms = data.get('rooms', [])
    for rm in tpl_rooms:
        name = rm.get('name')
        if not name:
            continue
        try:
            cur.execute('INSERT INTO rooms (name) VALUES (?)', (name,))
        except sqlite3.IntegrityError:
            pass

    conn.commit()

    # Build name→id maps for items and rooms so we can resolve template references
    cur.execute('SELECT id, name FROM items ORDER BY id')
    items_map = {name: iid for iid, name in cur.fetchall()}

    # Map template item IDs to actual SQLite IDs (template IDs may differ after wipe)
    template_id_map = {}
    for idx, it in enumerate(tpl_items, start=1):
        tid = it.get('id', idx)   # Use explicit id from template, or insertion order
        name = it.get('name')
        if name in items_map:
            template_id_map[tid] = items_map[name]

    cur.execute('SELECT id, name FROM rooms ORDER BY id')
    rooms_map = {name: rid for rid, name in cur.fetchall()}

    # Initialize every room × item pair with count=0
    for rname, rid in rooms_map.items():
        for iname, iid in items_map.items():
            cur.execute('INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)', (rid, iid))
    conn.commit()

    # Apply any explicit counts from the template's "room_items" section
    for ri in data.get('room_items', []):
        room_name   = ri.get('room')
        tpl_item_id = ri.get('item_id')
        count       = int(ri.get('count', 0))
        if not room_name or tpl_item_id is None:
            continue
        rid            = rooms_map.get(room_name)
        sqlite_item_id = template_id_map.get(tpl_item_id)
        if rid is None or sqlite_item_id is None:
            continue  # Skip if the room or item can't be resolved from the template
        cur.execute('UPDATE room_items SET count = ? WHERE room_id = ? AND item_id = ?', (count, rid, sqlite_item_id))
    conn.commit()
    conn.close()
    print(f"Database reset from template: {template_path}")
