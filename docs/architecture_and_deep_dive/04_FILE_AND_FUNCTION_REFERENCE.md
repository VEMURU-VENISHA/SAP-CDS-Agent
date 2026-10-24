# 04 - File & Function Reference

## 1. Complete Codebase Directory Map

```
SAP-CDS-Agent/
|-- backend/
|   |-- data/
|   |   `-- sap_cds.db               # SQLite database: 86,296 views, FTS5 index, associations
|   |-- src/
|   |   |-- __init__.py
|   |   |-- main.py                  # Application entry point, lifespan, CORS, middleware
|   |   |-- config.py                # Pydantic v2 configuration, environment settings
|   |   |-- api/
|   |   |   |-- __init__.py
|   |   |   |-- router.py            # Master router mounting /api/v1 and /api
|   |   |   `-- routes/
|   |   |       |-- __init__.py
|   |   |       |-- discovery.py     # Search, fields, associations, preview, checkruns
|   |   |       |-- requirements.py  # Natural language requirement parsing & normalization
|   |   |       |-- decisions.py     # DDL proposal synthesis, evaluation, review workflow
|   |   |       `-- health.py        # System health, SAP ADT connection, and DB metrics
|   |   |-- models/
|   |   |   |-- __init__.py
|   |   |   |-- entities.py          # CDS View, Field, Association, Join entities
|   |   |   |-- discovery.py         # Search query, filter, and scoring models
|   |   |   |-- requirements.py      # Parsed requirement and normalizer models
|   |   |   `-- decisions.py         # Proposal, DDL generation, and review models
|   |   |-- sap/
|   |   |   |-- __init__.py
|   |   |   |-- adt_client.py        # Native REST client for SAP ADT over HTTPS (port 44301)
|   |   |   |-- adt_connector.py     # ISAPConnector interface and ADT connector adapter
|   |   |   `-- parser.py            # Lexer/parser for ABAP CDS DDL syntax trees
|   |   `-- services/
|   |       |-- __init__.py
|   |       |-- discovery_service.py # Catalog querying, FTS5 search, BFS association graph
|   |       |-- cds_generation_validator.py # Clean Core rule engine & syntax validator
|   |       |-- gemini_service.py    # Google Gemini 2.5 Flash API client & DDL synthesis
|   |       |-- review_service.py    # Human-in-the-Loop governance, approvals, audit logs
|   |       `-- normalizer.py        # Business domain mapping & synonym dictionary
|   `-- tests/                       # 28 test files, 311 passing tests
`-- frontend/
    |-- src/
    |   |-- main.tsx                 # React DOM bootstrap
    |   |-- App.tsx                  # Root layout, theme provider, header & pipeline view
    |   |-- components/
    |   |   |-- Header.tsx           # Global header with live status badges & DB stats
    |   |   `-- RecentPipelines.tsx  # Interactive 13-stage HITL pipeline workspace
    |   |-- services/
    |   |   `-- api.ts               # Axios client and backend API wrappers
    |   `-- types/
    |       `-- index.ts             # TypeScript interfaces matching backend models
    |-- package.json
    `-- vite.config.ts
```

---

## 2. Backend Module Reference

### `backend/src/main.py` (223 lines)
* **Purpose**: Core bootstrap module for the FastAPI application.
* **Key Functions**:
  * `create_application() -> FastAPI`: Instantiates FastAPI, applies middleware (`CORSMiddleware`, `CorrelationIdMiddleware`), registers exception handlers, and mounts the master router.
  * `lifespan(app: FastAPI)`: Asynchronous context manager handling startup events (verifying SQLite database connection, checking SAP ADT reachability, preloading caches) and graceful shutdown.
* **Error Handling**: Global exception handler transforms unhandled Python exceptions into standardized RFC 7807 problem details with correlation IDs.

### `backend/src/config.py` (203 lines)
* **Purpose**: Type-safe hierarchical settings management powered by Pydantic v2 `BaseSettings`.
* **Classes**:
  * `SAPSettings`: Host, port (`44301`), client (`100`), credentials, timeout, SSL verification flag.
  * `GeminiSettings`: API key, model version (`gemini-2.5-flash`), temperature, max output tokens.
  * `DatabaseSettings`: SQLite path (`data/sap_cds.db`), pool size, timeout.
  * `Settings`: Aggregates all settings sub-models into a single singleton `get_settings()`.

