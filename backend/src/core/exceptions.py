"""Custom domain exception hierarchy for the SAP CDS Platform."""

from typing import Any, Dict, Optional


class PlatformBaseException(Exception):
    """Base class for all platform exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundError(PlatformBaseException):
    """Raised when a requested CDS view, requirement, or pipeline entity is not found."""

    def __init__(self, entity_name: str, identifier: str):
        super().__init__(
            message=f"{entity_name} '{identifier}' was not found.",
            code="ENTITY_NOT_FOUND",
            status_code=404,
            details={"entity": entity_name, "identifier": identifier},
        )


class InvalidRequirementError(PlatformBaseException):
    """Raised when an incoming business requirement fails structural or semantic validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="INVALID_REQUIREMENT",
            status_code=400,
            details=details,
        )


class SAPConnectorError(PlatformBaseException):
    """Base exception for SAP connectivity, RFC, ADT, or catalog failures."""

    def __init__(self, message: str, code: str = "SAP_CONNECTOR_ERROR", status_code: int = 502, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code=code, status_code=status_code, details=details)


class SAPNotConnectedError(SAPConnectorError):
    """Raised when an operation requires an active SAP S/4HANA connection that is disabled/unconnected."""

    def __init__(self, operation_name: str):
        super().__init__(
            message=(
                f"SAP operation '{operation_name}' cannot be performed. "
                "The SAP connector is in 'unconnected' mode as mandated by Milestone 1 enterprise guardrails. "
                "No live SAP connection or synthetic metadata has been configured."
            ),
            code="SAP_NOT_CONNECTED",
            status_code=503,
            details={"operation": operation_name, "milestone": "1", "resolution": "Connect in future milestone after auth approval"},
        )


class SAPAuthorizationError(SAPConnectorError):
    """Raised when SAP user authorizations or ADT scopes are insufficient."""

    def __init__(self, auth_object: str, activity: str):
        super().__init__(
            message=f"SAP authorization missing for object '{auth_object}' with activity '{activity}'.",
            code="SAP_AUTH_INSUFFICIENT",
            status_code=403,
            details={"auth_object": auth_object, "activity": activity},
        )


class SAPConfigurationError(SAPConnectorError):
    """Raised when required SAP connection settings are missing or malformed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="SAP_CONFIG_ERROR",
            status_code=500,
            details=details,
        )


class SAPAuthenticationError(SAPConnectorError):
    """Raised when SAP HTTP authentication fails (HTTP 401)."""

    def __init__(self, message: str = "SAP ADT authentication failed. Check credentials and client configuration."):
        super().__init__(
            message=message,
            code="SAP_AUTH_FAILED",
            status_code=401,
            details={"status": 401},
        )


class SAPPermissionError(SAPConnectorError):
    """Raised when SAP user lacks authorization for the requested ADT resource (HTTP 403)."""

    def __init__(self, resource: str = ""):
        super().__init__(
            message=f"Access forbidden to SAP ADT resource '{resource}'. Check authorization profile S_ADT_RES.",
            code="SAP_PERMISSION_DENIED",
            status_code=403,
            details={"resource": resource, "status": 403},
        )


class SAPNotFoundError(SAPConnectorError):
    """Raised when a requested CDS definition or ADT resource does not exist in the SAP system (HTTP 404)."""

    def __init__(self, resource_name: str):
        super().__init__(
            message=f"SAP CDS resource '{resource_name}' was not found in the target system.",
            code="SAP_RESOURCE_NOT_FOUND",
            status_code=404,
            details={"resource": resource_name, "status": 404},
        )


class SAPConnectionError(SAPConnectorError):
    """Raised when connection to SAP host fails or times out."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="SAP_CONNECTION_ERROR",
            status_code=502,
            details=details,
        )


class SAPSecurityError(SAPConnectorError):
    """Raised when a pre-socket security guard or zero-write policy violation is detected."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="SAP_SECURITY_VIOLATION",
            status_code=403,
            details=details,
        )


class GovernanceApprovalRequiredError(PlatformBaseException):
    """Raised when an operation (such as CDS draft creation or activation) requires explicit human sign-off."""

    def __init__(self, action: str, object_name: str):
        super().__init__(
            message=f"Action '{action}' on object '{object_name}' requires explicit senior developer or architect approval.",
            code="GOVERNANCE_APPROVAL_REQUIRED",
            status_code=403,
            details={"action": action, "object": object_name},
        )


class AgentExecutionError(PlatformBaseException):
    """Raised when an AI agent within the LangGraph pipeline encounters an unrecoverable failure."""

    def __init__(self, agent_name: str, reason: str):
        super().__init__(
            message=f"Agent '{agent_name}' execution failed: {reason}",
            code="AGENT_EXECUTION_ERROR",
            status_code=500,
            details={"agent": agent_name, "reason": reason},
        )
