"""Run from the repo root:  python3 tests/test_core.py   (also works under pytest)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from novelty.core import accounts, catalog, reviews  # noqa: E402
from novelty.errors import NoveltyError  # noqa: E402
from novelty.store import Store  # noqa: E402


def fresh():
    s = Store(tempfile.mkdtemp())
    s.books.append({"book_id": "b0001", "title": "T", "author": "A", "category": "c", "date_added": "2026-01-01",
                    "price": 10.0, "cover_path": "", "text_path": "", "stock": 5, "copies_sold": 0})
    s.save("books")
    s.save_taboo({"darn", "heck"})
    return s, accounts.register(s, "Ana")


def raises(fn, *args):
    try:
        fn(*args)
    except NoveltyError as e:
        return str(e)
    raise AssertionError("expected NoveltyError")


def test_overdraft_fine_suspend_reopen():
    s, u = fresh()
    assert "fine" in raises(accounts.purchase, s, u, s.books[0])
    assert u["balance"] == -1 and u["status"] == "suspended"
    raises(accounts.reopen, s, u, 0)
    accounts.reopen(s, u, 5)
    assert u["status"] == "active" and u["balance"] == 4


def test_vip_discount_promotion_stock():
    s, u = fresh()
    accounts.deposit(s, u, 100)
    for _ in range(4):
        accounts.purchase(s, u, s.books[0])
    assert u["role"] == "VC" and u["balance"] == 60
    accounts.purchase(s, u, s.books[0])  # 10% off
    assert u["balance"] == 51 and s.books[0]["stock"] == 0
    assert raises(accounts.purchase, s, u, s.books[0]) == "Out of stock"


def test_taboo_filter_and_warnings():
    s, u = fresh()
    assert reviews.filter_taboo("Darn it, heck", s.taboo()) == ("**** it, ****", 2)
    reviews.rate(s, s.books[0], u, 5, "darn good")
    assert s.ratings[0]["comment"] == "**** good"
    bad = "darn heck darn heck"
    for _ in range(3):
        raises(reviews.rate, s, s.books[0], u, 1, bad)
    assert u["warnings"] == 3 and u["status"] == "suspended"
    u["role"], u["status"] = "VC", "active"
    raises(reviews.rate, s, s.books[0], u, 1, bad)
    assert u["role"] == "RC"
    raises(reviews.add_taboo, s, " DARN ")
    reviews.add_taboo(s, "Blah")
    assert "blah" in s.taboo()


def test_weighted_avg_and_order_lists():
    s, u = fresh()
    accounts.deposit(s, u, 20)
    accounts.purchase(s, u, s.books[0])
    reviews.rate(s, s.books[0], u, 5, "")  # verified purchaser, weight 2
    for _ in range(3):
        reviews.rate(s, s.books[0], None, 4, "")
    assert reviews.weighted_avg(s, "b0001") == (4.4, 4)
    assert catalog.order_lists(s) == ([s.books[0]], [])


def test_persisted():
    s, u = fresh()
    accounts.deposit(s, u, 7.5)
    again = Store(s.dir)
    assert again.users[0]["balance"] == 7.5
    assert again.transactions("u0001")[0]["amount"] == "7.50"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
