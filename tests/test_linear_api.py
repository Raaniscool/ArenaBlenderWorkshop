import base64
import json
import tempfile
import unittest
import urllib.parse
import urllib.error
from pathlib import Path

from arena_workshop.linear_api import (
    GRAPHQL_URL,
    OAUTH_SCOPES,
    TOKEN_URL,
    LinearApi,
    LinearApiError,
    LinearCredentialStore,
)
from arena_workshop.linear_cli import configure_credentials


class FakeResponse:
    def __init__(self, value, status=200):
        self.body = json.dumps(value).encode("utf-8")
        self.status = status

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class LinearApiTests(unittest.TestCase):
    def test_client_credentials_request_uses_fixed_least_scopes(self):
        requests = []

        def opener(request, timeout=30):
            requests.append(request)
            return FakeResponse({"access_token": "test-access-token", "expires_in": 100})

        api = LinearApi("public-client-id", "private-client-secret", opener=opener)
        api.authenticate()
        self.assertEqual(api._access_token, "test-access-token")
        request = requests[0]
        self.assertEqual(request.full_url, TOKEN_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        expected_auth = "Basic " + base64.b64encode(b"public-client-id:private-client-secret").decode("ascii")
        self.assertEqual(request.get_header("Authorization"), expected_auth)
        form = urllib.parse.parse_qs(request.data.decode("ascii"))
        self.assertEqual(form["grant_type"], ["client_credentials"])
        self.assertEqual(form["scope"], [",".join(OAUTH_SCOPES)])
        self.assertEqual(set(OAUTH_SCOPES), {"read", "issues:create", "comments:create"})

    def test_graphql_401_fetches_one_new_in_memory_token_and_retries(self):
        requests = []
        token_count = 0
        graphql_count = 0

        def opener(request, timeout=30):
            nonlocal token_count, graphql_count
            requests.append(request)
            if request.full_url == TOKEN_URL:
                token_count += 1
                return FakeResponse({"access_token": "token-{}".format(token_count)})
            graphql_count += 1
            if graphql_count == 1:
                raise urllib.error.HTTPError(GRAPHQL_URL, 401, "Unauthorized", {}, None)
            return FakeResponse({"data": {"viewer": {"id": "worker"}}})

        api = LinearApi("client", "secret", opener=opener)
        data = api.graphql("query { viewer { id } }")
        self.assertEqual(data["viewer"]["id"], "worker")
        self.assertEqual(token_count, 2)
        graph_requests = [request for request in requests if request.full_url == GRAPHQL_URL]
        self.assertEqual(graph_requests[0].get_header("Authorization"), "Bearer token-1")
        self.assertEqual(graph_requests[1].get_header("Authorization"), "Bearer token-2")
        self.assertEqual(api._access_token, "token-2")

    def test_authentication_failure_is_safe_and_does_not_leak_secret(self):
        secret = "do-not-print-this"

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(TOKEN_URL, 401, "Unauthorized", {}, None)

        api = LinearApi("client-id", secret, opener=opener)
        with self.assertRaises(LinearApiError) as raised:
            api.authenticate()
        self.assertEqual(raised.exception.code, "unauthorized")
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(api._access_token)

    def test_graphql_errors_are_not_reported_as_success(self):
        def opener(request, timeout=30):
            if request.full_url == TOKEN_URL:
                return FakeResponse({"access_token": "access"})
            return FakeResponse({"data": {}, "errors": [{"message": "private detail"}]})

        api = LinearApi("client", "secret", opener=opener)
        with self.assertRaises(LinearApiError) as raised:
            api.graphql("query { viewer { id } }")
        self.assertEqual(raised.exception.code, "graphql_error")
        self.assertNotIn("private detail", str(raised.exception))

    def test_network_outage_is_retryable(self):
        def opener(request, timeout=30):
            raise urllib.error.URLError("offline")

        api = LinearApi("client", "secret", opener=opener)
        with self.assertRaises(LinearApiError) as raised:
            api.authenticate()
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("secret", str(raised.exception))


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "linear_credentials.dpapi"

    def tearDown(self):
        self.temporary.cleanup()

    def test_credentials_are_saved_only_as_injected_protected_bytes(self):
        seen = []

        def protect(raw):
            seen.append(raw)
            return b"protected:" + raw[::-1]

        def unprotect(value):
            self.assertTrue(value.startswith(b"protected:"))
            return value[len(b"protected:"):][::-1]

        store = LinearCredentialStore(self.path, protect=protect, unprotect=unprotect)
        store.save("client-id", "secret-value")
        self.assertNotIn(b"secret-value", self.path.read_bytes())
        self.assertEqual(store.load(), {"client_id": "client-id", "client_secret": "secret-value"})
        self.assertEqual(len(seen), 1)

    def test_no_plaintext_fallback_when_dpapi_fails(self):
        store = LinearCredentialStore(self.path, protect=lambda value: (_ for _ in ()).throw(OSError("DPAPI unavailable")))
        with self.assertRaises(LinearApiError) as raised:
            store.save("client-id", "secret-value")
        self.assertEqual(raised.exception.code, "credential_protection_failed")
        self.assertFalse(self.path.exists())

    def test_setup_validates_then_saves_and_discards_access_token(self):
        saved = {}

        class Store:
            def save(self, client_id, client_secret):
                saved["client_id"] = client_id
                saved["client_secret"] = client_secret

        class Api:
            def __init__(self, client_id, client_secret):
                saved["api_credentials"] = (client_id, client_secret)
                self.forgot = False

            def authenticate_and_forget(self):
                self.forgot = True
                saved["forgot"] = True

        configure_credentials(" client-id ", "secret-value", store=Store(), api_factory=Api)
        self.assertEqual(saved["client_id"], "client-id")
        self.assertEqual(saved["client_secret"], "secret-value")
        self.assertTrue(saved["forgot"])


if __name__ == "__main__":
    unittest.main()
