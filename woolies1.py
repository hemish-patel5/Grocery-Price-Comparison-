# pip install flask flask-cors httpx

from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app)

STORE_ID = 9023

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"

def search_products(query, store_id):
    with httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
            "referer": "https://www.woolworths.co.nz/shop/searchproducts"
        },
        timeout=10.0
    ) as client:

        client.get(BASE_URL)

        client.cookies.set(
            "fulfilmentStoreId",
            str(store_id),
            domain=".woolworths.co.nz"
        )
        params = {
            "target": "search",
            "search": query,
            "size": 24
        }

        res = client.get(API_URL, params=params)
        data = res.json()

        products = data.get("products", {}).get("items", [])

        def get_price(p):
            price = p.get("price", {})
            return price.get("salePrice") or price.get("originalPrice")

        valid = [p for p in products if get_price(p) is not None]
        valid.sort(key=get_price)

        return [
            {
                "name": p["name"], 
                "price": f"{get_price(p):.2f}", 
                "store": "Woolworths"
            }
            for p in valid
        ]

@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    products = search_products(query, STORE_ID)
    return jsonify(products)

if __name__ == "__main__":
    app.run(debug=True)