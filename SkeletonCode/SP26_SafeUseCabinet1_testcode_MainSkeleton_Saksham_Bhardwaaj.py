# MainSkeleton.py
# Skeleton (terminal-based) entry point for the SafeUseCabinet dispensing system.
# Collects room number and item selection from the keyboard (via ButtonPressed.py),
# validates against the SQLite database, enforces per-item stock caps, and
# optionally emails a full database dump with a restock-needed summary.
# Intended to be run on a development machine or the Pi without hardware attached.

import ButtonPressed
import os
import importlib.util

# ---------------------------------------------------------------------------
# Per-item maximum dispensing totals (across all rooms combined)
# Adjust these to match the physical stock loaded in each dispenser slot.
# ---------------------------------------------------------------------------
max_Condoms          = 100
max_Bandaids         = 200
max_Xylazine_Strips  = 5
max_Fentanyl_Strips  = 100
max_Cook_Strips      = 40
max_Clean_Needles    = 500
max_Pregnancy_Tests  = 50
max_Gloves           = 300
max_Wipes            = 400
max_Narcan           = 60


def main(argv=None):
    enteringRoomNumber = True

    # ---------------------------------------------------------------------------
    # Optional: reset the database from the JSON template before this session
    # This lets staff wipe and re-seed counts without touching the CLI tool.
    # ---------------------------------------------------------------------------
    db_mod_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'database.py'))
    spec_db = importlib.util.spec_from_file_location('database', db_mod_path)
    database = importlib.util.module_from_spec(spec_db)
    spec_db.loader.exec_module(database)
    resp_reset = input('Reset database from template? (y/N): ').strip().lower()
    if resp_reset in ('y', 'yes'):
        try:
            database.reset_from_template()
        except Exception as e:
            print('Failed to reset database:', e)

    # ---------------------------------------------------------------------------
    # Room number entry
    # ---------------------------------------------------------------------------
    if enteringRoomNumber:
        roomNumber = ButtonPressed.getRoomNumber()
        print(f"Room number entered: {roomNumber}")
        enteringRoomNumber = False

        # Load the database access module dynamically so this skeleton works without
        # having the Database/ directory on sys.path at import time.
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'databaseAccess.py'))
        spec = importlib.util.spec_from_file_location('dbaccess', db_path)
        dbaccess = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dbaccess)

        # Initialize tables if this is the first run
        dbaccess.init_db()

        # Auto-create the room if it isn't already registered
        if not dbaccess.room_exists(roomNumber):
            dbaccess.add_room(roomNumber)
            print(f"Room '{roomNumber}' created in database.")
        else:
            print(f"Room '{roomNumber}' already exists in database.")

    # ---------------------------------------------------------------------------
    # Item selection and dispensing logic
    # ---------------------------------------------------------------------------
    if not enteringRoomNumber:
        itemChosen = ButtonPressed.getItemChosen()
        print(f"Item chosen: {itemChosen}")

        try:
            idx = int(itemChosen)   # Item IDs are 1-based integers

            # Map each item id to its maximum total (None = no cap enforced)
            MAX_PER_ITEM = {
                1: max_Xylazine_Strips,
                2: max_Fentanyl_Strips,
                3: max_Cook_Strips,
                4: max_Clean_Needles,
                5: max_Pregnancy_Tests,
                6: max_Condoms,
                7: max_Bandaids,
                8: max_Wipes,
                9: max_Gloves,
                10: None,  # No cap defined for these IDs
                11: None,
                12: None,
            }
            max_allowed = MAX_PER_ITEM.get(idx)

            if max_allowed is not None:
                # Check whether the total dispensed across all rooms has reached the cap
                try:
                    current_total = dbaccess.get_total_count_for_item(idx)
                except Exception as e:
                    print(f"Unable to read totals for item {idx}: {e}")
                    current_total = 0

                if current_total >= max_allowed:
                    # Item is out of stock — do not increment the count
                    print(f"We have run out of stock of that item "
                          f"(total taken: {current_total} >= max {max_allowed}). Cannot take more.")
                else:
                    # Stock available — record the dispense
                    try:
                        new_count = dbaccess.increment_item_by_id(roomNumber, idx)
                        print(f"Updated item id {idx} for room {roomNumber}. New count: {new_count}")
                    except ValueError as ve:
                        print(f"Could not increment item: {ve}")
            else:
                # No maximum configured for this item — allow the increment unconditionally
                try:
                    new_count = dbaccess.increment_item_by_id(roomNumber, idx)
                    print(f"Updated item id {idx} for room {roomNumber}. New count: {new_count}")
                except ValueError as ve:
                    print(f"Could not increment item: {ve}")

        except ValueError:
            print("Invalid item number entered. Please enter a numeric item id from the item list.")

    # ---------------------------------------------------------------------------
    # Optional: print the entire database to the console
    # ---------------------------------------------------------------------------
    resp = input("\nPrint entire database contents? (y/N): ").strip().lower()
    if resp == 'y' or resp == 'yes':
        # Reload dbaccess in case the module reference was lost
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'databaseAccess.py'))
        spec = importlib.util.spec_from_file_location('dbaccess', db_path)
        dbaccess = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dbaccess)
        dbaccess.init_db()
        dbaccess.print_database()

        # Optionally reset counts for a specific item (e.g. after restocking)
        resp_reset_item = input("\nReset counts for an item across all rooms? (y/N): ").strip().lower()
        if resp_reset_item in ('y', 'yes'):
            item_input = input("Enter item id or exact item name to reset: ").strip()
            try:
                iid = int(item_input)  # Try treating as numeric id first
                try:
                    changed = dbaccess.reset_item_counts(iid)
                    print(f"Reset counts for item id {iid} across rooms. Rows updated: {changed}")
                except Exception as e:
                    print(f"Failed to reset by id: {e}")
            except ValueError:
                # Not a number — treat as item name
                try:
                    changed = dbaccess.reset_item_counts_by_name(item_input)
                    print(f"Reset counts for item '{item_input}' across rooms. Rows updated: {changed}")
                except Exception as e:
                    print(f"Failed to reset by name: {e}")

    # ---------------------------------------------------------------------------
    # Optional: email the full database dump with a restock summary
    # ---------------------------------------------------------------------------
    es = input("\nSend this dump by email? (y/N): ").strip().lower()
    if es in ('y', 'yes'):
        to   = input("Recipient email address: ").strip()
        subj = input("Email subject (default 'Database dump'): ").strip() or "Database dump"

        # Load the gmail_send helper dynamically (same pattern as dbaccess above)
        gpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'gmail_send.py'))
        spec2 = importlib.util.spec_from_file_location('gmail_send', gpath)
        gmail_send = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(gmail_send)

        # Build the email body from the full database dump
        body = dbaccess.dump_database_text()

        # Append a restock summary: items where ≥70% of stock has been dispensed
        MAX_PER_ITEM = {
            1: max_Xylazine_Strips,
            2: max_Fentanyl_Strips,
            3: max_Cook_Strips,
            4: max_Clean_Needles,
            5: max_Pregnancy_Tests,
            6: max_Condoms,
            7: max_Bandaids,
            8: None,
            9: max_Gloves,
            10: max_Wipes,
            11: None,
            12: None,
        }
        items = dbaccess.get_all_items_with_totals()
        restock_lines = []
        for iid, name, total in items:
            max_allowed = MAX_PER_ITEM.get(iid)
            if max_allowed is None or max_allowed <= 0:
                continue
            frac = float(total) / float(max_allowed)
            if frac >= 0.7:  # Flag items that are 70% or more depleted
                restock_lines.append(
                    f"{name} (id {iid}): taken {total} of {max_allowed} ({frac:.0%} taken)"
                )

        if not restock_lines:
            restock_text = "\n\n--- RESTOCK NEEDED ---\nNo items need restocking.\n"
        else:
            restock_text = "\n\n--- RESTOCK NEEDED ---\n" + "\n".join(restock_lines) + "\n"

        body = body + restock_text
        print("Sending email (this will open a browser for OAuth if needed)...")
        res = gmail_send.send_email(to, subj, body)
        print("Email sent, id:", res.get('id'))


if __name__ == "__main__":
    main()
