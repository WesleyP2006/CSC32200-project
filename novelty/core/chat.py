"""UC-10 Chat with the System: answer from store information (RAG) when it covers the question, else the LLM.

answer() returns (text, tag). The tag says where the answer came from:
  "via RAG · hours.txt"   matching store information was retrieved and given to the model
  "LLM · llama3.2"        nothing in the store information matched; the model answered on its own
  "restricted"            the best match is information this user may not see (SR-01, SR-03)

Questions about yourself ("my balance", "what have I bought") always get your own account record, even when
it scores below the threshold, and are never refused: they are about your own data.

What the chatbot can draw on, and who may see it:
  data/store_info/*.txt      everyone; a file whose name starts with "finance" or "admin" is SU only
  the catalog                everyone (built live from books.json and ratings.json)
  the finance report         SU only (built live from transactions.csv, users.json and books.json)
  "your account"             only the logged in RC/VC it describes
"""
import os
import re
from collections import defaultdict

from ..errors import NoveltyError, Unavailable
from . import accounts, llm, rag
from .reviews import weighted_avg

TOP_K = 3                              # store chunks given to the model per question
SU_ONLY_FILES = ("finance", "admin")   # store_info files whose names start with these are SU only
ABOUT_ME = {"i", "me", "my", "mine", "myself", "im", "ive"}

RAG_SYSTEM = ("You are the assistant of Novelty, a small bookstore desktop app. Answer the question using only "
              "the store information below. Keep it short: one to four sentences. If the information does not "
              "answer the question, say that you don't have that information.")
LLM_SYSTEM = ("You are the assistant of Novelty, a small bookstore desktop app. Answer the question directly and "
              "briefly, in one to four sentences. General-knowledge questions are fine: just answer them, with no "
              "disclaimer. You cannot see this store's own records, so ONLY when the question is about this "
              "store's hours, books, prices, stock, sales, money or someone's account, say that you don't have "
              "that information.")
RESTRICTED = "Sorry, that information is only available to the store administrator."


def answer(store, question, user):
    question = question.strip()
    if not question:
        raise NoveltyError("Type a question first")
    method, scored = rag.search(question, documents(store, user), cache_path(store))
    limit = rag.THRESHOLD[method]
    about_me = bool(ABOUT_ME & set(re.findall(r"[a-z]+", question.lower().replace("'", ""))))
    if not about_me and scored and scored[0][0] >= limit and not can_see(user, scored[0][1]):
        return RESTRICTED, "restricted"  # refused before the model ever sees the hidden text
    hits = [c for s, c in scored if s >= limit and can_see(user, c)][:TOP_K]
    if about_me:
        mine = [c for _, c in scored if c["owner"] is not None and can_see(user, c)]
        hits = mine + [c for c in hits if c not in mine]
    if not hits:
        return llm.chat(LLM_SYSTEM, question), f"LLM · {llm.CHAT_MODEL}"

    tag = "via RAG · " + ", ".join(dict.fromkeys(c["source"] for c in hits))
    if method == "keyword":
        tag += " (keyword match)"
    context = "\n\n".join(f"[{c['source']}]\n{c['text']}" for c in hits)
    try:
        return llm.chat(RAG_SYSTEM, f"Store information:\n{context}\n\nQuestion: {question}"), tag
    except Unavailable:  # SR-08: retrieval still works without the model, so show what was found
        return hits[0]["text"], tag + " · Ollama is offline, showing the matching store text"


def can_see(user, chunk):
    role = user["role"] if user else "VS"
    return role in chunk["roles"] and chunk["owner"] in (None, user and user["user_id"])


def cache_path(store):
    return os.path.join(store.path("rag_cache"), "store.json")


def documents(store, user):
    """Every chunk the chatbot can search, each tagged with who may see it."""
    chunks = []
    if user and user["role"] in ("RC", "VC"):
        chunks += account_chunks(store, user)  # first, so "my ..." questions prefer it on a tie
    folder = store.path("store_info")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".txt"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        roles = ("SU",) if name.lower().startswith(SU_ONLY_FILES) else rag.EVERYONE
        chunks += rag.make_chunks(name, text, roles)
    chunks += catalog_chunks(store)
    chunks += finance_chunks(store)
    return chunks


def _chunk(source, text, roles=rag.EVERYONE, owner=None):
    return {"source": source, "text": text, "roles": list(roles), "owner": owner}


