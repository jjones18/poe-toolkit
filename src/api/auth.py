"""
POE API Authentication providers.
"""

from abc import ABC, abstractmethod


class AuthProvider(ABC):
    @abstractmethod
    def get_headers(self) -> dict:
        pass


class SessionAuthProvider(AuthProvider):
    """Authentication via POESESSID cookie."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id

    def get_headers(self) -> dict:
        return {
            "Cookie": f"POESESSID={self.session_id}",
            "User-Agent": "OAuth 2.0/POE Toolkit/1.0 (contact: github.com/jjones18)"
        }

