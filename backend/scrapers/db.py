import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

UPLOAD_CHUNK_SIZE = 500

_client = None


def get_client():
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def get_or_create_store(store_key, store):
    client = get_client()

    client.table("stores").upsert({
        "store_key": store_key,
        "address": store["address"],
        "fulfilment_store_id": store["fulfilmentStoreId"],
        "area_id": store.get("areaId"),
        "pickup_address_id": store.get("pickupAddressId"),
    }, on_conflict="store_key").execute()

    result = client.table("stores").select("id").eq("store_key", store_key).execute()
    return result.data[0]["id"]


def to_number(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def product_row(product, store_id, scraped_at):
    return {
        "scraped_at": scraped_at,
        "store_id": store_id,
        "product_id": str(product["product_id"]),
        "name": product["name"],
        "brand": product.get("brand"),
        "price": to_number(product.get("price")),
        "original_price": to_number(product.get("original_price")),
        "sale_price": to_number(product.get("sale_price")),
        "size": product.get("size"),
        "unit_price": product.get("unit_price"),
        "department": product.get("department"),
        "aisle": product.get("aisle"),
        "image_url": product.get("image_url"),
    }


def upload_products(store_key, store, products):
    client = get_client()
    store_id = get_or_create_store(store_key, store)

    scraped_at = datetime.now(timezone.utc).isoformat()
    rows = [
        product_row(p, store_id, scraped_at)
        for p in products
        if p.get("product_id")
    ]

    for start in range(0, len(rows), UPLOAD_CHUNK_SIZE):
        chunk = rows[start:start + UPLOAD_CHUNK_SIZE]
        client.table("products").upsert(
            chunk,
            on_conflict="store_id,product_id",
        ).execute()
        print(f"Uploaded {start + len(chunk)}/{len(rows)} products")

    print(f"Upload complete: {len(rows)} products for {store['address']}")
    return len(rows)
