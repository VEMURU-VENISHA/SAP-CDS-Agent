# 01 - Project Overview

## 1. What Problem Does This Project Solve?

### The Beginner-Friendly Explanation
Imagine walking into a massive library containing **86,296 books** (called "CDS Views"). Each book represents a business concept in a company—such as sales orders, customer invoices, warehouse inventory, or employee payroll. 

When an SAP developer or business analyst needs to create a new report or API (like "Show me all overdue customer invoices with shipping addresses and product categories"), they face severe challenges:
1. **Finding the right data**: Which of the 86,296 views contains the true, authoritative invoice data? Is it `I_BillingDocumentItem`, `VBRK`, or an obsolete compatibility view?
2. **Connecting the data correctly**: How do you connect sales invoices to shipping addresses without creating duplicate rows or crashing the database? In SAP, you must use predefined "Associations" rather than guessing database joins.
3. **Writing complex code**: SAP Core Data Services (CDS) Data Definition Language (DDL) requires dozens of specialized annotations (`@VDM.viewType`, `@AccessControl.authorizationCheck`, `@EndUserText.label`, `@Semantics.amount.currencyCode`). A single missing annotation or incorrect syntax breaks the build.
4. **Clean Core Compliance**: Modern SAP S/4HANA systems strictly forbid direct modifications or direct access to low-level internal tables. Developers must use released SAP standard interface views (`I_*`).

**The SAP CDS Agent solves this entirely.** A developer simply types a natural language request (e.g., *"Create a CDS view for open sales orders with customer credit limit and delivery status"*). The platform parses the request, searches the local 86,296-view catalog using full-text indexing, traverses real SAP associations up to 3 hops away, generates valid ABAP CDS DDL code using Google Gemini LLM, deterministically validates it against Clean Core rules, tests it against live SAP systems without writing data, and enforces human-in-the-loop review before deployment.

---

## 2. Enterprise Context & The "Clean Core" Paradigm

In traditional SAP ECC systems, developers frequently modified standard tables or wrote custom ABAP reports directly querying internal database tables (`VBAK`, `VBAP`, `MARA`). This created massive technical debt, making system upgrades expensive and time-consuming.

In **SAP S/4HANA**, SAP introduced:
* **The Virtual Data Model (VDM)**: A standardized, layered architecture of CDS views:
  * **Basic / Interface Views (`I_*`)**: Core business entities (e.g., `I_SalesOrder`, `I_Customer`), reusable, public, and stable.
  * **Composite Views (`I_*`)**: Cross-functional views joining multiple basic views.
  * **Consumption Views (`C_*`)**: Specialized analytical or transactional views exposed directly to SAP Fiori or OData.
  * **Private Views (`P_*`)**: Internal implementation details not released for custom extension.
* **Clean Core Extensibility**: Custom extensions must **never** touch internal database tables directly. They must use released SAP API CDS views (`I_*`), adhere to customer naming conventions (`Z*` or `Y*`), and preserve standard authorization checks.

The **SAP CDS Agent** acts as an intelligent enterprise copilot that guarantees every generated CDS view strictly adheres to Clean Core standards, selects valid released interface views, and generates production-ready DDL.

---

## 3. Quantitative Codebase & Catalog Metrics

| Metric | Measured Value | Significance |
|---|---|---|
| **Cataloged CDS Views** | **86,296** views | Full live metadata snapshot from SAP S/4HANA 2023. |
| **Search Index (FTS5)** | **86,296** entries | SQLite Full-Text Search index for sub-millisecond keyword lookup. |
| **Cataloged Packages** | **3,681** ABAP packages | Categorized by module and application layer. |
| **Application Components** | **928** components | Spanning SD, MM, FI, CO, PP, QM, PM, HCM, and Basis. |
| **Indexed Field Definitions** | **212** views | Detailed field schemas with data types, keys, and labels. |
| **Pre-Mapped Associations** | **1,139** associations | Official SAP semantic relationships across views. |
| **Verified Joins** | **41** joins | Deterministic join paths between standard entities. |
| **Automated Test Suite** | **311 passing tests** | 0 failures, 6 skipped across 28 test modules. |
| **Backend Codebase** | **25 Python modules** | ~10,500 lines of robust, type-annotated Python. |
| **Frontend Codebase** | **React 18 + Vite** | Single-page interactive 13-stage HITL pipeline. |

---

## 4. Key Value Propositions

1. **Dramatic Cycle Time Reduction**: Reduces CDS view design, field discovery, association resolution, and DDL authoring from **4–6 hours** to **under 2 minutes**.
2. **Guaranteed Clean Core Compliance**: Built-in deterministic validation engines reject legacy table queries and enforce `Z*`/`Y*` namespaces, `@VDM` annotations, and key preservation.
3. **Zero-Write Safety Perimeter**: Built-in HTTP interception ensures that interactions with live SAP systems remain 100% read-only (`GET` and sandboxed checkruns). No unauthorized database writes can ever reach the SAP S/4HANA system.
4. **Human-in-the-Loop (HITL) Governance**: Unlike black-box AI tools, every pipeline step is inspectable, editable, and gate-kept. Generated DDL requires multi-role approval (Developer, Architect, Security) before transport staging.
