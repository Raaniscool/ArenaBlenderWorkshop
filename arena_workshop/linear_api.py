"""Minimal outbound-only Linear OAuth client for the Windows worker."""

import base64
import json
import os
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .drive import _dpapi_protect, _dpapi_unprotect

TOKEN_URL = "https://api.linear.app/oauth/token"
GRAPHQL_URL = "https://api.linear.app/graphql"
OAUTH_SCOPES = ("read", "issues:create", "comments:create")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 30


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward OAuth credentials or job data to a redirect target."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _default_opener(request, timeout=HTTP_TIMEOUT_SECONDS):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


class LinearApiError(RuntimeError):
    """Safe error; messages never contain tokens, secrets, or response bodies."""

    def __init__(self, code, message, retryable=False, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status


def default_credential_path():
    """Return the user-local DPAPI credential location, outside the checkout."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArenaBlenderWorkshop" / "linear_credentials.dpapi"
    return Path.home() / "AppData" / "Local" / "ArenaBlenderWorkshop" / "linear_credentials.dpapi"


class LinearCredentialStore:
    """Atomically store Linear client credentials as a DPAPI CurrentUser blob."""

    def __init__(self, path=None, protect=None, unprotect=None):
        self.path = Path(path) if path is not None else default_credential_path()
        self._protect = protect or _dpapi_protect
        self._unprotect = unprotect or _dpapi_unprotect

    def save(self, client_id, client_secret):
        if (not isinstance(client_id, str) or not client_id.strip()
                or not isinstance(client_secret, str) or not client_secret):
            raise LinearApiError("invalid_credentials", "A Linear OAuth client ID and secret are required.")
        payload = json.dumps(
            {"client_id": client_id.strip(), "client_secret": client_secret},
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        try:
            protected = self._protect(payload)
        except Exception as exc:
            raise LinearApiError(
                "credential_protection_failed",
                "Windows DPAPI could not protect the Linear client secret; no plaintext fallback is supported.",
            ) from exc
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".linear-credential-", suffix=".tmp", dir=str(self.path.parent))
            if os.name != "nt":
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb") as stream:
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise LinearApiError("credential_store_failed", "The protected Linear credential store could not be written.") from exc
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def load(self):
        try:
            protected = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LinearApiError("credential_store_unreadable", "The protected Linear credential store could not be read.") from exc
        try:
            payload = self._unprotect(protected)
            value = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise LinearApiError("credential_store_invalid", "The Linear credential store could not be decrypted.") from exc
        if (not isinstance(value, dict) or not isinstance(value.get("client_id"), str)
                or not value["client_id"] or not isinstance(value.get("client_secret"), str)
                or not value["client_secret"]):
            raise LinearApiError("credential_store_invalid", "The protected Linear credential store has an invalid format.")
        return {"client_id": value["client_id"], "client_secret": value["client_secret"]}

    def delete(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise LinearApiError("credential_store_delete_failed", "The protected Linear credential store could not be removed.") from exc


def _read_json(opener, request, timeout=HTTP_TIMEOUT_SECONDS):
    try:
        response = opener(request, timeout=timeout)
        with response:
            status = getattr(response, "status", 200)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
        except Exception:
            raw = b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LinearApiError(
            "network_error", "A request to Linear failed ({}).".format(type(exc).__name__),
            retryable=True,
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LinearApiError("response_too_large", "Linear returned an unexpectedly large response.", status=status)
    if status == 401:
        raise LinearApiError("unauthorized", "Linear rejected the worker authorization.", status=status)
    if status == 429 or status >= 500:
        raise LinearApiError("linear_unavailable", "Linear returned a temporary service error.", retryable=True, status=status)
    if status >= 400:
        raise LinearApiError("linear_http_error", "Linear rejected the worker request.", status=status)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LinearApiError("invalid_linear_response", "Linear returned invalid JSON.", status=status) from exc
    if not isinstance(value, dict):
        raise LinearApiError("invalid_linear_response", "Linear returned an invalid response object.", status=status)
    return value


class LinearApi:
    """Linear OAuth client-credentials and GraphQL requests using stdlib HTTPS."""

    def __init__(self, client_id, client_secret, opener=_default_opener):
        self.client_id = client_id
        self._client_secret = client_secret
        self.opener = opener
        self._access_token = None

    def authenticate(self):
        if not isinstance(self.client_id, str) or not self.client_id.strip() or not self._client_secret:
            raise LinearApiError("invalid_credentials", "Linear OAuth client credentials are missing.")
        basic = base64.b64encode((self.client_id + ":" + self._client_secret).encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": ",".join(OAUTH_SCOPES),
        }).encode("ascii")
        request = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        response = _read_json(self.opener, request)
        token = response.get("access_token")
        if not isinstance(token, str) or not token:
            raise LinearApiError("token_response_invalid", "Linear did not return a valid access token.")
        self._access_token = token
        return True

    def graphql(self, query, variables=None):
        if self._access_token is None:
            self.authenticate()
        body = json.dumps({"query": query, "variables": variables or {}}, separators=(",", ":")).encode("utf-8")
        refreshed = False
        while True:
            request = urllib.request.Request(
                GRAPHQL_URL,
                data=body,
                headers={
                    "Authorization": "Bearer " + self._access_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                response = _read_json(self.opener, request)
            except LinearApiError as exc:
                if exc.code == "unauthorized" and not refreshed:
                    self._access_token = None
                    self.authenticate()
                    refreshed = True
                    continue
                raise
            errors = response.get("errors")
            if errors:
                raise LinearApiError("graphql_error", "Linear could not complete the requested operation.")
            data = response.get("data")
            if not isinstance(data, dict):
                raise LinearApiError("invalid_linear_response", "Linear returned an incomplete GraphQL response.")
            return data

    def authenticate_and_forget(self):
        """Validate saved credentials during setup, then discard the token."""
        self.authenticate()
        self._access_token = None

    def list_issues(self, state_name, team_key, label_name):
        query = """
        query ArenaBlenderJobs($teamKey: String!, $stateName: String!, $labelName: String!, $after: String) {
          issues(
            filter: {
              team: { key: { eq: $teamKey } }
              state: { name: { eq: $stateName } }
              labels: { some: { name: { eq: $labelName } } }
            }
            first: 50
            after: $after
          ) {
            nodes {
              id identifier title description
              team { key }
              state { name }
              labels { nodes { name } }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        all_issues = []
        after = None
        while True:
            data = self.graphql(query, {
                "teamKey": team_key,
                "stateName": state_name,
                "labelName": label_name,
                "after": after,
            })
            connection = data.get("issues")
            if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
                raise LinearApiError("invalid_linear_response", "Linear returned an invalid issue list.")
            all_issues.extend(connection["nodes"])
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            after = page.get("endCursor")
            if not isinstance(after, str) or not after:
                raise LinearApiError("invalid_linear_response", "Linear issue pagination returned no cursor.")
        return all_issues

    def get_workflow_states(self, team_key):
        data = self.graphql("""
        query ArenaBlenderWorkflowStates($teamKey: String!) {
          workflowStates(filter: { team: { key: { eq: $teamKey } } }) {
            nodes { id name }
          }
        }
        """, {"teamKey": team_key})
        connection = data.get("workflowStates")
        nodes = connection.get("nodes") if isinstance(connection, dict) else None
        if not isinstance(nodes, list):
            raise LinearApiError("invalid_linear_response", "Linear returned invalid workflow states.")
        states = {}
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("id"), str) and isinstance(node.get("name"), str):
                states[node["name"]] = node["id"]
        return states

    def get_issue(self, issue_id):
        data = self.graphql("""
        query ArenaBlenderIssue($issueId: String!) {
          issue(id: $issueId) {
            id identifier title description
            team { key }
            state { name }
            labels { nodes { name } }
          }
        }
        """, {"issueId": issue_id})
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise LinearApiError("issue_not_found", "The Linear job issue could not be read.")
        return issue

    def list_comments(self, issue_id):
        query = """
        query ArenaBlenderComments($issueId: String!, $after: String) {
          issue(id: $issueId) {
            comments(first: 50, after: $after) {
              nodes { id body }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        comments = []
        after = None
        while True:
            data = self.graphql(query, {"issueId": issue_id, "after": after})
            issue = data.get("issue")
            connection = issue.get("comments") if isinstance(issue, dict) else None
            if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
                raise LinearApiError("invalid_linear_response", "Linear returned invalid issue comments.")
            comments.extend(connection["nodes"])
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            after = page.get("endCursor")
            if not isinstance(after, str) or not after:
                raise LinearApiError("invalid_linear_response", "Linear comment pagination returned no cursor.")
        return comments

    def update_issue_state(self, issue_id, state_id):
        data = self.graphql("""
        mutation ArenaBlenderUpdateIssueState($issueId: String!, $stateId: String!) {
          issueUpdate(id: $issueId, input: { stateId: $stateId }) {
            success issue { id identifier state { name } }
          }
        }
        """, {"issueId": issue_id, "stateId": state_id})
        result = data.get("issueUpdate")
        if not isinstance(result, dict) or result.get("success") is not True:
            raise LinearApiError("issue_update_failed", "Linear did not confirm the issue state update.")
        return result.get("issue")

    def create_comment(self, issue_id, body):
        data = self.graphql("""
        mutation ArenaBlenderCreateComment($issueId: String!, $body: String!) {
          commentCreate(input: { issueId: $issueId, body: $body }) {
            success comment { id body }
          }
        }
        """, {"issueId": issue_id, "body": body})
        result = data.get("commentCreate")
        if not isinstance(result, dict) or result.get("success") is not True:
            raise LinearApiError("comment_create_failed", "Linear did not confirm the result comment.")
        return result.get("comment")
