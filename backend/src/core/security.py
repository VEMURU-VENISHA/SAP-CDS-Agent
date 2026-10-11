"""Security and RBAC abstractions for the SAP CDS Platform."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    VIEWER = "VIEWER"
    DEVELOPER = "DEVELOPER"
    SENIOR_DEVELOPER = "SENIOR_DEVELOPER"
    ARCHITECT = "ARCHITECT"
    ADMIN = "ADMIN"


class UserContext(BaseModel):
    """Represents authenticated user context for auditing and approval gating."""

    user_id: str = Field(..., description="Unique user identifier (e.g. employee ID or email)")
    roles: List[UserRole] = Field(default_factory=lambda: [UserRole.DEVELOPER])
    sap_user_alias: Optional[str] = Field(default=None, description="Optional SAP Developer user ID for ADT assignment")
