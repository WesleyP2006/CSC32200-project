"""Owns the data files (SRS Appendix A). Lists are loaded once; call save(name) after changing one."""
import csv
import json
import os
from datetime import datetime


class Store:
    def __init__(self, data_dir):
        self.dir = str(data_dir)
        self.users = self._load("users")
        self.books = self._load("books")
        self.ratings = self._load("ratings")

    def path(self, name):
        return os.path.join(self.dir, name)

    def _load(self, name):
        try:
            with open(self.path(name + ".json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def save(self, name):
        tmp = self.path(name + ".json.tmp")
        with open(tmp, "w") as f:
            json.dump(getattr(self, name), f, indent=1)
        os.replace(tmp, self.path(name + ".json"))  # atomic: a crash never leaves a half-written file

    def next_id(self, prefix, items, key):
        n = max((int(i[key][1:]) for i in items), default=0) + 1
        return f"{prefix}{n:04d}"

    def transactions(self, user_id=None):
        try:
            with open(self.path("transactions.csv"), newline="") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError:
            return []
        return [r for r in rows if user_id is None or r["user_id"] == user_id]

    def append_transaction(self, user_id, kind, book_id, amount):
        path = self.path("transactions.csv")
        tid = f"t{len(self.transactions()) + 1:04d}"
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["transaction_id", "user_id", "type", "book_id", "amount", "timestamp"])
            w.writerow([tid, user_id, kind, book_id or "", f"{amount:.2f}",
                        datetime.now().isoformat(timespec="seconds")])

    def taboo(self):
        try:
            with open(self.path("taboo_words.txt")) as f:
                return {w.strip().lower() for w in f if w.strip()}
        except FileNotFoundError:
            return set()

    def save_taboo(self, words):
        tmp = self.path("taboo_words.txt.tmp")
        with open(tmp, "w") as f:
            f.write("\n".join(sorted(words)) + "\n")
        os.replace(tmp, self.path("taboo_words.txt"))
