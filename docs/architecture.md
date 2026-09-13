# Platform Architecture: SAP CDS Intelligence & Automation

This document details the architectural principles, domain abstractions, multi-agent orchestration, and governance models of the **SAP CDS Intelligence & Automation Platform**.

---

## 1. Architectural Principles

1. **Clean Core & VDM First:**
   Favor reusing standard SAP Virtual Data Model (VDM) CDS views over creating bespoke tables or redundant views.
2. **Determinism Before Generation:**
   Before any ABAP code is drafted, the platform runs semantic mapping and decision scoring to evaluate feasibility.
3. **Defense in Depth & Zero Secrets:**
   No production or DEV secrets are stored in the platform. Connectors accept ephemeral session tokens or OAuth 2.0 mTLS certificates during live invocation.
4. **Auditability by Design:**
   Every recommendation, field mapping, score, and human sign-off is persisted in an immutable audit ledger.

---

## 2. Decision Logic Matrix: REUSE vs EXTEND vs CREATE

The platform categorizes incoming requirements against discovered SAP S/4HANA CDS views using the following deterministic threshold matrix:

| Metric / Criterion | REUSE | EXTEND | CREATE |
| :--- | :--- | :--- | :--- |
| **Field Coverage** | \(\ge 95\%\) of requested fields exist | \(70\% - 94\%\) exist or are joinable via standard associations | \(< 70\%\) covered |
| **Granularity / Grain** | Exact match with business entity key | Exact match or compatible via extension | Incompatible grain or disparate aggregate |
| **Clean-Core Impact** | **Zero footprint** (consumes standard CDS) | **Non-intrusive extension** (`EXTEND VIEW ENTITY`) | **New custom object** (`Z_*` or custom namespace) |
| **Recommended Artifact**| Analytical / transactional consumption | CDS View Entity Extension with join/fields | Brand-new Composite or Consumption CDS View |
| **Maintenance Burden**  | Zero (maintained by SAP S/4HANA release) | Minimal (upgrade-safe extension points) | Full customer lifecycle ownership |

---

## 3. Multi-Agent Pipeline & Responsibilities

The agent pipeline operates as a directed state graph via **LangGraph**:

```
[Business Requirement]
         |
         v
+-------------------------------+
|     Requirement Agent         | -> Parses NL, extracts domain, entities, fields, filters
+-------------------------------+
         |
         v
+-------------------------------+
|     SAP Discovery Agent       | -> Queries CDS catalog/VDM via ISAPConnector
+-------------------------------+
         |
         v
+-------------------------------+
|   Semantic Mapping Agent      | -> Maps required fields to CDS attributes & associations
+-------------------------------+
         |
         v
+-------------------------------+
|       Decision Agent          | -> Computes coverage score -> decides REUSE / EXTEND / CREATE
+-------------------------------+
         |
         +---------------------------------------+
         |                                       |
    (If REUSE)                               (If EXTEND or CREATE)
         |                                       v
         |                         +-------------------------------+
         |                         |      Data Model Agent         | -> Designs entity associations & keys
         |                         +-------------------------------+
         |                                       |
         |                                       v
         |                         +-------------------------------+
         |                         |    CDS Generator Agent        | -> Drafts clean ABAP CDS DDL syntax
         |                         +-------------------------------+
         |                                       |
         |                                       v
         |                         +-------------------------------+
         |                         |     Validation Agent          | -> Checks SAP syntax, naming, rules
         |                         +-------------------------------+
         |                                       |
         +-------------------+-------------------+
                             |
                             v
               +-------------------------------+
               |   Security & Governance Agent | -> HUMAN APPROVAL GATE (Sign-off & TR assignment)
               +-------------------------------+
                             |
                             v
               +-------------------------------+
               |     Impact & Audit Agent      | -> Calculates blast radius, updates audit ledger
               +-------------------------------+
```

---

## 4. SAP Connector Layer (`ISAPConnector`)

The connector layer isolates the platform from the physical transport layer. In Milestone 1, this layer is defined as an abstract interface. In future milestones, it connects to:
- **SAP ADT (ABAP Development Tools) REST APIs** for CDS discovery, DDL draft submission, syntax check, and activation.
- **SAP RFC / OData** for data dictionary inspection (`DDLS`, `DD26S`, `RODPS_REPL`).

Crucially, the connector enforces **zero mock contamination**: if the connection is unconfigured or offline, it raises typed errors rather than synthesizing counterfeit metadata.