### `backend/src/api/router.py` (152 lines)
* **Purpose**: Aggregates all route modules and provides dual-prefix exposure.
* **Mounting**:
  * `/api/v1`: Primary REST standard API prefix.
  * `/api`: Legacy backward-compatibility prefix ensuring existing frontend calls resolve seamlessly.

### `backend/src/api/routes/discovery.py` (520 lines)
* **Purpose**: Exposes search, field inspection, association graph navigation, data preview, and checkruns.
* **Key Endpoints**:
  * `POST /discover` or `GET /search`: Executes FTS5 search and 6-level match scoring.
  * `GET /views/{name}`: Retrieves full metadata for a specific CDS view.
  * `GET /views/{name}/fields`: Returns field catalog for an entity, triggering live ADT retrieval if missing.
  * `GET /associations/{name}`: Returns incoming and outgoing associations up to 3 hops.
  * `POST /preview-data`: Triggers live read-only data preview via SAP ADT freestyle query.
  * `POST /validate-pipeline`: Executes dry-run ABAP syntax checkrun against live SAP kernel.

### `backend/src/api/routes/requirements.py` (278 lines)
* **Purpose**: Natural language parsing and business requirement normalization.
* **Key Endpoints**:
  * `POST /parse`: Invokes Gemini LLM (or regex fallback) to extract entities, metrics, and filters.
  * `POST /normalize`: Maps colloquial terms to canonical SAP domains and packages.
  * `POST /validate`: Verifies requirement completeness before catalog search.

### `backend/src/api/routes/decisions.py` (304 lines)
* **Purpose**: DDL synthesis, evaluation, and Human-in-the-Loop review lifecycle.
* **Key Endpoints**:
  * `POST /propose`: Generates CDS DDL code proposals using Gemini 2.5 Flash.
  * `POST /evaluate`: Evaluates generated DDL against deterministic Clean Core rules.
  * `POST /review`: Records developer/architect approval actions and audit logs.
  * `GET /export`: Exports final DDL artifact formatted for transport release.

### `backend/src/api/routes/health.py` (148 lines)
* **Purpose**: Liveness, readiness, and connectivity diagnostics.
* **Key Endpoints**:
  * `GET /health`: Basic backend liveness check.
  * `GET /sap-status`: Real-time probe of SAP ADT endpoint and CSRF token availability.
  * `GET /metrics`: Returns catalog metrics (total views, indexed fields, association count).

### `backend/src/services/discovery_service.py` (2,104 lines)
* **Purpose**: Core catalog intelligence engine.
* **Class**: `CDSDiscoveryService`
* **Key Methods**:
  * `discover_views(query, filters, limit)`: Tokenizes query, queries SQLite FTS5 table `cds_views_fts`, and computes weighted relevance scores.
  * `find_association_paths(source_entity, max_depth)`: Implements BFS graph traversal to find semantic connection paths.
  * `sync_incremental()`: Performs incremental metadata sync between live SAP system and local SQLite catalog.
  * `get_view_fields_with_live_fallback(cds_name)`: Queries `cds_fields`; if empty, fetches DDL from SAP ADT, parses fields via `CDSDDLParser`, and caches them locally.

### `backend/src/services/cds_generation_validator.py` (924 lines)
* **Purpose**: Deterministic rule and syntax validation engine for SAP CDS DDL.
* **Classes**: `CDSGenerationValidator`, `CDSDDLParser`
* **Key Methods**:
  * `validate_ddl(ddl: str) -> ValidationResult`: Runs sequential validation checks:
    * `_check_clean_core_compliance()`: Rejects legacy table references (`VBAK`, `MARA`, etc.).
    * `_check_namespace()`: Enforces `Z*` or `Y*` prefix.
    * `_check_sql_view_name()`: Enforces max 16 characters for `@AbapCatalog.sqlViewName`.
    * `_check_key_definitions()`: Ensures at least one primary key is defined.
    * `_check_amount_currency_semantics()`: Validates that `@Semantics.amount` is paired with currency code.

