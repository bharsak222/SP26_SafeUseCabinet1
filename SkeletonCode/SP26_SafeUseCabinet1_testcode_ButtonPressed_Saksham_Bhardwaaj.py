# ButtonPressed.py
# Provides simple terminal-input helper functions for the SafeUseCabinet
# skeleton interface. MainSkeleton.py calls these to collect the room number,
# item ID, and email preference from a keyboard before interacting with the
# database and conveyor system.

def getRoomNumber():
    # Prompt the operator to type the 3-digit room number and strip whitespace
    print("Enter Room Number:")
    return input().strip()

def getItemChosen():
    # Prompt the operator to enter the numeric item ID (maps to a dispenser slot)
    print("Enter item Number:")
    return input().strip()

def getEmail():
    # Ask whether a database-dump email should be sent after this transaction
    print("Want email? 1 yes, 2 no:")
    return input().strip()
