import argparse
import json
import re
import time
from pathlib import Path

import httpx


BASE_URL = "https://www.woolworths.co.nz"
PICKUP_ADDRESSES_URL = f"{BASE_URL}/api/v1/addresses/pickup-addresses"
SET_PICKUP_ADDRESS_URL = f"{BASE_URL}/api/v1/fulfilment/my/pickup-addresses"
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("woolworths_stores.json")


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "woolworths_store"


def unique_key(base_key, existing):
    key = base_key
    count = 2

    while key in existing:
        key = f"{base_key}_{count}"
        count += 1

    return key


def get_cookie_value(client, name):
    for cookie in client.cookies.jar:
        if cookie.name == name:
            return cookie.value
    return None


def make_client():
    return httpx.Client(
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "referer": "https://www.woolworths.co.nz/",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
        },
        timeout=20.0,
    )


def get_pickup_addresses(client):
    response = client.get(PICKUP_ADDRESSES_URL)
    response.raise_for_status()

    stores = []
    seen_pickup_address_ids = set()

    for area in response.json().get("storeAreas", []):
        area_id = area.get("id")

        for store in area.get("storeAddresses", []):
            pickup_address_id = store.get("id")
            if pickup_address_id in seen_pickup_address_ids:
                continue

            seen_pickup_address_ids.add(pickup_address_id)
            stores.append({
                "address": store.get("name", "").strip(),
                "fullAddress": store.get("address"),
                "areaId": area_id,
                "pickupAddressId": pickup_address_id,
            })

    return stores


def enrich_store(client, store):
    response = client.put(
        SET_PICKUP_ADDRESS_URL,
        json={"addressId": store["pickupAddressId"]},
    )
    response.raise_for_status()

    location_cookie = get_cookie_value(client, "cw-lrkswrdjp")
    fulfilment = response.json().get("context", {}).get("fulfilment", {})

    store["address"] = fulfilment.get("address") or store["address"]
    store["areaId"] = fulfilment.get("areaId") or store["areaId"]
    store["fulfilmentStoreId"] = fulfilment.get("fulfilmentStoreId")
    store["pickupAddressId"] = fulfilment.get("pickupAddressId") or store["pickupAddressId"]
    store["locationCookie"] = location_cookie

    return store


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Woolworths NZ pickup stores and location cookies.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N pickup addresses. Useful for testing.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Output JSON file path.",
    )
    args = parser.parse_args()

    with make_client() as client:
        client.get(BASE_URL).raise_for_status()
        pickup_addresses = get_pickup_addresses(client)
        if args.limit is not None:
            pickup_addresses = pickup_addresses[:args.limit]

        stores = {}
        for index, store in enumerate(pickup_addresses, start=1):
            try:
                enriched_store = enrich_store(client, store)
            except httpx.HTTPError as error:
                print(f"Skipping {store['address']}: {error}")
                continue

            key = unique_key(slugify(enriched_store["address"]), stores)
            stores[key] = enriched_store
            print(f"{index}/{len(pickup_addresses)} {key}: {enriched_store['locationCookie']}")
            time.sleep(0.1)

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(stores, file, indent=2, ensure_ascii=False)

    print(f"Saved {len(stores)} stores to {args.output}")


if __name__ == "__main__":
    main()
