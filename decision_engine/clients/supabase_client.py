"""Small PostgREST transport. Never includes response bodies or credentials in errors."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SupabaseClient:
    def __init__(self, settings, timeout=30):
        parsed = urlparse(settings.supabase_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Supabase URL must be an HTTPS origin")
        self.url = settings.supabase_url + "/rest/v1/"
        self.key = settings.service_role_key
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, payload=None, params=None):
        url = self.url + path + ("?" + urlencode(params) if params else "")
        data = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = Request(url, data=data, method=method, headers={
            "apikey": self.key, "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json", "Prefer": "return=representation"})
        # Only reads are automatically retried. RPC transactions can have ambiguous outcomes.
        for attempt in range(3 if method == "GET" else 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = response.read()
                    return json.loads(body) if body else None
            except HTTPError as error:
                if method == "GET" and error.code in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(0.25 * 2 ** attempt)
                    continue
                raise RuntimeError(f"Supabase {method} failed with HTTP {error.code}") from None
            except (URLError, TimeoutError):
                if method == "GET" and attempt < 2:
                    time.sleep(0.25 * 2 ** attempt)
                    continue
                raise RuntimeError("Supabase connection failed") from None

    def rows(self, table, filters=None):
        result, offset = [], 0
        while True:
            page = self.request("GET", table, params={"select": "*", "order": "id.asc", **(filters or {}), "limit": 500, "offset": offset})
            if not isinstance(page, list):
                raise ValueError("Unexpected database response")
            result.extend(page)
            if not page:
                return result
            offset += len(page)

    def rpc(self, name, payload):
        return self.request("POST", "rpc/" + name, payload)