### `backend/src/services/gemini_service.py` (1,017 lines)
* **Purpose**: AI generation engine integrating Google Gemini 2.5 Flash.
* **Class**: `GeminiService`
* **Key Methods**:
  * `generate_cds_ddl(context)`: Grounded prompt injection synthesizing production-ready ABAP CDS DDL.
  * `parse_requirement(prompt)`: Extracts structured intent, entities, metrics, and filters from freeform text.
  * `repair_ddl_syntax(ddl, error_message)`: Multi-shot repair routine that feeds syntax errors back to the model to produce corrected DDL.

### `backend/src/services/review_service.py` (1,456 lines)
* **Purpose**: Governance engine enforcing Human-in-the-Loop review gates.
* **Class**: `ReviewStore`
* **Key Methods**:
  * `create_review_record(ddl, metadata)`: Creates a pending review entry with unique UUID.
  * `record_approval(review_id, role, comment)`: Updates status to `APPROVED` and writes immutable audit entry.
  * `get_audit_trail(review_id)`: Retrieves history of reviews, edits, and decisions.

### `backend/src/services/normalizer.py` (429 lines)
* **Purpose**: Semantic domain mapping and keyword canonicalization.
* **Key Methods**:
  * `resolve_domain_from_sap_metadata(package, app_component)`: Maps ABAP package names (`DEVCLASS`) and Application Components (`DF14L`) to one of 10 standard business domains (`SD`, `MM`, `FI`, `CO`, `PP`, `QM`, `PM`, `HCM`, `LE`, `BASIS`).
  * `normalize_term(term)`: Canonicalizes user synonyms (e.g., "customer invoice" -> "BillingDocument").

### `backend/src/sap/adt_client.py` (1,774 lines)
* **Purpose**: Native REST communication client for SAP ABAP Development Tools (ADT).
* **Class**: `SAPADTClient`
* **Key Methods**:
  * `fetch_csrf_token()`: Fetches CSRF token using `HEAD /sap/bc/adt/discovery` with `X-CSRF-Token: Fetch`.
  * `_assert_zero_write_policy(method, url)`: Enforces zero-write security guarantee prior to issuing HTTP calls.
  * `fetch_ddl(cds_name)`: Retrieves raw DDL source code via `GET /sap/bc/adt/ddic/ddls/sources/{cds_name}`.
  * `run_syntax_check(ddl_source, object_name)`: Performs sandboxed syntax check via `POST /sap/bc/adt/checkruns`.
  * `preview_data(sql_query, max_rows)`: Executes read-only data preview via `POST /sap/bc/adt/datapreview/freestyle`.

### `backend/src/sap/adt_connector.py` (1,119 lines)
* **Purpose**: Connector abstraction implementing `ISAPConnector`.
* **Class**: `SAPADTConnector`
* **Key Methods**:
  * Wraps `SAPADTClient` with graceful degradation: switches to local simulation/mocking if SAP network connectivity is unavailable.

### `backend/src/sap/parser.py` (870 lines)
* **Purpose**: Deterministic tokenizer and parser for ABAP CDS DDL.
* **Class**: `CDSDDLParser`
* **Key Methods**:
  * `parse(ddl: str) -> ParsedCDSView`: Parses view entity name, base data sources, join clauses, associations, cardinality, fields, expressions, and annotations into an Abstract Syntax Tree (AST).

---

## 3. Frontend Architecture Reference

### `frontend/src/App.tsx`
* Top-level component rendering the global `Header` and the `RecentPipelines` workspace.
* Manages dark/light theme state and handles global error toasts.

### `frontend/src/components/Header.tsx`
* Displays system liveness indicator (green/amber/red).
* Shows SAP ADT connection badge (e.g., `Connected to YAWSS4HSBX:44301`).
* Shows local catalog metrics (`86,296 CDS Views Loaded`).

### `frontend/src/components/RecentPipelines.tsx` (~3,500 lines)
* The central orchestration UI component powering the 13-stage interactive HITL pipeline.
* Maintains pipeline state machine, active step indicator, form inputs, DDL editor, diff viewer, and approval buttons.

### `frontend/src/services/api.ts`
* Axios-based API client with configured base URL (`http://localhost:8000/api`).
* Implements unified error response interceptor and timeout configuration.
