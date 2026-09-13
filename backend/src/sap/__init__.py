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
from src.sap.connector import (
    UnconnectedSAPConnector,
    get_sap_connector,
    reset_sap_connector,
)
from src.sap.adt_connector import SAPADTConnector

__all__ = [
    "ISAPConnector",
    "UnconnectedSAPConnector",
    "SAPADTConnector",
    "get_sap_connector",
    "reset_sap_connector",
    "SAPSystemInfo",
    "CDSMetadata",
    "FieldDefinition",
    "DependencyGraph",
    "DraftResult",
    "ActivationResult",
]

