import mfrc522
import sqlite3
import time

DB = "capturebox.db"
FACTIONS = {1: "Red", 2: "Blue", 3: "Green", 4: "Yellow"}

def get_uid(reader):
    while True:
        id, _ = reader.scan()
        if id:
            return "-".join([str(x) for x in id])
        time.sleep(0.2)

def main():
    reader = mfrc522.SimpleMFRC522()
    con = sqlite3.connect(DB)

    print("\n=== CaptureBox NFC Admin ===")
    print("1) Register card to faction")
    print("2) Reset card")
    print("3) Show card info")
    choice = input("Choice: ").strip()

    print("Scan card now...")
    uid = get_uid(reader)
    print(f"Card UID: {uid}")

    if choice == "1":
        print("Factions:", FACTIONS)
        faction = int(input("Faction (1-4): ").strip())
        con.execute("""
            INSERT OR REPLACE INTO cards (uid, faction_id, registered_at)
            VALUES (?, ?, datetime('now'))
        """, (uid, faction))
        con.commit()
        print(f"Registered to {FACTIONS[faction]}")

    elif choice == "2":
        con.execute("DELETE FROM cards WHERE uid = ?", (uid,))
        con.commit()
        print("Card reset — blank again")

    elif choice == "3":
        cur = con.execute("SELECT * FROM cards WHERE uid = ?", (uid,))
        row = cur.fetchone()
        if row:
            print(f"UID: {row[0]}, Faction: {FACTIONS.get(row[1], '?')}, Registered: {row[2]}")
        else:
            print("Card not registered")

    con.close()

if __name__ == "__main__":
    main()