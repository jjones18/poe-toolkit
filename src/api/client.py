"""
POE Stash API client.
"""

import requests
import time
from .auth import AuthProvider
from utils.workers import bounded_http_request


class PoEClientError(RuntimeError):
    """Actionable, structured error from a Path of Exile API operation."""

    def __init__(self, operation: str, message: str, *, status_code=None):
        self.operation = operation
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(
            f"{operation} failed{suffix}: {message}. Check POESESSID/account, league, and network, then Retry."
        )


class PoEClient:
    """Client for interacting with the Path of Exile stash API."""
    
    BASE_URL = "https://www.pathofexile.com"
    DEFAULT_TIMEOUT = (5.0, 20.0)

    def __init__(self, auth_provider: AuthProvider, account_name: str, league: str, session=None, *, timeout=None):
        self.auth_provider = auth_provider
        self.account_name = account_name
        self.league = league
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def get_stash_tab_list(self, context=None, rate_limit_callback=None):
        """
        Fetches the list of stash tabs (metadata only).
        Returns the 'tabs' metadata list from tab 0.
        """
        data = self.get_stash_items(0, context=context, rate_limit_callback=rate_limit_callback)
        if 'tabs' not in data:
            raise PoEClientError("tab list fetch", "API response did not include stash tab metadata")
        return data['tabs']

    def get_stash_items(self, tab_index: int, context=None, rate_limit_callback=None, max_429_retries: int = 1):
        """
        Fetches items from a specific stash tab index.
        """
        url = f"{self.BASE_URL}/character-window/get-stash-items"
        params = {
            "accountName": self.account_name,
            "league": self.league,
            "tabIndex": tab_index,
            "tabs": 1 
        }
        
        headers = self.auth_provider.get_headers()
        response = None
        
        try:
            attempts = 0
            while True:
                if context is not None:
                    context.raise_if_cancelled()
                if context is not None:
                    response = bounded_http_request(
                        self.session,
                        "GET",
                        url,
                        token=context.token,
                        timeout=self.timeout,
                        params=params,
                        headers=headers,
                    )
                else:
                    response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)

                if response.status_code != 429 or attempts >= max_429_retries:
                    break
                attempts += 1
                try:
                    retry_after = max(0, int(response.headers.get("Retry-After", 60)))
                except (TypeError, ValueError):
                    retry_after = 60
                if rate_limit_callback is not None:
                    rate_limit_callback({
                        "phase": "rate_limit",
                        "tab_index": tab_index,
                        "retry_after": retry_after,
                        "attempt": attempts,
                    })
                print(f"Rate limited! Waiting {retry_after}s...")
                if context is not None:
                    context.sleep(retry_after)
                else:
                    time.sleep(retry_after)

            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise PoEClientError("stash tab fetch", "API response was not an object", status_code=response.status_code)
            return data
        except PoEClientError:
            raise
        except requests.exceptions.RequestException as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code is None and 'response' in locals():
                status_code = getattr(response, "status_code", None)
            raise PoEClientError("stash tab fetch", str(e), status_code=status_code) from e

    def get_first_stash_tab(self, context=None):
        return self.get_stash_items(0, context=context)

    def close(self):
        if getattr(self, "_owns_session", False):
            self.session.close()
