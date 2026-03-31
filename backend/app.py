# pip install flask httpx flask-cors gunicorn

from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app)

STORE_ID = 9023

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"

# ✅ Proper browser-like headers (VERY IMPORTANT)
client = httpx.Client(
    headers={
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-NZ,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "x-requested-with": "OnlineShopping.WebApp",
        "referer": "https://www.woolworths.co.nz/shop/searchproducts",
        "origin": "https://www.woolworths.co.nz"
    },
    timeout=10.0
)


def search_woolworths(query: str, store_id: int):
    try:
        # Step 1: Start session
        client.get(BASE_URL)

        # Step 2: Set store cookie
        client.cookies.set(
            "fulfilmentStoreId",
            str(store_id),
            domain=".woolworths.co.nz"
        )

        # Step 3: API request with store header
        params = {
            "target": "search",
            "search": query,
            "size": 24
        }

        res = client.get(
            API_URL,
            params=params,
            headers={
                "x-fulfilment-store-id": str(store_id),
                "accept": "application/json"
            }
        )

        # 🔍 DEBUG (check Render logs)
        print("STATUS:", res.status_code)
        print("URL:", res.url)
        print("TEXT SAMPLE:", res.text[:300])

        data = res.json()

    except Exception as e:
        print("ERROR:", e)
        return []

    products = data.get("products", {}).get("items", [])

    def get_price(p):
        price_data = p.get("price", {})
        return (
            price_data.get("salePrice")
            or price_data.get("originalPrice")
            or price_data.get("price")
        )

    print("TOTAL PRODUCTS:", len(products))

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
        return jsonify([])

    try:
        products = search_woolworths(query, store_id)
        return jsonify(products)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return "API is running 🚀"


if __name__ == "__main__":
    app.run(debug=True)