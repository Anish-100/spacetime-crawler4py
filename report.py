import json
from collections import Counter
from urllib.parse import urlparse

urls = set(open("files/pages_visited.txt").read().split())
print("Unique pages:", len(urls))

data = json.load(open("files/stats.json"))
print("Longest page:", data["longest"])

print("\nTop 50 words:")
for w, c in Counter(data["words"]).most_common(50):
    print(w, c)

subs = Counter()
for u in urls:
    host = urlparse(u).hostname
    if host and host.endswith(".ics.uci.edu"):
        subs["http://" + host] += 1
print("\nics.uci.edu subdomains:", len(subs))
for s in sorted(subs):
    print(f"{s}, {subs[s]}")