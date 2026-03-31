# pip install flask flask-cors httpx

from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app)

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"

def init_session(store_id: int):
    client = httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
            "referer": "https://www.woolworths.co.nz/shop/searchproducts"
        }
    )
    client.get(BASE_URL)
    client.cookies.set("fulfilmentStoreId", str(store_id), domain=".woolworths.co.nz")
    return client

def search_products(client: httpx.Client, query: str):
    params = {
        "target": "search",
        "search": query,
        "size": 48
    }
    response = client.get(API_URL, params=params)
    data = response.json()
    products = data.get("products", {}).get("items", [])

    def get_price(p):
        price_data = p.get("price", {})
        return price_data.get("salePrice") or price_data.get("originalPrice")

    valid_products = [p for p in products if get_price(p) is not None]
    valid_products.sort(key=get_price)
    return valid_products

@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    store_id = int(request.args.get("store", 9023))

    client = init_session(store_id)
    products = search_products(client, query)

    def get_price(p):
        price_data = p.get("price", {})
        return price_data.get("salePrice") or price_data.get("originalPrice")

    return jsonify([{
        "name": p["name"],
        "price": get_price(p)
    } for p in products])

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0")
