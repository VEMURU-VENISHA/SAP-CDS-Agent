# 13 - Interview & Project Defense Guide

## 1. Fast Summaries

### 30-Second Elevator Pitch
> *"The SAP CDS Agent is an enterprise AI developer platform that accelerates SAP S/4HANA Core Data Services development. It takes natural language business requirements and automatically discovers the right SAP standard interface views from an indexed catalog of 86,296 views. It navigates multi-hop associations up to 3 hops away, generates production-ready CDS DDL using Google Gemini 2.5 Flash, deterministically enforces Clean Core rules and customer namespaces, and validates the code against a live SAP system via ADT checkruns—all while strictly enforcing a zero-write security policy."*

### 2-Minute Architectural Walkthrough
> *"The system is built on a clean three-tier architecture:
> On the frontend, a React 18 Single Page Application provides a 13-stage Human-in-the-Loop wizard that gives developers full control over requirement parsing, field selection, live data preview, DDL generation, and approval sign-off.
> On the backend, FastAPI orchestrates the pipeline with sub-millisecond local discovery powered by SQLite FTS5 with BM25 ranking across 86,296 cataloged views. We traverse semantic relationships using a Breadth-First Search association graph.
> For code generation, we combine Gemini 2.5 Flash with deterministic AST linting: the LLM proposes DDL grounded in real SAP vocabulary, and a deterministic Python rule engine verifies customer namespaces (`Z*`/`Y*`), SQL view name lengths ($\le 16$), and Clean Core rules.
> Finally, our native SAP ADT client communicates directly with SAP S/4HANA over HTTPS port 44301. It runs in-memory syntax checkruns on the ABAP kernel and data previews without ever writing to the database, guaranteed by our pre-socket `_assert_zero_write_policy` guard."*

---

## 2. Role-Based Interview Defense & Deep Dives

### Perspective 1: The SAP S/4HANA Enterprise Architect
**Q: How do you prevent developers from violating SAP's "Clean Core" extensibility paradigm?**
* **Answer**: *"We enforce Clean Core deterministically at two levels. First, our discovery engine prioritizes released SAP Virtual Data Model interface views (`I_*`) and composite views. Second, our `CDSGenerationValidator` parses the generated DDL's AST and cross-references data sources against a blacklist of classical transparent tables (`VBAK`, `VBAP`, `MARA`, `BSEG`, etc.). If a query references a raw table, the validator blocks the pipeline immediately and suggests the released SAP CDS counterpart."*

**Q: Why use CDS Associations instead of traditional SQL Joins?**
* **Answer**: *"Traditional SQL joins in ABAP execute eagerly, loading unneeded relational data into memory. SAP CDS associations are 'joins on demand'—they define the relationship in metadata and only trigger database joins when fields from the associated entity are explicitly referenced in a consumer query. Our agent automatically discovers existing associations from `cds_associations` and generates proper association syntax with cardinality (`[0..1]`, `[1..*]`), ensuring optimal SAP HANA performance."*

---

### Perspective 2: The Senior Backend / Python Engineer
**Q: Why did you choose SQLite with FTS5 instead of PostgreSQL or a Vector DB?**
* **Answer**: *"Three reasons: precision, operational simplicity, and latency. In enterprise SAP, developers search for exact technical names like `I_SalesOrderItem`. Vector embeddings suffer from semantic blur on technical tokens, whereas SQLite FTS5 with BM25 ranking and Porter stemming delivers exact and tokenized matches in under 4 milliseconds across 86,296 rows. Furthermore, bundling the entire catalog in a single 45 MB SQLite database file eliminates external infrastructure dependencies, making local development and CI/CD testing instantaneous."*

**Q: How do you handle distributed tracing and error observability?**
* **Answer**: *"We implemented a custom `CorrelationIdMiddleware` in FastAPI that checks for an incoming `X-Correlation-ID` header or generates a UUIDv4. This correlation ID is bound to the logging context and propagated into all downstream service calls, ADT HTTP headers, and error responses. If an unhandled exception occurs, our global exception handler returns an RFC 7807 problem detail payload containing the correlation ID, allowing instant log lookup."*

---

### Perspective 3: The AI & LLM Engineer
**Q: How do you mitigate hallucinations when generating ABAP CDS DDL?**
* **Answer**: *"We never allow the LLM to generate code in a vacuum. We ground the prompt in three ways:
1. We inject real schemas from `cds_fields` and verified associations from `cds_associations` into the prompt context.
2. We provide few-shot examples and approved SAP VDM annotations via our `HEURISTIC_SAP_VOCABULARY`.
3. We use a low temperature (`0.1`) on Gemini 2.5 Flash.
Crucially, the LLM is only an advisory engine—all output is immediately parsed by our deterministic AST validator. If syntax or rule violations occur, our automated repair loop feeds the exact compiler error back into Gemini for up to 3 self-healing iterations."*

---

### Perspective 4: The Security & Compliance Officer
**Q: What prevents the AI agent from altering or corrupting production SAP data?**
* **Answer**: *"We implement defense-in-depth centered around our pre-socket `_assert_zero_write_policy` guard in `SAPADTClient`. Every outbound HTTP request is intercepted before socket transmission. All `PUT`, `DELETE`, and `PATCH` methods are blocked unconditionally. `POST` requests are whitelisted only for read-only functional endpoints: `/datapreview/freestyle` (which enforces `TOP 10` limits and prohibits DML) and `/checkruns` (which compiles code in memory without saving). Furthermore, credentials are never committed to git and are isolated in local `.env` files."*

---

## 3. How to Whiteboard the Architecture in an Interview

When asked to draw the system on a whiteboard:
1. **Draw 3 Horizontal Swimlanes**:
   * **Top**: *Frontend (React 18 / Vite)* $\rightarrow$ Mention 13-stage HITL pipeline.
   * **Middle**: *Backend Services (FastAPI)* $\rightarrow$ Draw Discovery Service, SQLite FTS5 catalog, Gemini LLM, and Validator.
   * **Bottom**: *SAP S/4HANA (ADT REST)* $\rightarrow$ Highlight HTTPS port 44301 and the Zero-Write Security Guard.
2. **Trace the Golden Path**:
   * Draw an arrow from User Prompt $\rightarrow$ Gemini Parser $\rightarrow$ SQLite FTS5 Search (sub-5ms) $\rightarrow$ BFS Association Graph (3 hops) $\rightarrow$ Gemini DDL Generation $\rightarrow$ Deterministic AST Validation $\rightarrow$ Live ADT Checkrun $\rightarrow$ Human Approval Gate.
