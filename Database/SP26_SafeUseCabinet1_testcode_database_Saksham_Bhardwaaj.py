import argparse
import os
import sqlite3
import sys
import json
from typing import List, Tuple

DB_FILENAME = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_conn():
	return sqlite3.connect(DB_FILENAME)


def init_db():
	conn = get_conn()
	cur = conn.cursor()
	# items: list of item names
	cur.execute("""
	CREATE TABLE IF NOT EXISTS items (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		name TEXT UNIQUE NOT NULL
	)
	""")
	# rooms: list of rooms
	cur.execute("""
	CREATE TABLE IF NOT EXISTS rooms (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		name TEXT UNIQUE NOT NULL
	)
	""")
	# counts: room_id, item_id, count
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
	conn = get_conn()
	cur = conn.cursor()
	try:
		cur.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
		conn.commit()
		room_id = cur.lastrowid
		# initialize counts for existing items
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
	cur.execute("INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)", (room_id, item_id))


def increment_item(room_name: str, item_name: str, amount: int = 1):
	conn = get_conn()
	cur = conn.cursor()
	# find room
	cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
	r = cur.fetchone()
	if not r:
		conn.close()
		print(f"Room not found: {room_name}")
		return
	room_id = r[0]
	# find item
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
	# return new count
	cur.execute("SELECT count FROM room_items WHERE room_id = ? AND item_id = ?", (room_id, item_id))
	new_count = cur.fetchone()[0]
	conn.close()
	print(f"Updated {item_name} for room {room_name}: +{amount} -> {new_count}")


def get_counts(room_name: str):
	conn = get_conn()
	cur = conn.cursor()
	cur.execute("SELECT id FROM rooms WHERE name = ?", (room_name,))
	r = cur.fetchone()
	if not r:
		print(f"Room not found: {room_name}")
		conn.close()
		return
	room_id = r[0]
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
	print(f"Seeded {len(items)} items (duplicates ignored)")


def find_item_names() -> List[str]:
	conn = get_conn()
	cur = conn.cursor()
	cur.execute("SELECT name FROM items ORDER BY name")
	rows = [r[0] for r in cur.fetchall()]
	conn.close()
	return rows


def parse_args(argv=None):
	p = argparse.ArgumentParser(description="Track counts of items taken per room (SQLite)")
	p.add_argument("--init", action="store_true", help="Initialize the DB")
	p.add_argument("--add-item", metavar="NAME", help="Add a new item")
	p.add_argument("--add-room", metavar="NAME", help="Add a new room")
	p.add_argument("--increment", nargs=3, metavar=("ROOM","ITEM","AMOUNT"), help="Increment item count for room")
	p.add_argument("--get-counts", metavar="ROOM", help="Show counts for a room")
	p.add_argument("--list-items", action="store_true", help="List all items")
	p.add_argument("--list-rooms", action="store_true", help="List all rooms")
	p.add_argument("--seed", nargs="*", metavar="ITEM", help="Seed a list of items (space separated) into DB")
	return p.parse_args(argv)


def main(argv=None):
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
	"""Reset the SQLite DB using the JSON template at template_path.

	- If template_path is None, uses Database/database_reset_template.json next to this file.
	- This will delete all rows from items, rooms and room_items, then insert items and rooms
	  from the template and initialize room_items rows with count=0 for every room×item pair.
	- If the template provides explicit room_items counts, those will be applied after initialization.
	"""
	if template_path is None:
		template_path = os.path.join(os.path.dirname(__file__), 'database_reset_template.json')
	if not os.path.exists(template_path):
		raise FileNotFoundError(f"Template not found: {template_path}")

	with open(template_path, 'r', encoding='utf-8') as f:
		data = json.load(f)

	conn = get_conn()
	cur = conn.cursor()
	# Ensure tables exist
	init_db()
	# Clear existing data
	cur.execute('DELETE FROM room_items')
	cur.execute('DELETE FROM rooms')
	cur.execute('DELETE FROM items')
	conn.commit()

	# Reset AUTOINCREMENT counters so newly-inserted items/rooms start at 1.
	# sqlite_sequence exists only when AUTOINCREMENT was used; wrap in try/except
	try:
		cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('items','rooms')")
		conn.commit()
	except Exception:
		# ignore if sqlite_sequence doesn't exist or can't be modified
		pass

	# Insert items (use name field; ignore provided IDs)
	tpl_items = data.get('items', [])
	for it in tpl_items:
		name = it.get('name')
		if not name:
			continue
		try:
			cur.execute('INSERT INTO items (name) VALUES (?)', (name,))
		except sqlite3.IntegrityError:
			pass

	# Insert rooms
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

	# Build mapping from template item id -> actual sqlite id (by insertion order/name)
	cur.execute('SELECT id, name FROM items ORDER BY id')
	items_map = {name: iid for iid, name in cur.fetchall()}
	# template id mapping: if template included ids, map them by order or explicit id
	template_id_map = {}
	for idx, it in enumerate(tpl_items, start=1):
		tid = it.get('id', idx)
		name = it.get('name')
		if name in items_map:
			template_id_map[tid] = items_map[name]

	cur.execute('SELECT id, name FROM rooms ORDER BY id')
	rooms_map = {name: rid for rid, name in cur.fetchall()}

	# Initialize room_items for every combination with count=0
	for rname, rid in rooms_map.items():
		for iname, iid in items_map.items():
			cur.execute('INSERT OR IGNORE INTO room_items (room_id, item_id, count) VALUES (?, ?, 0)', (rid, iid))
	conn.commit()

	# Apply explicit counts from template if any (supports template item_id values mapped above)
	for ri in data.get('room_items', []):
		room_name = ri.get('room')
		tpl_item_id = ri.get('item_id')
		count = int(ri.get('count', 0))
		if not room_name or tpl_item_id is None:
			continue
		rid = rooms_map.get(room_name)
		sqlite_item_id = template_id_map.get(tpl_item_id)
		if rid is None or sqlite_item_id is None:
			# skip if mapping can't be resolved
			continue
		cur.execute('UPDATE room_items SET count = ? WHERE room_id = ? AND item_id = ?', (count, rid, sqlite_item_id))
	conn.commit()
	conn.close()
	print(f"Database reset from template: {template_path}")

