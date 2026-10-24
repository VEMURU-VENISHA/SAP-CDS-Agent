# SAP CDS Agent: Architecture & Deep Dive Documentation Suite

Welcome to the comprehensive technical documentation and architecture reference for the **SAP CDS Agent** platform.

This documentation suite covers every layer of the system: from SAP ABAP Core Data Services (CDS) discovery and SQLite FTS5 catalog ingestion, to BFS multi-hop graph traversal, Gemini LLM DDL synthesis, deterministic Clean Core validation, and 13-stage Human-in-the-Loop (HITL) governance.

---

## 🗺️ Master Document Directory & Recommended Reading Order

| # | Document | Target Audience | Primary Focus |
|---|---|---|---|
| **01** | [01_PROJECT_OVERVIEW.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/01_PROJECT_OVERVIEW.md) | All / New Engineers | Business problem, enterprise context, core value proposition, key metrics. |
| **02** | [02_SYSTEM_ARCHITECTURE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/02_SYSTEM_ARCHITECTURE.md) | Architects / Leads | High-level topology, component boundaries, data flow diagrams, security perimeters. |
| **03** | [03_END_TO_END_DATA_FLOW.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/03_END_TO_END_DATA_FLOW.md) | Full-Stack Developers | Step-by-step lifecycle of a request across all 13 pipeline phases with payload traces. |
| **04** | [04_FILE_AND_FUNCTION_REFERENCE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/04_FILE_AND_FUNCTION_REFERENCE.md) | Backend / Frontend Devs | Complete directory map, Python class & function reference, React component breakdown. |
| **05** | [05_DATA_SOURCES_AND_PROVENANCE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/05_DATA_SOURCES_AND_PROVENANCE.md) | Data / SAP Engineers | Live SAP S/4HANA 2023 metadata extraction, table provenance, domain resolution logic. |
| **06** | [06_DATABASE_AND_STORAGE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/06_DATABASE_AND_STORAGE.md) | DB / Data Engineers | SQLite schema (`sap_cds.db`), FTS5 full-text indexing, query patterns, indexing strategy. |
| **07** | [07_SAP_ADT_AND_CDS_DISCOVERY.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/07_SAP_ADT_AND_CDS_DISCOVERY.md) | SAP ABAP Developers | ADT REST protocols, CSRF handling, zero-write policy, checkruns, data preview. |
| **08** | [08_BACKEND_API_REFERENCE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/08_BACKEND_API_REFERENCE.md) | Backend / API Consumers | FastAPI endpoints, OpenAPI schemas, request/response models, error handling. |
| **09** | [09_FRONTEND_WALKTHROUGH.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/09_FRONTEND_WALKTHROUGH.md) | Frontend Developers | React 18, Vite, Tailwind CSS, 13-stage interactive HITL pipeline UI walkthrough. |
| **10** | [10_AGENT_VALIDATION_AND_LLM.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/10_AGENT_VALIDATION_AND_LLM.md) | AI / LLM Engineers | Gemini 2.5 Flash prompting, deterministic Clean Core validation, regex syntax repairs. |
| **11** | [11_TESTING_AND_VERIFICATION.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/11_TESTING_AND_VERIFICATION.md) | QA / DevOps Engineers | Pytest test suite (311 tests), test fixtures, live vs. mock testing, coverage breakdown. |
| **12** | [12_TECHNOLOGY_DECISIONS_AND_TRADEOFFS.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/12_TECHNOLOGY_DECISIONS_AND_TRADEOFFS.md) | Architects / Tech Leads | Architecture Decision Records (ADRs): SQLite vs Vector DB, Fastify vs FastAPI, etc. |
| **13** | [13_INTERVIEW_AND_PROJECT_DEFENSE.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/13_INTERVIEW_AND_PROJECT_DEFENSE.md) | Candidates / Leads | 30-second elevator pitch, deep technical Q&A, whiteboarding guide, defense tactics. |
| **14** | [14_GLOSSARY.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/14_GLOSSARY.md) | All Readers | SAP ABAP CDS, VDM, ADT, Clean Core, and Python/AI terminology definitions. |
| **15** | [15_IMPLEMENTATION_GAPS_AND_RISKS.md](file:///c:/Users/vsrik/Downloads/SAP-CDS-Agent%20(3)/SAP-CDS-Agent/docs/architecture_and_deep_dive/15_IMPLEMENTATION_GAPS_AND_RISKS.md) | Tech Leads / PMs | Known gaps, single-file frontend tech debt, production hardening checklist. |

---

## 🏛️ Executive Summary

```
                      +---------------------------------------+
                      |       USER / SAP CDS DEVELOPER        |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |         REACT 18 + VITE FRONTEND      |
                      |   13-Step Human-in-the-Loop Pipeline  |
                      +---------------------------------------+
                                          |
                        HTTP / JSON (REST) via Axios
                                          v
                      +---------------------------------------+
                      |          FASTAPI PYTHON BACKEND       |
                      |         Port 8000 (CORS Enabled)      |
                      +---------------------------------------+
                       /                 |                  \
                      /                  |                   \
                     v                   v                    v
+------------------------+  +------------------------+  +------------------------+
|   LOCAL CATALOG ENGINE  |  |    AI SYNTHESIS & RULE |  |    LIVE SAP ADT REST   |
|   SQLite + FTS5 Index  |  |       VALIDATOR        |  |       CONNECTOR        |
|  - 86,296 CDS Views    |  |  - Gemini 2.5 Flash    |  |  - HTTPS Port 44301    |
|  - 1,139 Associations  |  |  - Clean Core Rules    |  |  - Zero-Write Security |
|  - 10 Business Domains |  |  - Syntax AST Linter   |  |  - Checkrun & Preview  |
+------------------------+  +------------------------+  +------------------------+
```

### Core System Invariants
1. **Zero-Write Guarantee to SAP Production**: The platform strictly enforces read-only access to SAP systems (`_assert_zero_write_policy`). DDL generation and checkruns are sandboxed.
2. **Deterministic Validation Over Hallucination**: LLM suggestions are subjected to 100% deterministic Clean Core verification, syntax parsing, and foreign key grain checks.
3. **Enterprise VDM Alignment**: Automatically classifies entities into SAP Virtual Data Model layers (`I_` Basic/Interface, `C_` Consumption, `P_` Private) and verifies naming conventions.
4. **Human-in-the-Loop Governance**: Every code artifact must traverse structured approval gates before export or transport staging.
