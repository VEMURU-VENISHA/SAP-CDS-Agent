# 14 - Technical Glossary

| Term | Definition & Enterprise Context |
|---|---|
| **ABAP** | *Advanced Business Application Programming*. SAP's proprietary high-level programming language used to build enterprise business applications on the SAP NetWeaver and S/4HANA platforms. |
| **ADT** | *ABAP Development Tools*. The official REST/HTTP-based development protocol exposed via ICF path `/sap/bc/adt` used by Eclipse and external tools to interact with the ABAP repository. |
| **AST** | *Abstract Syntax Tree*. A tree representation of the abstract syntactic structure of source code, used by `CDSGenerationValidator` and `CDSDDLParser` to validate DDL rules deterministically. |
| **BFS** | *Breadth-First Search*. A graph traversal algorithm used by `CDSDiscoveryService` to explore multi-hop association paths from a root CDS view up to 3 relationship levels away. |
| **BM25** | *Best Matching 25*. A probabilistic ranking function used by SQLite's FTS5 full-text search engine to estimate the relevance of catalog views to a given search query. |
| **CDS** | *Core Data Services*. SAP's next-generation data modeling infrastructure that defines semantically rich data models directly at the database layer in SAP HANA. |
| **Checkrun** | An in-memory syntax and semantic compilation process executed by the SAP ABAP kernel via `POST /sap/bc/adt/checkruns` without saving or persisting objects to the database. |
| **Clean Core** | SAP's modern architecture standard requiring custom extensions to be strictly decoupled from core ERP software, consuming only released APIs and CDS interface views (`I_*`). |
| **CSRF** | *Cross-Site Request Forgery*. A security mechanism where the server requires a validated token (`X-CSRF-Token`) before executing non-idempotent HTTP operations. |
| **CTS** | *Change and Transport System*. The SAP infrastructure used to manage, track, and migrate software developments and configuration changes across system landscapes (DEV $\rightarrow$ QAS $\rightarrow$ PRD). |
| **DDIC** | *Data Dictionary*. The central SAP metadata repository containing data types, domains, database tables, and view definitions. |
| **DDL** | *Data Definition Language*. The subset of SQL/CDS syntax used to define data structures (e.g. `define view entity ...`). |
| **DF14L** | Standard SAP system table that stores the hierarchy and technical definitions of Application Components (e.g. `SD`, `MM`, `FI`). |
| **FTS5** | SQLite virtual table module providing full-text search capabilities with tokenizers, stemming, and phrase matching. |
| **Grain** | The level of detail or aggregation represented by an entity (e.g., Header level vs. Item level). |
| **HITL** | *Human-in-the-Loop*. An architecture pattern ensuring that automated AI processes require human review and explicit sign-off before executing critical actions. |
| **OData** | *Open Data Protocol*. A standardized REST-based protocol used to expose SAP CDS views and business data to SAP Fiori user interfaces and external APIs. |
| **TADIR** | Standard SAP system table representing the central Object Directory, storing all development objects and their package assignments. |
| **TDEVC** | Standard SAP system table storing package (development class) definitions and hierarchies. |
| **VDM** | *Virtual Data Model*. SAP's structured architectural framework classifying CDS views into distinct layers: Basic/Interface (`I_*`), Composite, Consumption (`C_*`), and Private (`P_*`). |
| **Zero-Write Policy** | The architectural security guarantee implemented in `SAPADTClient` ensuring that the platform only performs read-only operations and never modifies live SAP systems. |
