import re
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request
SEARCH_RESULT_LIMIT = 100
CHEAPEST_LOOKUP_CHUNK = 50  # 50 product ids x 11 stores stays under PAGE_SIZE

SELECT_COLUMNS = (
    "product_id, name, brand, price, original_price, sale_price, "
    "size, unit_price, department, aisle, image_url, "
    "stores(store_key, address)"
)

_reference_store_id = None


def reference_store_id(client):
    """The store with the most scraped products.

    Each product is stored once per store, so a broad query like 'milk'
    matches thousands of near-duplicate rows -- far beyond the 1000-row
    response cap, which used to silently drop everything above ~$3.50.
    Searching a single store first keeps the fetch small and complete;
    the cheapest store for each displayed product is resolved afterwards.
    Counted once and cached for the life of the process.
    """
    global _reference_store_id
    if _reference_store_id is None:
        stores = client.table("stores").select("id").execute().data
        if not stores:
            return None

        def count_rows(store):
            result = (
                client.table("products")
                .select("product_id", count="exact")
                .eq("store_id", store["id"])
                .limit(1)
                .execute()
            )
            return store["id"], result.count or 0

        with ThreadPoolExecutor(max_workers=len(stores)) as pool:
            counts = list(pool.map(count_rows, stores))
        _reference_store_id = max(counts, key=lambda pair: pair[1])[0]
    return _reference_store_id


def words(text):
    """Lowercase words plus singular forms, so 'eggs' matches 'egg'."""
    found = set(re.findall(r"[a-z0-9&']+", (text or "").lower()))
    return found | {w[:-1] for w in found if w.endswith("s")}


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    # match each word separately so 'free range eggs' finds names with the
    # words in any order; strip a trailing 's' so 'eggs' also matches 'egg'.
    # words contain only [a-z0-9&'], so they can't break the or() syntax
    terms = re.findall(r"[a-z0-9&']+", query.lower())
    stems = list(dict.fromkeys(
        t[:-1] if len(t) > 3 and t.endswith("s") else t for t in terms
    ))
    if not stems:
        return jsonify([])

    client = get_client()
    store_id = reference_store_id(client)
    if store_id is None:
        return jsonify([])

    def sort_key(row):
        name_words = words(f"{row.get('name')} {row.get('brand')}")
        aisle_words = words(row.get("aisle"))
        name_hit = any(s in name_words for s in stems)
        aisle_hit = any(s in aisle_words for s in stems)
        # relevance first: products whose name AND aisle both match (real
        # milk in the Milk aisle), then name-only matches (m&m 'milk'
        # chocolate), then aisle-only matches (cream in the Milk aisle),
        # then substring-only matches ('egg' inside 'eggplant');
        # cheapest first within each group
        if name_hit and aisle_hit:
            group = 0
        elif name_hit:
            group = 1
        elif aisle_hit:
            group = 2
        else:
            group = 3
        price = row["price"] if row["price"] is not None else float("inf")
        return (group, price)

    # Phase 1: find and rank every matching product within the reference
    # store, fetching only the columns the ranking needs
    db_query = (
        client.table("products")
        .select("product_id, name, brand, size, aisle, price")
        .eq("store_id", store_id)
    )
    # chained or_() filters are ANDed by PostgREST: every query word must
    # appear somewhere in the product's name, brand, size, or aisle label
    for stem in stems:
        db_query = db_query.or_(
            f"name.ilike.%{stem}%,brand.ilike.%{stem}%,"
            f"size.ilike.%{stem}%,aisle.ilike.%{stem}%"
        )
    candidates = db_query.order("price").limit(PAGE_SIZE).execute().data

    # the same item sometimes exists under two product ids with identical
    # name/brand/size; rows arrive cheapest-first, so keep the first
    seen_items = set()
    deduped = []
    for row in candidates:
        item_key = (
            (row.get("name") or "").lower(),
            (row.get("brand") or "").lower(),
            row.get("size"),
        )
        if item_key in seen_items:
            continue
        seen_items.add(item_key)
        deduped.append(row)

    deduped.sort(key=sort_key)
    top_ids = [row["product_id"] for row in deduped[:SEARCH_RESULT_LIMIT]]

    # Phase 2: for just the products being displayed, fetch their rows
    # across ALL stores and keep each product's cheapest store
    def fetch_chunk(ids):
        return (
            client.table("products")
            .select(SELECT_COLUMNS)
            .in_("product_id", ids)
            .order("price")
            .limit(PAGE_SIZE)
            .execute()
            .data
        )

    chunks = [
        top_ids[start:start + CHEAPEST_LOOKUP_CHUNK]
        for start in range(0, len(top_ids), CHEAPEST_LOOKUP_CHUNK)
    ]
    cheapest = {}
    if chunks:
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            for page in pool.map(fetch_chunk, chunks):
                for row in page:
                    current = cheapest.get(row["product_id"])
                    row_price = row["price"] if row["price"] is not None else float("inf")
                    current_price = (
                        current["price"]
                        if current is not None and current["price"] is not None
                        else float("inf")
                    )
                    if current is None or row_price < current_price:
                        cheapest[row["product_id"]] = row

    # re-rank with each product's true cheapest price
    final = [cheapest[pid] for pid in top_ids if pid in cheapest]
    final.sort(key=sort_key)

    products = []
    for row in final:
        store = row.pop("stores") or {}
        products.append({
            **row,
            "store": "Woolworths",
            "store_key": store.get("store_key"),
            "store_address": store.get("address"),
            "original_price": f"{row['original_price']:.2f}" if row["original_price"] is not None else None,
            "sale_price": f"{row['sale_price']:.2f}" if row["sale_price"] is not None else None,
        })

    return jsonify(products)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
