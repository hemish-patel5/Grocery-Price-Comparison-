import unittest
from unittest.mock import patch

from backend.api import app


class QueryResult:
    def __init__(self, data):
        self.data = data


class TableQuery:
    def __init__(self, data):
        self.data = data

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return QueryResult(self.data)


class FakeSupabase:
    def __init__(self, rpc_rows=None, tables=None, rpc_error=None):
        self.rpc_rows = rpc_rows or []
        self.tables = tables or {}
        self.rpc_error = rpc_error
        self.rpc_name = None
        self.rpc_args = None

    def rpc(self, name, args):
        self.rpc_name = name
        self.rpc_args = args
        return self

    def execute(self):
        if self.rpc_error:
            raise self.rpc_error
        return QueryResult(self.rpc_rows)

    def table(self, name):
        return TableQuery(self.tables.get(name, []))


class SearchApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_empty_unfiltered_search_does_not_call_supabase(self):
        with patch("backend.api.get_client") as get_client:
            response = self.client.get("/api/search?q=")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        get_client.assert_not_called()

    def test_search_uses_unified_rpc_and_normalizes_retailer_id(self):
        database = FakeSupabase(rpc_rows=[{
            "retailer": "New World",
            "product_id": "5010717-EA-000",
            "name": "Originals Ready Salted Potato Chips",
            "brand": "Bluebird",
            "size": "150g",
            "price": 2.2,
            "original_price": None,
            "sale_price": None,
            "is_club_price": True,
            "is_on_special": False,
            "store_key": "albany",
            "store_address": "New World Albany",
            "total_count": 12,
        }])

        with patch("backend.api.get_client", return_value=database):
            response = self.client.get(
                "/api/search",
                query_string={
                    "q": "Bluebird bluebird chips!!!",
                    "category": "pantry",
                    "sort": "price_asc",
                    "location": "new_world:albany",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.rpc_name, "search_grocery_products")
        self.assertEqual(database.rpc_args, {
            "p_query": "bluebird chips",
            "p_category": "pantry",
            "p_retailer": "New World",
            "p_store_key": "albany",
            "p_sort": "price_asc",
            "p_limit": 100,
            "p_offset": 0,
        })
        row = response.get_json()[0]
        self.assertEqual(row["product_id"], "new_world:5010717-EA-000")
        self.assertEqual(row["store"], "New World")
        self.assertTrue(row["is_club_price"])
        self.assertEqual(response.headers["X-Total-Count"], "12")

    def test_category_only_search_is_supported(self):
        database = FakeSupabase()
        with patch("backend.api.get_client", return_value=database):
            response = self.client.get(
                "/api/search",
                query_string={"category": "meat_seafood"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.rpc_args["p_query"], "")
        self.assertEqual(database.rpc_args["p_category"], "meat_seafood")

    def test_relevance_search_interleaves_retailers(self):
        database = FakeSupabase(rpc_rows=[
            {
                "retailer": retailer,
                "product_id": product_id,
                "name": product_id,
                "price": 1,
            }
            for retailer, product_id in (
                ("Woolworths", "w1"),
                ("Woolworths", "w2"),
                ("Woolworths", "w3"),
                ("New World", "n1"),
                ("New World", "n2"),
                ("PAK'nSAVE", "p1"),
            )
        ])

        with patch("backend.api.get_client", return_value=database):
            response = self.client.get("/api/search?q=milk")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["store"] for row in response.get_json()],
            [
                "Woolworths",
                "New World",
                "PAK'nSAVE",
                "Woolworths",
                "New World",
                "Woolworths",
            ],
        )

    def test_price_search_keeps_database_order(self):
        database = FakeSupabase(rpc_rows=[
            {
                "retailer": retailer,
                "product_id": product_id,
                "name": product_id,
                "price": price,
            }
            for retailer, product_id, price in (
                ("Woolworths", "w1", 1),
                ("Woolworths", "w2", 2),
                ("New World", "n1", 3),
            )
        ])

        with patch("backend.api.get_client", return_value=database):
            response = self.client.get(
                "/api/search",
                query_string={"q": "milk", "sort": "price_asc"},
            )

        self.assertEqual(
            [row["store"] for row in response.get_json()],
            ["Woolworths", "Woolworths", "New World"],
        )

    def test_invalid_filters_are_rejected(self):
        cases = (
            ({"category": "not-real"}, "Unknown category"),
            ({"sort": "cheapest-ish"}, "Unknown sort order"),
            ({"location": "unknown:albany"}, "Unknown location"),
            ({"q": "x" * 101}, "100 characters or fewer"),
        )
        for parameters, expected_message in cases:
            with self.subTest(parameters=parameters):
                response = self.client.get("/api/search", query_string=parameters)
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected_message, response.get_json()["error"])

    def test_rpc_failure_returns_service_unavailable(self):
        database = FakeSupabase(rpc_error=RuntimeError("database unavailable"))
        with (
            patch("backend.api.get_client", return_value=database),
            self.assertLogs(app.logger, level="ERROR"),
        ):
            response = self.client.get("/api/search?q=milk")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"error": "Search is temporarily unavailable"},
        )

    def test_search_options_only_include_uploaded_stores(self):
        database = FakeSupabase(tables={
            "woolies_stores": [{
                "store_key": "quay_street",
                "address": "Woolworths Auckland Quay Street",
            }],
            "newworld_stores": [{
                "store_key": "albany",
                "address": "New World Albany",
            }],
            "paknsave_stores": [{
                "store_key": "manukau",
                "address": "PAK'nSAVE Manukau",
            }],
        })
        with patch("backend.api.get_client", return_value=database):
            response = self.client.get("/api/search/options")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["locations"]), 3)
        self.assertIn(
            "paknsave:manukau",
            {location["value"] for location in data["locations"]},
        )
        self.assertIn(
            "meat_seafood",
            {category["value"] for category in data["categories"]},
        )


if __name__ == "__main__":
    unittest.main()
