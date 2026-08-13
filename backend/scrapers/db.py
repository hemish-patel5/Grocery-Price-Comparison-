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


def newworld_store_name(store_key, store):
    address = store.get("address") or store.get("name")
    if address:
        return address
    return f"New World {store_key.replace('_', ' ').title()}"


def get_or_create_store(store_key, store):
    client = get_client()

    client.table("woolies_stores").upsert({
        "store_key": store_key,
        "address": store["address"],
        "fulfilment_store_id": store["fulfilmentStoreId"],
        "area_id": store.get("areaId"),
        "pickup_address_id": store.get("pickupAddressId"),
    }, on_conflict="store_key").execute()

    result = (
        client.table("woolies_stores")
        .select("id")
        .eq("store_key", store_key)
        .execute()
    )
    return result.data[0]["id"]


def get_or_create_newworld_store(store_key, store):
    """Upsert a New World store without touching the Woolworths store table."""
    client = get_client()
    retailer_store_id = store.get("storeId") or store.get("store_id") or store.get("id")
    if not retailer_store_id:
        raise ValueError(f"Missing New World store ID for {store_key}")

    client.table("newworld_stores").upsert({
        "store_key": store_key,
        "retailer_store_id": str(retailer_store_id),
        "address": newworld_store_name(store_key, store),
    }, on_conflict="store_key").execute()

    result = (
        client.table("newworld_stores")
        .select("id")
        .eq("store_key", store_key)
        .execute()
    )
    return result.data[0]["id"]


def to_number(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def catalog_row(product):
    """Store-independent product info, stored once per unique product."""
    return {
        "product_id": str(product["product_id"]),
        "name": product["name"],
        "brand": product.get("brand"),
        "size": product.get("size"),
        "department": product.get("department"),
        "aisle": product.get("aisle"),
        "image_url": product.get("image_url"),
    }


def price_row(product, store_id):
    """Per-store prices for one product."""
    return {
        "product_id": str(product["product_id"]),
        "store_id": store_id,
        "price": to_number(product.get("price")),
        "original_price": to_number(product.get("original_price")),
        "sale_price": to_number(product.get("sale_price")),
        "unit_price": product.get("unit_price"),
    }


def newworld_price_row(product, store_id):
    """Only the New World price data requested by the scraper contract."""
    return {
        "product_id": str(product["product_id"]),
        "store_id": store_id,
        "price": to_number(product.get("price")),
        "is_club_price": bool(product.get("is_club_price", False)),
    }


def upsert_chunked(client, table, rows, on_conflict, label):
    for start in range(0, len(rows), UPLOAD_CHUNK_SIZE):
        chunk = rows[start:start + UPLOAD_CHUNK_SIZE]
        client.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        print(f"Uploaded {start + len(chunk)}/{len(rows)} {label}")


def upload_products(store_key, store, products):
    """Upload Woolworths data to its existing three tables."""
    client = get_client()
    store_id = get_or_create_store(store_key, store)

    # keyed by product_id: upserting the same key twice in one statement
    # is a Postgres error
    unique = {
        str(p["product_id"]): p
        for p in products
        if p.get("product_id")
    }

    upsert_chunked(
        client, "woolies_products",
        [catalog_row(p) for p in unique.values()],
        on_conflict="product_id", label="products",
    )
    upsert_chunked(
        client, "woolies_store_prices",
        [price_row(p, store_id) for p in unique.values()],
        on_conflict="product_id,store_id", label="prices",
    )

    # scrape time lives on the store, stamped once the upload succeeded
    client.table("woolies_stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(f"Upload complete: {len(unique)} products for {store['address']}")
    return len(unique)


def upload_newworld_products(store_key, store, products):
    """Upload New World data to its own products, prices and stores tables."""
    client = get_client()
    store_id = get_or_create_newworld_store(store_key, store)
    unique = {
        str(product["product_id"]): product
        for product in products
        if product.get("product_id")
    }

    upsert_chunked(
        client,
        "newworld_products",
        [catalog_row(product) for product in unique.values()],
        on_conflict="product_id",
        label="New World products",
    )
    upsert_chunked(
        client,
        "newworld_store_prices",
        [newworld_price_row(product, store_id) for product in unique.values()],
        on_conflict="product_id,store_id",
        label="New World prices",
    )
    client.table("newworld_stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(
        f"Upload complete: {len(unique)} New World products for "
        f"{newworld_store_name(store_key, store)}"
    )
    return len(unique)
