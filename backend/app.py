# pip install flask httpx flask-cors gunicorn

from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from functools import lru_cache

app = Flask(__name__)
CORS(app)

STORE_ID = 9023

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"

# ✅ Global persistent client (KEY FIX for Render timeouts)
client = httpx.Client(
    headers={
        "accept": "application/json",
        "user-agent": "Mozilla/5.0",
        "x-requested-with": "OnlineShopping.WebApp",
        "referer": "https://www.woolworths.co.nz/shop/searchproducts"
    },
    timeout=10.0
)

# Track if store cookie has been set
store_initialized = False


def init_store(store_id: int):
    global store_initialized

    if not store_initialized:
        try:
            # Start session
            client.get(BASE_URL)

            # Set store cookie
            client.cookies.set(
                "fulfilmentStoreId",
                str(store_id),
                domain=".woolworths.co.nz"
            )

            store_initialized = True
        except Exception:
            pass


def search_woolworths(query: str, store_id: int):
    init_store(store_id)

    params = {
        "target": "search",
        "search": query,
        "size": 48
    }

    try:
        res = client.get(API_URL, params=params)
        data = res.json()
    except Exception:
        return []

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


# ✅ Cache results (huge speed boost)
@lru_cache(maxsize=100)
def cached_search(query, store_id):
    return tuple(search_woolworths(query, store_id))


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    store_id = int(request.args.get("store", STORE_ID))

    if not query:
        return jsonify([])

    try:
        products = list(cached_search(query, store_id))
        return jsonify(products)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return "API is running 🚀"


if __name__ == "__main__":
    app.run(debug=True)