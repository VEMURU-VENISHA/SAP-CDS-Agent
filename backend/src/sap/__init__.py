"""SAP Connector Layer: Abstract interfaces and DTOs.

Milestone 1 adheres to strict enterprise guardrails:
- Pure abstract interface definition (ISAPConnector)
- Unconnected connector stub that strictly refuses to emit synthetic metadata
- Future real SAP ADT/RFC/OData integration can be swapped in via dependency injection
"""

from src.sap.interface import ISAPConnector
from src.sap.models import (
    ActivationResult,
    CDSMetadata,
    DependencyGraph,
    DraftResult,
    FieldDefinition,
    SAPSystemInfo,
)
from src.sap.connector import UnconnectedSAPConnector

__all__ = [
    "ISAPConnector",
    "UnconnectedSAPConnector",
    "SAPSystemInfo",
    "CDSMetadata",
    "FieldDefinition",
    "DependencyGraph",
    "DraftResult",
    "ActivationResult",
]
