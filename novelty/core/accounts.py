"""UC-05 register (temporary home), UC-07 deposit, UC-08 purchase, UC-14 reopen."""
from ..errors import NoveltyError

ROLES = ("VS", "RC", "VC", "SU")
VIP_DISCOUNT = 0.10
VIP_MIN_PURCHASES = 3   # strictly more than 3 purchases (i.e. >= 4)
VIP_MIN_SPENT = 200.0   # strictly more than $200 spent
OVERDRAFT_FINE = 1.0


def register(store, name, face_ref="", voice_ref=""):
    # shortcut: no face/voice samples yet, move to auth.py when biometrics land
    name = name.strip()
    if not name:
        raise NoveltyError("Name is required")
    if any(u["name"].lower() == name.lower() for u in store.users):
        raise NoveltyError("Name already taken")
    user = {
        "user_id": store.next_id("u", store.users, "user_id"),
        "name": name,
        "role": "RC",
        "balance": 0.0,
        "status": "active",
        "warnings": 0,
        "face_ref": face_ref,
        "voice_ref": voice_ref,
    }
    store.users.append(user)
    store.save("users")
    return user


def deposit(store, user, amount):
    if not user or user.get("role") not in ("RC", "VC"):
        raise NoveltyError("Only customers have a wallet")
    if amount <= 0:
        raise NoveltyError("Deposit must be more than $0")
    user["balance"] = round(user["balance"] + amount, 2)
    store.save("users")
    store.append_transaction(user["user_id"], "deposit", None, amount)
    return user["balance"]


def checkout_price(user, book):
    """Return book price with 10% VIP discount applied for VC users."""
    role = user.get("role", "VS") if user else "VS"
    multiplier = (1.0 - VIP_DISCOUNT) if role == "VC" else 1.0
    return round(float(book["price"]) * multiplier, 2)


def vip_progress(store, user):
    """Return (purchase_count, total_spent) for an RC/VC user."""
    if not user or not user.get("user_id"):
        return 0, 0.0
    bought = [t for t in store.transactions(user["user_id"]) if t["type"] == "purchase"]
    return len(bought), round(sum(float(t["amount"]) for t in bought), 2)


def purchase(store, user, book):
    if not user or user["role"] not in ("RC", "VC"):
        raise NoveltyError("Only customers can buy")
    if user["status"] != "active":
        raise NoveltyError("Account suspended")
    if book["stock"] < 1:
        raise NoveltyError("Out of stock")

    price = checkout_price(user, book)
    if price > user["balance"]:
        user["balance"] = round(user["balance"] - OVERDRAFT_FINE, 2)
        if user["balance"] < 0:
            user["status"] = "suspended"
        store.save("users")
        store.append_transaction(user["user_id"], "fine", None, OVERDRAFT_FINE)
        raise NoveltyError(
            "Not enough money: $1 fine charged"
            + (", account suspended" if user["status"] == "suspended" else "")
        )

    user["balance"] = round(user["balance"] - price, 2)
    book["stock"] -= 1
    book["copies_sold"] = book.get("copies_sold", 0) + 1
    store.append_transaction(user["user_id"], "purchase", book["book_id"], price)

    if user["role"] == "RC":
        count, spent = vip_progress(store, user)
        if count > VIP_MIN_PURCHASES or spent > VIP_MIN_SPENT:
            user["role"] = "VC"

    store.save("users")
    store.save("books")
    return price


def reopen(store, user, amount=0):
    """SU reopens a suspended account; a suspended user cannot log in to deposit, so the SU can deposit here."""
    if amount < 0:
        raise NoveltyError("Deposit cannot be negative")
    if amount > 0:
        deposit(store, user, amount)
    if user["balance"] <= 0:
        raise NoveltyError("Balance must be positive before reopening")
    user["status"] = "active"
    user["warnings"] = 0
    store.save("users")