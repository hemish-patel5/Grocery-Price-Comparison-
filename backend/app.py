# pip install flask httpx flask-cors

from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app)

STORE_ID = 9023

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"


def search_woolworths(query: str, store_id: int):
    with httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
            "referer": "https://www.woolworths.co.nz/shop/searchproducts"
        },
        timeout=10.0
    ) as client:

        # Step 1: Start session
        client.get(BASE_URL)

        # Step 2: Set store
        client.cookies.set(
            "fulfilmentStoreId",
            str(store_id),
            domain=".woolworths.co.nz"
        )

        # Step 3: Call API
        params = {
            "target": "search",
            "search": query,
            "size": 48
        }

        res = client.get(API_URL, params=params)
        data = res.json()

        products = data.get("products", {}).get("items", [])

        def get_price(p):
            price_data = p.get("price", {})
            return price_data.get("salePrice") or price_data.get("originalPrice")

        valid = [p for p in products if get_price(p) is not None]
        valid.sort(key=get_price)

        return [
            {"name": p["name"], "price": get_price(p)}
            for p in valid
        ]


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    store_id = int(request.args.get("store", STORE_ID))

    if not query:
        return jsonify({"error": "Missing query"}), 400

    try:
        products = search_woolworths(query, store_id)
        return jsonify(products)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()