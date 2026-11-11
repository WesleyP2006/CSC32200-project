"""UC-01 recommend, UC-02 browse, UC-03 text search, UC-12 add book, UC-15 order lists."""
from datetime import date

from ..errors import NoveltyError
from .reviews import weighted_avg


def browse(store, category="", author="", since=""):
    return [b for b in store.books
            if (not category or b["category"].lower() == category.lower())
            and (not author or author.lower() in b["author"].lower())
            and (not since or b["date_added"] >= since)]


def search_text(store, q):
    q = q.lower()
    return [b for b in store.books
            if q in b["title"].lower() or q in b["author"].lower() or q in b["category"].lower()]


def recommend(store, user):
    popular = sorted(store.books, key=lambda b: -b.get("copies_sold", 0))
    if user and user["role"] in ("RC", "VC"):
        bought = {t["book_id"] for t in store.transactions(user["user_id"]) if t["type"] == "purchase"}
        cats = {b["category"] for b in store.books if b["book_id"] in bought}
        picks = [b for b in store.books if b["category"] in cats and b["book_id"] not in bought]
        picks.sort(key=lambda b: -(weighted_avg(store, b["book_id"])[0] or 0))
        return (picks + [b for b in popular if b not in picks])[:3]
    return popular[:3]


def order_lists(store):
    to_order, no_order = [], []
    for b in store.books:
        avg, n = weighted_avg(store, b["book_id"])
        if n > 3 and avg > 4:
            to_order.append(b)
        elif n > 3 and avg < 2:
            no_order.append(b)
    return to_order, no_order


def add_book(store, title, author, category, price, stock):
    if not (title.strip() and author.strip() and category.strip()):
        raise NoveltyError("Title, author and category are required")
    if price <= 0 or stock < 0:
        raise NoveltyError("Price must be above 0 and stock 0 or more")
    book = {"book_id": store.next_id("b", store.books, "book_id"), "title": title.strip(),
            "author": author.strip(), "category": category.strip(), "date_added": date.today().isoformat(),
            "price": round(price, 2), "cover_path": "", "text_path": "", "stock": stock, "copies_sold": 0}
    store.books.append(book)
    store.save("books")
    return book
