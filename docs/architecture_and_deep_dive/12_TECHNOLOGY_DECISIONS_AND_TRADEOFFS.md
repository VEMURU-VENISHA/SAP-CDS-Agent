# 12 - Technology Decisions & Trade-offs (ADRs)

## Architecture Decision Records (ADRs)

This document records the architectural rationale, trade-offs, and design justifications behind key technology choices in the SAP CDS Agent platform.

---

### ADR-01: SQLite with FTS5 vs. Vector Databases (Chroma / Pinecone / Qdrant)

* **Status**: Accepted
* **Context**: We needed a search and catalog engine capable of indexing 86,296 SAP CDS views and providing sub-second search for business and technical queries.
* **Options Considered**:
  1. *Vector Databases (ChromaDB, Pinecone, FAISS)* with embedding models (text-embedding-ada-002, etc.).
  2. *SQLite with FTS5 (Full-Text Search)* using BM25 ranking.
  3. *Elasticsearch / OpenSearch cluster*.
* **Decision**: Selected **SQLite with FTS5**.
* **Rationale**:
  * **Precision on Technical Identifiers**: SAP developers frequently search for exact technical names (`I_SalesOrderItem`, `I_BillingDocItem`, `VBRK`). Embedding models suffer from semantic blur on technical identifiers, often returning unrelated views with similar sentence embeddings. FTS5 with Porter stemming provides exact token and prefix matching.
  * **Zero Operational Footprint**: Embedding databases require background worker processes, GPU inference, or external cloud subscriptions. SQLite embeds directly inside Python as a single 45 MB file.
  * **Query Latency**: SQLite FTS5 executes searches across 86,296 records in **< 4 milliseconds**, faster than network roundtrips to managed vector cloud endpoints.

---

### ADR-02: FastAPI vs. Flask / Django / Node.js

* **Status**: Accepted
* **Context**: Choice of backend framework for serving the REST API, running async background tasks, and interfacing with Python AI libraries.
* **Decision**: Selected **FastAPI (Python 3.11+)**.
* **Rationale**:
  * **Pydantic v2 Type Safety**: FastAPI validates every incoming and outgoing payload at runtime using Rust-backed Pydantic v2, eliminating runtime schema bugs.
  * **Native Asynchronous I/O**: High-concurrency async support (`asyncio`) allows non-blocking HTTP calls to live SAP ADT endpoints and the Google Gemini API.
  * **Automatic OpenAPI Documentation**: Automatically generates interactive Swagger UI (`/docs`) directly from code annotations without manual documentation maintenance.

---

### ADR-03: Direct SAP ADT REST Client vs. PyRFC / SAP NetWeaver RFC SDK

* **Status**: Accepted
* **Context**: Integrating with the live SAP S/4HANA 2023 system to perform DDL reads, checkruns, and data previews.
* **Options Considered**:
  1. *PyRFC with SAP NetWeaver RFC SDK*: Calling ABAP function modules via RFC.
  2. *Native REST over SAP ADT (ABAP Development Tools)* on HTTPS port 44301.
* **Decision**: Selected **Native REST over SAP ADT**.
* **Rationale**:
  * **No Native C Dependencies**: `PyRFC` requires compiling proprietary SAP C/C++ libraries (`libsapnwrfc.so` or `sapnwrfc.dll`), creating severe OS compatibility and deployment hurdles in containerized or cross-platform environments.
  * **Standard HTTPS Protocol**: ADT runs over standard HTTPS (port 44301), traversing firewalls seamlessly.
  * **Native Development Capabilities**: ADT natively exposes the exact endpoints required for developer tooling: DDL source extraction (`/ddic/ddls/sources`), ABAP compiler checkruns (`/checkruns`), and SQL freestyle preview (`/datapreview/freestyle`).

---

### ADR-04: Deterministic Rule Validator vs. Autonomous LLM Code Generation

* **Status**: Accepted
* **Context**: Determining whether the LLM should be solely responsible for generating syntactically valid and compliant CDS views.
* **Decision**: Enforced a **Dual-Layer Architecture**: Generative LLM proposes $\rightarrow$ Deterministic AST Validator verifies.
* **Rationale**:
  * **Zero-Hallucination Tolerance**: In an enterprise SAP system, invalid database names (e.g. querying `VBAK` instead of `I_SalesOrder`) break S/4HANA Clean Core compliance. An LLM cannot be guaranteed to never hallucinate.
  * **Deterministic Enforcement**: Rules such as customer namespace (`Z*`/`Y*`), SQL view name length ($\le 16$), and primary key requirements are mathematical invariants. Validating them with a deterministic Python AST parser guarantees 100% compliance.

---

### ADR-05: React 18 + Vite vs. Next.js / Server-Side Rendering (SSR)

* **Status**: Accepted
* **Context**: Selecting the frontend architecture for the 13-stage developer pipeline.
* **Decision**: Selected **React 18 SPA bundled with Vite**.
* **Rationale**:
  * **Internal Developer Tool Nature**: The SAP CDS Agent is an internal engineering tool behind enterprise firewalls, not a public consumer website. Search Engine Optimization (SEO) and SSR are irrelevant.
  * **Development Velocity**: Vite provides near-instantaneous hot reloading and build speeds.
  * **Simplified Deployment**: An SPA compiles to static assets (`dist/`), eliminating the need to maintain a separate Node.js server runtime alongside the Python FastAPI backend.
