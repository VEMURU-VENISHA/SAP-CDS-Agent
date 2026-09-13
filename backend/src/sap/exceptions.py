"""SAP Connector specific exceptions."""

from src.core.exceptions import SAPConnectorError, SAPNotConnectedError, SAPAuthorizationError

__all__ = ["SAPConnectorError", "SAPNotConnectedError", "SAPAuthorizationError"]
