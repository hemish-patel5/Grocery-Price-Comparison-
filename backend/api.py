from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_FETCH_LIMIT = 1000
SEARCH_RESULT_LIMIT = 100


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    client = get_client()
    result = (
        client.table("products")
        .select(
            "product_id, name, brand, price, original_price, sale_price, "
            "is_on_special, size, unit_price, department, barcode, "
            "image_url, product_url, stores(store_key, address)"
        )
        .ilike("name", f"%{query}%")
        .order("price")
        .limit(SEARCH_FETCH_LIMIT)
        .execute()
    )

    # The same product is stored once per scraped store. Rows arrive sorted
    # cheapest-first, so keeping the first row per product keeps its
    # cheapest store.
    products = []
    seen_product_ids = set()
    for row in result.data:
        if row["product_id"] in seen_product_ids:
            continue
        seen_product_ids.add(row["product_id"])

        store = row.pop("stores") or {}
        products.append({
            **row,
            "store": "Woolworths",
            "store_key": store.get("store_key"),
            "store_address": store.get("address"),
            "price": f"{row['price']:.2f}" if row["price"] is not None else None,
        })

        if len(products) >= SEARCH_RESULT_LIMIT:
            break

    return jsonify(products)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
