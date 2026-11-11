"""UC-09 rate and comment, UC-13 taboo words."""
import re
from datetime import datetime

from ..errors import NoveltyError


def filter_taboo(text, taboo):
    """Returns (text with taboo words starred out, how many were found)."""
    count = 0

    def sub(m):
        nonlocal count
        if m.group().lower() in taboo:
            count += 1
            return "*" * len(m.group())
        return m.group()

    return re.sub(r"[A-Za-z']+", sub, text), count


def rate(store, book, user, stars, comment):
    if stars not in range(1, 6):
        raise NoveltyError("Stars must be 1 to 5")
    cleaned, n = filter_taboo(comment, store.taboo())
    if n > 3:
        if user:
            user["warnings"] += 1
            if user["role"] == "VC":
                user["role"] = "RC"
            elif user["role"] == "RC" and user["warnings"] > 2:
                user["status"] = "suspended"
            store.save("users")
        raise NoveltyError(f"Comment blocked: {n} taboo words. A warning was issued.")
    verified = bool(user) and any(t["type"] == "purchase" and t["book_id"] == book["book_id"]
                                  for t in store.transactions(user["user_id"]))
    store.ratings.append({"rating_id": store.next_id("r", store.ratings, "rating_id"),
                          "book_id": book["book_id"], "user_id": user["user_id"] if user else None,
                          "stars": stars, "comment": cleaned, "verified": verified,
                          "timestamp": datetime.now().isoformat(timespec="seconds")})
    store.save("ratings")


def weighted_avg(store, book_id):
    """Verified purchasers count double. Returns (average or None, number of ratings)."""
    rs = [r for r in store.ratings if r["book_id"] == book_id]
    if not rs:
        return None, 0
    w = [2 if r["verified"] else 1 for r in rs]
    return round(sum(r["stars"] * x for r, x in zip(rs, w)) / sum(w), 2), len(rs)


def add_taboo(store, word):
    w, words = word.strip().lower(), store.taboo()
    if not w or w in words:
        raise NoveltyError("Empty or duplicate word")
    words.add(w)
    store.save_taboo(words)


def remove_taboo(store, word):
    w, words = word.strip().lower(), store.taboo()
    if w not in words:
        raise NoveltyError("Word is not on the list")
    words.discard(w)
    store.save_taboo(words)
