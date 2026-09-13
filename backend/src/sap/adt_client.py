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
from src.models.domain import SAPCheckMessage, SAPCheckrunResult, SAPValidationStatus


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

    @staticmethod
    def _parse_search_xml(xml_text: str) -> List[Dict[str, str]]:
        """Parses SAP ADT object references XML response returned by information system search."""
        import xml.etree.ElementTree as ET

        results: List[Dict[str, str]] = []
        if not xml_text or not xml_text.strip():
            return results

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("Failed to parse SAP ADT search XML: %s", e)
            return results

        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "objectReference":
                attrs = elem.attrib
                name = None
                obj_type = None
                description = ""
                package_name = ""
                uri = ""

                for k, v in attrs.items():
                    clean_k = k.split("}")[-1] if "}" in k else k
                    if clean_k == "name":
                        name = v
                    elif clean_k == "type":
                        obj_type = v
                    elif clean_k == "description":
                        description = v
                    elif clean_k in ("packageName", "package"):
                        package_name = v
                    elif clean_k == "uri":
                        uri = v

                if name:
                    results.append({
                        "name": name,
                        "type": obj_type or "DDLS/DF",
                        "description": description,
                        "package": package_name,
                        "uri": uri,
                    })
        return results

    async def search_information_system(
        self,
        query: str,
        max_results: int = 51,
    ) -> List[Dict[str, str]]:
        """Invokes the verified SAP ADT repository information-system search service.

        Endpoint: GET /sap/bc/adt/repository/informationsystem/search
        Evidence: VERIFIED IN OUR SYSTEM (Observed directly in Eclipse ABAP Communication Log).
        Observed parameters: operation=quickSearch, query=..., maxResults=...
        """
        self._validate_config()

        effective_max = max(1, min(max_results, 200))
        clean_query = query.strip()
        formatted_query = clean_query if clean_query.endswith("*") else f"{clean_query}*"

        path = "/sap/bc/adt/repository/informationsystem/search"
        params = {
            "operation": "quickSearch",
            "query": formatted_query,
            "maxResults": str(effective_max),
        }
        headers = self._get_auth_headers()
        headers["Accept"] = (
            "application/xml, text/xml, application/vnd.sap.adt.repository.informationsystem.search.v1+xml, */*"
        )

        self._log_request("GET", path)

        try:
            client = await self._get_client()
            if self._custom_client is not None:
                resp = await client.get(path, params=params, headers=headers)
            else:
                async with client as http:
                    resp = await http.get(path, params=params, headers=headers)

            self._log_request("GET", path, resp.status_code)

            if resp.status_code in (200, 304):
                return self._parse_search_xml(resp.text)

            if resp.status_code == 401:
                raise SAPAuthenticationError("Authentication failed during SAP repository search.")
            if resp.status_code == 403:
                raise SAPPermissionError(resource=path)
            if resp.status_code == 404:
                logger.warning("SAP repository search endpoint returned 404.")
                return []

            raise SAPConnectorError(
                message=f"SAP repository search returned unexpected HTTP status {resp.status_code}.",
                status_code=resp.status_code,
            )

        except httpx.TimeoutException as e:
            logger.error("SAP repository search timed out: %s", self._sanitize_url_for_logging(path))
            raise SAPConnectionError(f"SAP search timed out on {path}: {e}")
        except httpx.ConnectError as e:
            logger.error("Failed to connect to SAP during search: %s", e)
            raise SAPConnectionError(f"Failed to connect to SAP host: {e}")
        except (SAPAuthenticationError, SAPPermissionError, SAPConnectorError):
            raise
        except Exception as e:
            logger.error("Unexpected error in SAP repository search: %s", e)
            raise SAPConnectorError(f"SAP search unexpected error: {e}")

    @staticmethod
    def _build_checkrun_xml(repository_uri: str, version: str = "active") -> str:
        """Constructs the verified XML checkObjectList payload for SAP ADT checkruns.

        Verified schema from Eclipse ABAP Communication Log:
        <chkrun:checkObjectList
            xmlns:chkrun="http://www.sap.com/adt/checkrun"
            xmlns:adtcore="http://www.sap.com/adt/core">
            <chkrun:checkObject
                adtcore:uri="..."
                chkrun:version="active"/>
        </chkrun:checkObjectList>
        """
        clean_uri = repository_uri.strip()
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkObjectList
    xmlns:chkrun="http://www.sap.com/adt/checkrun"
    xmlns:adtcore="http://www.sap.com/adt/core">
    <chkrun:checkObject
        adtcore:uri="{clean_uri}"
        chkrun:version="{version}"/>
