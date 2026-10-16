# read_frontier.py
import shelve
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "frontier.shelve"

with shelve.open(path, flag="r") as db:
    entries = list(db.values())  # each value is (url, completed)

done = [url for url, completed in entries if completed]
pending = [url for url, completed in entries if not completed]

print(f"Total URLs: {len(entries)}")
print(f"Completed:  {len(done)}")
print(f"Pending:    {len(pending)}")

if "--list" in sys.argv:
    print("\n--- Completed ---")
    for url in done:
        print(url)
    print("\n--- Pending ---")
    for url in pending:
        print(url)
