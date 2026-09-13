# SAP Connector Interface Specification

## 1. Overview
The SAP Connector abstraction layer (`backend/src/sap/`) is designed to isolate the CDS platform from the specific connectivity protocol used to speak with SAP S/4HANA (e.g., ADT HTTP/REST, SAP PyRFC, SAP OData Service Catalog).

In accordance with strict enterprise governance rules:
- **No connection is established in Milestone 1.**
- **No synthetic SAP metadata is returned.**
- Operations without an authenticated SAP endpoint raise explicit, typed `SAPNotConnectedError` exceptions.

---

## 2. Core Operations Protocol

The connector interface is governed by `ISAPConnector` (`backend/src/sap/interface.py`):

### 2.1 Discovery & Search
- `search_cds(query: str, package: Optional[str], layer: Optional[CDSLayer]) -> list[CDSCandidate]`
  Searches standard and custom CDS view entities in the target system.
- `get_cds_metadata(view_name: str) -> CDSMetadata`
  Retrieves complete DDL AST or metadata including annotations, associations, parameters, and field list.
- `search_fields(field_names: list[str], entity_hints: list[str]) -> list[FieldDefinition]`
  Searches data elements and table columns across core standard tables (`VBAK`, `EKKO`, `ACDOCA`, `BKPF`, etc.).
- `get_dependencies(view_name: str, depth: int) -> DependencyGraph`
  Retrieves underlying tables, associations, and parent consumption views.

### 2.2 Development Lifecycle (Human Approval Required)
- `create_cds_draft(view_definition: str, transport_request: str) -> DraftResult`
  Creates an inactive CDS DDL draft object in SAP DEV via Eclipse ADT APIs.
- `validate_cds(view_definition: str) -> ValidationResult`
  Invokes the remote ABAP syntax checker and CDS compiler to validate annotations, SQL syntax, and access controls.
- `activate_cds(view_name: str, transport_request: str) -> ActivationResult`
  Activates the CDS view in SAP DEV dictionary runtime.
