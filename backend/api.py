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
    # happen in Postgres (see backend/sql/normalize_schema.sql)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
