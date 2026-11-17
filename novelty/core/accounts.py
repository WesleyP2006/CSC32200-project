"""UC-05 register (temporary home), UC-07 deposit, UC-08 purchase, UC-14 reopen."""
from ..errors import NoveltyError


def register(store, name):
    # shortcut: no face/voice samples yet, move to auth.py when biometrics land
    name = name.strip()
    if not name:
        raise NoveltyError("Name is required")
    if any(u["name"].lower() == name.lower() for u in store.users):
        raise NoveltyError("Name already taken")
    user = {"user_id": store.next_id("u", store.users, "user_id"), "name": name, "role": "RC",
            "balance": 0.0, "status": "active", "warnings": 0, "face_ref": "", "voice_ref": ""}
    store.users.append(user)
    store.save("users")
    return user


def deposit(store, user, amount):
    if amount <= 0:
        raise NoveltyError("Deposit must be more than $0")
    user["balance"] = round(user["balance"] + amount, 2)
    store.save("users")
    store.append_transaction(user["user_id"], "deposit", None, amount)


def purchase(store, user, book):
    if user["role"] not in ("RC", "VC"):
        raise NoveltyError("Only customers can buy")
    if user["status"] != "active":
        raise NoveltyError("Account suspended")
    if book["stock"] < 1:
        raise NoveltyError("Out of stock")
    price = round(book["price"] * (0.9 if user["role"] == "VC" else 1), 2)
    if price > user["balance"]:
        user["balance"] = round(user["balance"] - 1, 2)
        if user["balance"] < 0:
            user["status"] = "suspended"
        store.save("users")
        store.append_transaction(user["user_id"], "fine", None, 1)
        raise NoveltyError("Not enough money: $1 fine charged"
                           + (", account suspended" if user["status"] == "suspended" else ""))
    user["balance"] = round(user["balance"] - price, 2)
    book["stock"] -= 1
    book["copies_sold"] = book.get("copies_sold", 0) + 1
    store.append_transaction(user["user_id"], "purchase", book["book_id"], price)
    if user["role"] == "RC":
        bought = [t for t in store.transactions(user["user_id"]) if t["type"] == "purchase"]
        if len(bought) > 3 or sum(float(t["amount"]) for t in bought) > 200:
            user["role"] = "VC"
    store.save("users")
    store.save("books")
    return price


def reopen(store, user, amount=0):
    """SU reopens a suspended account; a suspended user cannot log in to deposit, so the SU can deposit here."""
    if amount > 0:
        deposit(store, user, amount)
    if user["balance"] <= 0:
        raise NoveltyError("Balance must be positive before reopening")
    user["status"] = "active"
    store.save("users")
