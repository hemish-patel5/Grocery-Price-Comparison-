import re

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_FETCH_LIMIT = 1000
SEARCH_RESULT_LIMIT = 100


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
    if not query:
        return jsonify([])

    # commas/parens would break the PostgREST or() filter syntax
    safe_query = re.sub(r"[(),]", " ", query).strip()

    client = get_client()
    result = (
        client.table("products")
        .select(
            "product_id, name, brand, price, original_price, sale_price, "
            "size, unit_price, department, aisle, image_url, "
            "stores(store_key, address)"
        )
        # match the product name OR its aisle label, so searching 'eggs'
        # also finds everything shelved in the Eggs aisle
        .or_(f"name.ilike.%{safe_query}%,aisle.ilike.%{safe_query}%")
        .order("price")
        .limit(SEARCH_FETCH_LIMIT)
        .execute()
    )

    query_words = words(query)

    def relevance_tier(row):
        """0 = query matches the product's name AND its aisle label (real
        eggs in the 'Eggs, Butter & Spreads' aisle), 1 = one of the two
        (margarine in that aisle, or a chocolate 'egg' by name), 2 = rest."""
        name_hit = bool(query_words & words(f"{row.get('name')} {row.get('brand')}"))
        aisle_hit = bool(query_words & words(row.get("aisle")))
        if name_hit and aisle_hit:
            return 0
        if name_hit or aisle_hit:
            return 1
        return 2

    # The same product is stored once per scraped store. Rows arrive sorted
    # cheapest-first, so keeping the first row per product keeps its
    # cheapest store.
    deduped = []
    seen_product_ids = set()
    for row in result.data:
        if row["product_id"] in seen_product_ids:
            continue
        seen_product_ids.add(row["product_id"])
        deduped.append(row)

    # most relevant tier first, cheapest first within each tier
    deduped.sort(key=lambda row: (
        relevance_tier(row),
        row["price"] if row["price"] is not None else float("inf"),
    ))

    products = []
    for row in deduped[:SEARCH_RESULT_LIMIT]:
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
