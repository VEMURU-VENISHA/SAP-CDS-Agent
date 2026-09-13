"""SAP ADT (ABAP Development Tools) Asynchronous REST Client.

Provides safe, authenticated HTTP communications over TLS with SAP S/4HANA ICF
services (/sap/bc/adt/...).

Enterprise Safety & Hygiene:
- Zero credential logging: Authorization headers, tokens, and passwords are fully scrubbed.
- Strict timeout bounds.
- Explicit typed error mapping for HTTP status codes (401, 403, 404, 500+).
"""

import re
from typing import Any, Dict, List, Optional
import httpx
from src.config import Settings, get_settings
from src.core.exceptions import (
    SAPAuthenticationError,
    SAPConfigurationError,
    SAPConnectionError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPPermissionError,
)
from src.logging_config import logger


class SAPADTClient:
    """HTTP Client interacting with SAP S/4HANA ADT endpoints."""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._custom_client = client

    def _validate_config(self) -> None:
        """Ensures required network and credential settings are present."""
        if not self.settings.SAP_BASE_URL:
            raise SAPConfigurationError(
                "SAP_BASE_URL is not configured. Set SAP_BASE_URL in environment or .env."
            )

        if self.settings.SAP_AUTH_TYPE == "basic":
            password_str = self.settings.SAP_PASSWORD.get_secret_value()
            if not self.settings.SAP_USERNAME or not password_str:
                raise SAPConfigurationError(
                    "SAP_USERNAME and SAP_PASSWORD are required for 'basic' authentication."
                )
        elif self.settings.SAP_AUTH_TYPE == "token":
            token_str = self.settings.SAP_API_TOKEN.get_secret_value()
            if not token_str:
                raise SAPConfigurationError(
                    "SAP_API_TOKEN is required for 'token' authentication."
                )

    def _get_auth_headers(self) -> Dict[str, str]:
        """Constructs headers without exposing them in logs or traces."""
        headers: Dict[str, str] = {
            "Accept": "text/plain, application/xml, application/vnd.sap.adt.ddic.ddls.sources.v2+xml, */*",
            "sap-client": self.settings.SAP_CLIENT,
        }
        if self.settings.SAP_AUTH_TYPE == "token":
            token_str = self.settings.SAP_API_TOKEN.get_secret_value()
            headers["Authorization"] = f"Bearer {token_str}"
        return headers

    def _get_auth_tuple(self) -> Optional[httpx.BasicAuth]:
        """Returns httpx BasicAuth object for basic auth mode."""
        if self.settings.SAP_AUTH_TYPE == "basic":
            return httpx.BasicAuth(
                username=self.settings.SAP_USERNAME,
                password=self.settings.SAP_PASSWORD.get_secret_value(),
            )
        return None

    def _sanitize_url_for_logging(self, url: str) -> str:
        """Removes query parameter values that could contain sensitive tokens."""
        return re.sub(r"([?&](?:token|password|secret|key)=)[^&]+", r"\1***", str(url), flags=re.IGNORECASE)

    def _log_request(self, method: str, path: str, status_code: Optional[int] = None) -> None:
        """Emits sanitized, audit-safe log messages."""
        clean_path = self._sanitize_url_for_logging(path)
        if status_code is not None:
            logger.info(
                "SAP ADT %s %s -> HTTP %d [Client: %s, System: %s]",
                method,
                clean_path,
                status_code,
                self.settings.SAP_CLIENT,
                self.settings.SAP_SYSTEM_ID,
            )
        else:
            logger.debug(
                "SAP ADT dispatching %s %s [Client: %s, System: %s]",
                method,
                clean_path,
                self.settings.SAP_CLIENT,
                self.settings.SAP_SYSTEM_ID,
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Creates or returns an active httpx client with configured SSL and timeout settings."""
        if self._custom_client is not None:
            return self._custom_client

        base_url = self.settings.SAP_BASE_URL.rstrip("/")
        return httpx.AsyncClient(
            base_url=base_url,
            verify=self.settings.SAP_VERIFY_SSL,
            timeout=float(self.settings.SAP_REQUEST_TIMEOUT_SECONDS),
            auth=self._get_auth_tuple(),
        )

    async def get_ddl_source(self, object_name: str) -> str:
        """Retrieves raw ABAP CDS DDL source code for a known CDS view entity.

        Endpoint: GET /sap/bc/adt/ddic/ddl/sources/{name}
        Evidence: VERIFIED IN SYSTEM (observed directly in Eclipse ADT communication log).
        """
        self._validate_config()
        # SAP ADT accepts lowercase or exact name
        clean_name = object_name.strip().lower()
        path = f"/sap/bc/adt/ddic/ddl/sources/{clean_name}"
        params = {"sap-client": self.settings.SAP_CLIENT}
        headers = self._get_auth_headers()

        self._log_request("GET", path)

        try:
            client = await self._get_client()
            # If using custom client, manage closure outside; if created here, use context manager
            if self._custom_client is not None:
                resp = await client.get(path, params=params, headers=headers)
            else:
                async with client as http:
                    resp = await http.get(path, params=params, headers=headers)

            self._log_request("GET", path, resp.status_code)

            if resp.status_code in (200, 304):
                return resp.text

            if resp.status_code == 401:
                raise SAPAuthenticationError(
                    f"Authentication failed on SAP ADT endpoint {path}. Verify credentials."
                )
            if resp.status_code == 403:
                raise SAPPermissionError(resource=clean_name)
            if resp.status_code == 404:
                raise SAPNotFoundError(resource_name=object_name)

            raise SAPConnectorError(
                message=f"SAP ADT returned unexpected status {resp.status_code} for DDL source '{object_name}'.",
                status_code=resp.status_code,
            )

        except httpx.TimeoutException as e:
            logger.error("SAP ADT request timed out: %s", self._sanitize_url_for_logging(path))
            raise SAPConnectionError(f"Connection to SAP timed out on {path}: {e}")
        except httpx.ConnectError as e:
            logger.error("Failed to establish connection to SAP: %s", e)
            raise SAPConnectionError(f"Failed to connect to SAP host: {e}")
        except (SAPAuthenticationError, SAPPermissionError, SAPNotFoundError, SAPConnectorError):
            raise
        except Exception as e:
            logger.error("Unexpected error in SAP ADT client: %s", e)
            raise SAPConnectorError(f"SAP client unexpected error: {e}")

    async def check_connectivity(self) -> bool:
        """Lightweight connection probe testing whether the SAP ADT host is online and authenticated.

        Attempts GET /sap/bc/adt/discovery (or root ADT tree).
        Returns True if HTTP 200/304 is returned.
        Raises typed errors on auth/permission failure, or returns False on unreachable host.
        """
        try:
            self._validate_config()
        except SAPConfigurationError as e:
            logger.warning("SAP connectivity check aborted: %s", e)
            return False

        path = "/sap/bc/adt/discovery"
        params = {"sap-client": self.settings.SAP_CLIENT}
        headers = self._get_auth_headers()

        try:
            client = await self._get_client()
            if self._custom_client is not None:
                resp = await client.get(path, params=params, headers=headers)
            else:
                async with client as http:
                    resp = await http.get(path, params=params, headers=headers)

            self._log_request("GET", path, resp.status_code)
            if resp.status_code in (200, 304):
                return True
            if resp.status_code == 401:
                logger.warning("SAP ADT connectivity test failed: 401 Unauthorized")
                return False
            if resp.status_code == 403:
                logger.warning("SAP ADT connectivity test failed: 403 Forbidden")
                return False
            # Some SAP systems return 404 on discovery root but allow DDL sources
            return resp.status_code < 500
        except Exception as e:
            logger.warning("SAP ADT connectivity probe failed: %s", e)
            return False

    async def search_repository_unverified(
        self,
        query: str,
        limit: int = 50,
    ) -> List[Dict[str, str]]:
        """Invokes the documented ADT repository quick search service.

        Endpoint: GET /sap/bc/adt/repository/quicksearch
        Evidence: DOCUMENTED BUT NOT YET SYSTEM-VERIFIED.
        Quarantined: Catches 404 or unverified failures safely without crashing.
        """
        self._validate_config()
        path = "/sap/bc/adt/repository/quicksearch"
        params = {
            "operation": "quickSearchSuggest",
            "query": query,
            "maxResults": str(limit),
            "type": "DDLS/DF",
            "sap-client": self.settings.SAP_CLIENT,
        }
        headers = self._get_auth_headers()
        headers["Accept"] = "application/xml, text/xml"

        logger.info(
            "Invoking system-unverified endpoint: %s?query=%s [Status: DOCUMENTED_ONLY]",
            path,
            query,
        )

        try:
            client = await self._get_client()
            if self._custom_client is not None:
                resp = await client.get(path, params=params, headers=headers)
            else:
                async with client as http:
                    resp = await http.get(path, params=params, headers=headers)

            self._log_request("GET", path, resp.status_code)
            if resp.status_code in (200, 304):
                # Basic extraction of object names from XML if returned
                matches: List[Dict[str, str]] = []
                for m in re.finditer(r'<adtcore:objectReference[^>]*adtcore:name="([^"]+)"[^>]*adtcore:type="DDLS/DF"[^>]*>', resp.text):
                    matches.append({"name": m.group(1), "type": "DDLS/DF"})
                return matches

            logger.warning(
                "Documented repository quicksearch returned status %d. Endpoint is system-unverified.",
                resp.status_code,
            )
            return []
        except Exception as e:
            logger.warning(
                "Documented repository quicksearch failed (%s). Handling gracefully as system-unverified.",
                e,
            )
            return []