</chkrun:checkObjectList>"""

    @staticmethod
    def _parse_checkrun_xml(
        xml_text: str,
        http_status: int = 200,
        content_type: str = "application/vnd.sap.adt.checkmessages+xml",
    ) -> SAPCheckrunResult:
        """Parses the verified SAP ADT checkrun XML response.

        Extracts:
        - check report status, reporter, triggering URI
        - check messages: severity/type, short text, msgid, msgno, variables (msgv1..msgv4)
        - source position (line, column/offset) extracted from #start=line,offset in uri or attributes
        """
        import xml.etree.ElementTree as ET

        if not xml_text or not xml_text.strip():
            return SAPCheckrunResult(
                status=SAPValidationStatus.PASS,
                reporter="abapCheckRun",
                http_status=http_status,
                content_type=content_type,
                messages=[],
            )

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("Failed to parse SAP ADT checkrun XML: %s", e)
            return SAPCheckrunResult(
                status=SAPValidationStatus.ERROR,
                reporter="abapCheckRun",
                http_status=http_status,
                content_type=content_type,
                reason=f"Malformed XML in SAP ADT checkrun response: {e}",
                messages=[],
            )

        def _strip_ns(tag: str) -> str:
            return tag.split("}")[-1] if "}" in tag else tag

        reporter = "abapCheckRun"
        triggering_uri = None
        messages: List[SAPCheckMessage] = []

        for elem in root.iter():
            tag = _strip_ns(elem.tag)
            clean_attrs = {_strip_ns(k): v for k, v in elem.attrib.items()}

            if tag in ("checkReport", "report"):
                if "reporter" in clean_attrs:
                    reporter = clean_attrs["reporter"]
                if "triggeringuri" in clean_attrs:
                    triggering_uri = clean_attrs["triggeringuri"]
                elif "triggeringUri" in clean_attrs:
                    triggering_uri = clean_attrs["triggeringUri"]

            elif tag in ("checkMessage", "message"):
                raw_uri = clean_attrs.get("uri")
                severity = (clean_attrs.get("type") or clean_attrs.get("severity") or "I").upper()
                short_text = clean_attrs.get("shortText") or clean_attrs.get("text") or ""
                msgid = clean_attrs.get("msgid")
                msgno = clean_attrs.get("msgno")

                # Extract message variables
                variables = []
                for v_key in ("msgv1", "msgv2", "msgv3", "msgv4"):
                    val = clean_attrs.get(v_key)
                    if val:
                        variables.append(val)

                # Extract line and column/offset from fragment, e.g. #start=10,5 or #start=10
                line = None
                col = None
                if raw_uri:
                    match = re.search(r"#start=(\d+)(?:,(\d+))?", raw_uri)
                    if match:
                        line = int(match.group(1))
                        if match.group(2):
                            col = int(match.group(2))

                if line is None and "line" in clean_attrs:
                    try:
                        line = int(clean_attrs["line"])
                    except (ValueError, TypeError):
                        pass

                if col is None and "offset" in clean_attrs:
                    try:
                        col = int(clean_attrs["offset"])
                    except (ValueError, TypeError):
                        pass

                messages.append(
                    SAPCheckMessage(
                        uri=raw_uri,
                        severity=severity,
                        short_text=short_text,
                        msgid=msgid,
                        msgno=msgno,
                        variables=variables,
                        line=line,
                        column=col,
                    )
                )

        has_error = any(m.severity in ("E", "A") for m in messages)
        has_warning = any(m.severity == "W" for m in messages)

        if has_error:
            overall_status = SAPValidationStatus.ERROR
        elif has_warning:
            overall_status = SAPValidationStatus.WARNING
        else:
            overall_status = SAPValidationStatus.PASS

        return SAPCheckrunResult(
            status=overall_status,
            reporter=reporter,
            triggering_uri=triggering_uri,
            messages=messages,
            http_status=http_status,
            content_type=content_type,
        )

    async def run_checkrun(
        self,
        repository_uri: str,
        version: str = "active",
    ) -> SAPCheckrunResult:
        """Executes a real read-only SAP ADT checkrun against a repository object URI.

        Endpoint: POST /sap/bc/adt/checkruns?reporters=abapCheckRun
        Verified Request Content-Type: application/vnd.sap.adt.checkobjects+xml
        Verified Response Content-Type: application/vnd.sap.adt.checkmessages+xml

        Conservative status mapping:
        - E / A: ERROR
        - W: WARNING
        - clean: PASS
        - unreachable / auth fail / unconfigured: UNAVAILABLE
        - invalid/missing URI: INSUFFICIENT_EVIDENCE
        """
        if not repository_uri or not repository_uri.strip():
            return SAPCheckrunResult(
                status=SAPValidationStatus.INSUFFICIENT_EVIDENCE,
                reason="No valid repository URI provided for SAP checkrun.",
            )

        try:
            self._validate_config()
        except SAPConfigurationError as e:
            logger.warning("SAP ADT checkrun aborted due to configuration error: %s", e)
            return SAPCheckrunResult(
                status=SAPValidationStatus.UNAVAILABLE,
                reason=f"SAP configuration error: {e}",
            )

        path = "/sap/bc/adt/checkruns"
        params = {"reporters": "abapCheckRun"}
        body = self._build_checkrun_xml(repository_uri, version=version)
        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/vnd.sap.adt.checkobjects+xml"
        headers["Accept"] = "application/vnd.sap.adt.checkmessages+xml"

        self._log_request("POST", path)

        try:
            client = await self._get_client()
            if self._custom_client is not None:
                resp = await client.post(path, params=params, headers=headers, content=body)
            else:
                async with client as http:
                    resp = await http.post(path, params=params, headers=headers, content=body)

            self._log_request("POST", path, resp.status_code)

            if resp.status_code in (200, 201):
                return self._parse_checkrun_xml(
                    resp.text,
                    http_status=resp.status_code,
                    content_type=resp.headers.get("Content-Type", ""),
                )

            if resp.status_code == 401:
                logger.warning("SAP ADT checkrun failed: 401 Unauthorized")
                return SAPCheckrunResult(
                    status=SAPValidationStatus.UNAVAILABLE,
                    http_status=401,
                    reason="SAP ADT checkrun failed: 401 Unauthorized. Verify credentials.",
                )
            if resp.status_code == 403:
                logger.warning("SAP ADT checkrun failed: 403 Forbidden")
                return SAPCheckrunResult(
                    status=SAPValidationStatus.UNAVAILABLE,
                    http_status=403,
                    reason="SAP ADT checkrun failed: 403 Forbidden. User lacks authorization.",
                )
            if resp.status_code == 404:
                logger.warning("SAP ADT checkrun returned 404 Not Found")
                return SAPCheckrunResult(
                    status=SAPValidationStatus.UNAVAILABLE,
                    http_status=404,
                    reason=f"Repository object URI '{repository_uri}' not found in SAP repository (HTTP 404).",
                )

            logger.warning("SAP ADT checkrun returned unexpected HTTP %d", resp.status_code)
            return SAPCheckrunResult(
                status=SAPValidationStatus.UNAVAILABLE,
                http_status=resp.status_code,
                reason=f"SAP ADT checkrun returned HTTP status {resp.status_code}.",
            )

        except httpx.TimeoutException as e:
            logger.warning("SAP ADT checkrun timed out: %s", self._sanitize_url_for_logging(path))
            return SAPCheckrunResult(
                status=SAPValidationStatus.UNAVAILABLE,
                reason=f"SAP ADT checkrun timed out on {path}: {e}",
            )
        except httpx.ConnectError as e:
            logger.warning("SAP ADT checkrun connection failed: %s", e)
            return SAPCheckrunResult(
                status=SAPValidationStatus.UNAVAILABLE,
                reason=f"Failed to connect to SAP host: {e}",
            )
        except Exception as e:
            logger.warning("Unexpected error during SAP ADT checkrun: %s", e)
            return SAPCheckrunResult(
                status=SAPValidationStatus.UNAVAILABLE,
                reason=f"SAP ADT checkrun encountered unexpected error: {e}",
            )

