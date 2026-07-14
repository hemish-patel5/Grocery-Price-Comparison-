import re

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_RESULT_LIMIT = 100


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    # split into words so 'free range eggs' matches names with the words in
    # any order; strip a trailing 's' so 'eggs' also matches 'egg'
    terms = re.findall(r"[a-z0-9&']+", query.lower())
    stems = list(dict.fromkeys(
        t[:-1] if len(t) > 3 and t.endswith("s") else t for t in terms
    ))
    if not stems:
        return jsonify([])

    # matching, relevance ranking, cheapest-store lookup and deduping all
    result = get_client().rpc("search_products", {
        "p_stems": stems,
        "p_limit": SEARCH_RESULT_LIMIT,
    }).execute()

    return jsonify([
        {
            **row,
            "store": "Woolworths",
            "original_price": f"{row['original_price']:.2f}" if row["original_price"] is not None else None,
            "sale_price": f"{row['sale_price']:.2f}" if row["sale_price"] is not None else None,
        }
        for row in result.data
    ])


@app.route("/api/product/<product_id>/prices")
def product_prices(product_id):
    """Every store's price for one product, cheapest first. Backs the
    per-store comparison dropdown on the product cards."""
    result = (
        get_client()
        .table("store_prices")
        .select("price, original_price, sale_price, unit_price, stores(store_key, address)")
        .eq("product_id", product_id)
        .order("price")
        .execute()
    )

    prices = []
    for row in result.data:
        store = row.pop("stores") or {}
        prices.append({
            **row,
            "store": "Woolworths",
            "store_key": store.get("store_key"),
            "store_address": store.get("address"),
            "original_price": f"{row['original_price']:.2f}" if row["original_price"] is not None else None,
            "sale_price": f"{row['sale_price']:.2f}" if row["sale_price"] is not None else None,
        })
    return jsonify(prices)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
