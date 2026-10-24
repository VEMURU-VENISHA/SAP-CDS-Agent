# 15 - Implementation Gaps, Technical Debt & Production Hardening

## 1. Known Implementation Gaps & Technical Debt

While the SAP CDS Agent is fully operational and backed by 311 passing automated tests, a rigorous architectural assessment identifies several areas of technical debt and enhancement opportunities:

### 1.1 Frontend Component Monolith (`RecentPipelines.tsx`)
* **Observation**: `frontend/src/components/RecentPipelines.tsx` contains approximately 3,500 lines of code in a single file.
* **Impact**: While it works reliably and maintains unified state across all 13 pipeline stages, maintaining and testing this component becomes harder as features grow.
* **Recommended Refactoring**: Split into modular step components inside a dedicated directory `frontend/src/components/pipeline/`:
  * `Step01RequirementInput.tsx`
  * `Step04DiscoveryGrid.tsx`
  * `Step05AssociationGraph.tsx`
  * `Step07DataPreviewGrid.tsx`
  * `Step08DDLEditor.tsx`
  * `Step10GovernanceSignoff.tsx`
  * `Step12CheckrunConsole.tsx`

### 1.2 Catalog Field Indexing Coverage
* **Observation**: Out of 86,296 cataloged CDS views, **212 views** currently have their field definitions pre-indexed in `cds_fields`.
* **Current Mitigation**: The `CDSDiscoveryService` implements an on-demand live fallback—if fields are not in SQLite, it fetches the DDL from SAP ADT in real time and caches the parsed fields.
* **Recommended Enhancement**: Execute a background batch ingestion script to pre-index fields for the top 2,500 most frequently queried standard VDM views (`I_Sales*`, `I_Purchase*`, `I_Billing*`, `I_Journal*`, `I_Customer*`), eliminating the initial 300ms ADT network roundtrip.

### 1.3 Review Store Database Separation
* **Observation**: The Human-in-the-Loop review and audit store currently uses SQLite.
* **Impact**: SQLite Write-Ahead Logging (WAL) supports unlimited concurrent readers but serializes write transactions.
* **Recommended Enhancement**: For enterprise deployments with hundreds of concurrent developers and reviewers, migrate the review and audit store to **PostgreSQL**, keeping `sap_cds.db` as a dedicated read-only local SQLite catalog.

### 1.4 Multi-LLM Provider Abstraction
* **Observation**: The AI synthesis layer is currently optimized for Google Gemini 2.5 Flash via `GeminiService`.
* **Recommended Enhancement**: Introduce an `ILLMProvider` interface allowing dynamic runtime switching between Google Gemini 2.5 Flash, Anthropic Claude 3.5 Sonnet, and OpenAI GPT-4o based on enterprise license availability.

---

## 2. Production Hardening Checklist

Prior to deploying the SAP CDS Agent in a mission-critical corporate environment, complete the following hardening steps:

- [ ] **Containerization & Orchestration**:
  - Package backend into a multi-stage Docker container (`python:3.11-slim`).
  - Package frontend into an Nginx Alpine container serving optimized static assets.
  - Provide a `docker-compose.yml` for unified local orchestration.
- [ ] **Enterprise Secrets Management**:
  - Replace local `.env` storage with HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault for SAP service account passwords and LLM API keys.
- [ ] **Rate Limiting & DoS Protection**:
  - Add `slowapi` rate limiting on `/api/v1/discovery/preview-data` to prevent overloading the live SAP S/4HANA application server.
- [ ] **Redis Response Caching**:
  - Add Redis caching for ADT DDL fetches and FTS5 search queries to reduce latency for repeated user searches.
- [ ] **Dual-Custody Transport Staging**:
  - Require two independent user approvals (Lead Architect + Security Lead) in the `ReviewStore` before generating final CTS transport staging manifests.