def catalog_chunks(store):
    """One chunk per book, plus a summary, so "who wrote Dracula?" finds exactly that book."""
    books = store.books
    if not books:
        return []
    out = [_chunk("catalog", f"Novelty's catalog has {len(books)} books in these categories: "
                             f"{', '.join(sorted({b['category'] for b in books}))}. Authors: "
                             f"{', '.join(sorted({b['author'] for b in books}))}.")]
    for b in books:
        avg, n = weighted_avg(store, b["book_id"])
        vip = b["price"] * (1 - accounts.VIP_DISCOUNT)
        out.append(_chunk("catalog", (
            f'"{b["title"]}" by {b["author"]}. Category: {b["category"]}. Price ${b["price"]:.2f} '
            f"(VIP customers pay ${vip:.2f}). "
            + (f'{b["stock"]} in stock.' if b["stock"] else "Out of stock.")
            + (f" Rated {avg} out of 5 from {n} review(s)." if n else " No reviews yet.")
            + f' Added to the store on {b["date_added"]}.')))
    return out


def finance_chunks(store):
    """SU only. Built fresh for every question, so the numbers are never out of date."""
    tx = store.transactions()
    count, total = defaultdict(int), defaultdict(float)
    sold, revenue = defaultdict(int), defaultdict(float)
    for t in tx:
        amount = float(t["amount"] or 0)
        count[t["type"]] += 1
        total[t["type"]] += amount
        if t["type"] == "purchase":
            sold[t["book_id"]] += 1
            revenue[t["book_id"]] += amount
    customers = [u for u in store.users if u["role"] in ("RC", "VC")]
    texts = [
        f"Store finances, from the transaction records: ${total['purchase']:.2f} revenue from "
        f"{count['purchase']} book sale(s). Customers deposited ${total['deposit']:.2f} in "
        f"{count['deposit']} deposit(s). Overdraft fines collected: ${total['fine']:.2f} from "
        f"{count['fine']} fine(s). Money held in customer balances: "
        f"${sum(u['balance'] for u in customers):.2f}.",
    ]
    if store.books:
        best = sorted(store.books, key=lambda b: (-revenue[b["book_id"]], -b.get("copies_sold", 0)))
        texts.append("Sales by book, best sellers first: " + "; ".join(
            f'"{b["title"]}" {sold[b["book_id"]]} sold in recorded transactions for '
            f'${revenue[b["book_id"]]:.2f}, {b.get("copies_sold", 0)} copies sold in total' for b in best) + ".")
        low = [f'"{b["title"]}" ({b["stock"]} left)' for b in store.books if b["stock"] <= 2]
        texts.append(f"Inventory: {sum(b['stock'] for b in store.books)} copies in stock, worth "
                     f"${sum(b['stock'] * b['price'] for b in store.books):.2f} at list price. Low or out of "
                     f"stock: {', '.join(low) or 'none'}.")
    if customers:
        texts.append("Customer accounts: " + "; ".join(
            f'{u["name"]} ({u["role"]}) balance ${u["balance"]:.2f}, {u["status"]}, {u["warnings"]} warning(s)'
            for u in customers) + ".")
    return [_chunk("finance report", t, roles=("SU",)) for t in texts]


def account_chunks(store, user):
    """The logged-in customer's own account, one short chunk per topic; nobody else's is ever built."""
    count, spent = accounts.vip_progress(store, user)
    titles = {b["book_id"]: b["title"] for b in store.books}
    bought = [titles.get(t["book_id"], t["book_id"]) for t in store.transactions(user["user_id"])
              if t["type"] == "purchase"]
    name = user["name"]
    texts = [
        f"Your balance: {name}, your account balance is ${user['balance']:.2f}. Your account is "
        f"{user['status']} and has {user['warnings']} warning(s).",
        f"Your purchases: {name}, you have bought {count} book(s) for ${spent:.2f} in total: {', '.join(bought)}."
        if bought else f"Your purchases: {name}, you have not bought any books yet.",
        f"Your membership: {name}, you are a VIP customer, so you get 10% off every book."
        if user["role"] == "VC" else
        f"Your membership: {name}, you are a registered customer. You become a VIP customer (10% off every "
        f"book) after more than {accounts.VIP_MIN_PURCHASES} purchases or more than "
        f"${accounts.VIP_MIN_SPENT:.0f} spent. So far: {count} purchase(s), ${spent:.2f} spent.",
    ]
    return [_chunk("your account", t, roles=(user["role"],), owner=user["user_id"]) for t in texts]
