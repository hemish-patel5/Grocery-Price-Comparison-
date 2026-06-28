from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

WOOLWORTHS_STORE_ID = 9023

def search_woolworths(query):
    try:
        with httpx.Client(
            headers={
                "accept": "application/json",
                "user-agent": "Mozilla/5.0",
                "x-requested-with": "OnlineShopping.WebApp",
                "referer": "https://www.woolworths.co.nz/shop/searchproducts"
            },
            timeout=10.0
        ) as client:
            client.get("https://www.woolworths.co.nz")
            client.cookies.set("fulfilmentStoreId", str(WOOLWORTHS_STORE_ID), domain=".woolworths.co.nz")
            res = client.get("https://www.woolworths.co.nz/api/v1/products", params={
                "target": "search", "search": query, "size": 24
            })
            products = res.json().get("products", {}).get("items", [])

            def get_price(p):
                price = p.get("price", {})
                return price.get("salePrice") or price.get("originalPrice")

            return [
                {"name": p["name"], "price": f"{get_price(p):.2f}", "store": "Woolworths"}
                for p in products if get_price(p) is not None
            ]
    except Exception as e:
        print(f"Woolworths error: {e}")
        return []


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    with ThreadPoolExecutor() as executor:
        woolworths_future = executor.submit(search_woolworths, query)
        results = (
            woolworths_future.result()
        )

    results.sort(key=lambda x: float(x["price"]))
    return jsonify(results)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
