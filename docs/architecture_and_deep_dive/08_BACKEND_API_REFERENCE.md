# 08 - Backend API Reference

## 1. API Architecture & Routing Conventions

The SAP CDS Agent backend exposes a comprehensive RESTful API built with **FastAPI**.
* **Base URL**: `http://localhost:8000`
* **Interactive Documentation**: Available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` (ReDoc).
* **Dual-Prefix Strategy**: Configured in `backend/src/api/router.py`:
  * `/api/v1/*`: Modern, versioned REST endpoints.
  * `/api/*`: Legacy unversioned endpoints maintained for frontend backwards compatibility.

---

## 2. Discovery Endpoints (`backend/src/api/routes/discovery.py`)

### 2.1 Discover Views (`POST /api/v1/discovery/discover`)
Executes full-text FTS5 search and 6-level composite scoring across the 86,296 cataloged CDS views.
* **Request Body**:
  ```json
  {
    "query": "sales order header",
    "domain": "SD",
    "limit": 10,
    "min_score": 0.4
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "total_matches": 42,
    "views": [
      {
        "cds_name": "I_SalesOrder",
        "label": "Sales Order Header",
        "domain": "SD",
        "package": "VA",
        "application_component": "SD-SLS",
        "score": 0.94,
        "score_breakdown": {
          "exact": 1.0,
          "prefix": 1.0,
          "fts": 0.88,
          "domain": 1.0,
          "grain": 1.0,
          "package": 0.9
        }
      }
    ]
  }
  ```

### 2.2 Get View Metadata (`GET /api/v1/discovery/views/{cds_name}`)
Retrieves comprehensive metadata for a specific view.
* **Path Parameter**: `cds_name` (e.g., `I_SalesOrderItem`)
* **Response (200 OK)**:
  ```json
  {
    "cds_name": "I_SalesOrderItem",
    "label": "Sales Order Item",
    "domain": "SD",
    "package": "VA",
    "has_auth_check": true,
    "grain": "Item",
    "source_type": "VIEW_ENTITY"
  }
  ```

### 2.3 Get View Fields (`GET /api/v1/discovery/views/{cds_name}/fields`)
Returns field catalog for a view. Fetches and parses DDL via live SAP ADT if fields are not present in local SQLite.
* **Response (200 OK)**:
  ```json
  {
    "cds_name": "I_SalesOrderItem",
    "field_count": 45,
    "fields": [
      {
        "fieldname": "SalesOrder",
        "field_label": "Sales Document",
        "data_type": "CHAR",
        "is_key": true
      },
      {
        "fieldname": "NetAmount",
        "field_label": "Net Amount",
        "data_type": "DEC",
        "is_key": false
      }
    ]
  }
  ```

### 2.4 Get Associations Graph (`GET /api/v1/discovery/associations/{cds_name}`)
Traverses reachable semantic associations up to 3 hops away.
* **Response (200 OK)**:
  ```json
  {
    "root_entity": "I_SalesOrderItem",
    "depth": 2,
    "edges": [
      {
        "source": "I_SalesOrderItem",
        "target": "I_SalesOrder",
        "association_name": "_SalesOrder",
        "cardinality": "[1..1]"
      },
      {
        "source": "I_SalesOrder",
        "target": "I_Customer",
        "association_name": "_SoldToParty",
        "cardinality": "[1..1]"
      }
    ]
  }
  ```

### 2.5 Live Data Preview (`POST /api/v1/discovery/preview-data`)
Safely executes read-only `SELECT TOP 10` on SAP S/4HANA via ADT.
* **Request Body**:
  ```json
  {
    "cds_name": "I_SalesOrderItem",
    "fields": ["SalesOrder", "SalesOrderItem", "NetAmount", "TransactionCurrency"],
    "max_rows": 10
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "columns": ["SalesOrder", "SalesOrderItem", "NetAmount", "TransactionCurrency"],
    "rows": [
      ["0000000010", "000010", "1250.00", "EUR"],
      ["0000000010", "000020", "450.50", "EUR"]
    ],
    "null_profile": {
      "NetAmount": 0.0,
      "TransactionCurrency": 0.0
    }
  }
  ```

### 2.6 Dry-Run Syntax Checkrun (`POST /api/v1/discovery/validate-pipeline`)
Sends proposed DDL to SAP ADT `/sap/bc/adt/checkruns` for live compiler verification without saving to database.
* **Request Body**:
  ```json
  {
    "ddl_source": "define view entity ZI_Test as select from I_SalesOrder { key SalesOrder }",
    "object_name": "ZI_TEST"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "is_valid": true,
    "error_count": 0,
    "warning_count": 0,
    "messages": []
  }
  ```

---

## 3. Requirements Endpoints (`backend/src/api/routes/requirements.py`)

### 3.1 Parse Requirement (`POST /api/v1/requirements/parse`)
Parses natural language prompt into structured requirement specifications using Gemini 2.5 Flash.
* **Request Body**:
  ```json
  {
    "raw_text": "Create CDS view for open sales orders with billing status and customer region"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "business_goal": "Report open sales orders with billing and customer details",
    "domain": "SD",
    "entities": ["SalesOrder", "BillingDocument", "Customer"],
    "granularity": "SalesOrderItem",
    "metrics": ["NetAmount"],
    "filters": []
  }
  ```

---

## 4. Decisions & Governance Endpoints (`backend/src/api/routes/decisions.py`)

### 4.1 Propose DDL (`POST /api/v1/decisions/propose`)
Synthesizes full ABAP CDS DDL code from selected entities and fields.
* **Request Body**:
  ```json
  {
    "view_name": "ZI_CustomSalesAnalysis",
    "base_entity": "I_SalesOrderItem",
    "selected_fields": ["SalesOrder", "SalesOrderItem", "NetAmount", "TransactionCurrency"],
    "associations": ["_SalesOrder", "_Customer"],
    "label": "Custom Sales Analysis Composite View"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "ddl_code": "@AccessControl.authorizationCheck: #CHECK\n@EndUserText.label: 'Custom Sales Analysis Composite View'\ndefine view entity ZI_CustomSalesAnalysis ...",
    "generation_source": "GEMINI_2_5_FLASH",
    "clean_core_compliant": true
  }
  ```

### 4.2 Record Review Approval (`POST /api/v1/decisions/review`)
Enforces Human-in-the-Loop review sign-off.
* **Request Body**:
  ```json
  {
    "review_id": "rev-8493-2940",
    "reviewer": "ARCHITECT_01",
    "role": "SAP_LEAD_ARCHITECT",
    "decision": "APPROVED",
    "comment": "Verified Clean Core compliance and grain alignment."
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "status": "APPROVED",
    "recorded_at": "2026-10-11T18:00:00Z",
    "audit_hash": "a94f83c1b092..."
  }
  ```

---

## 5. Health & Diagnostic Endpoints (`backend/src/api/routes/health.py`)

* `GET /api/v1/health`: Returns system status (`"healthy"`), version (`"1.0.0"`), and uptime.
* `GET /api/v1/health/sap-status`: Probes SAP ADT endpoint, reports latency (ms), and confirms CSRF handshake state.
* `GET /api/v1/health/metrics`: Returns database size, total views (86,296), associations (1,139), and field indexes (212).
