# 05 - Data Sources & Provenance

## 1. Live SAP S/4HANA System Origin

All metadata resident in the SAP CDS Agent originates from a real SAP S/4HANA 2023 Sandbox system:

| Parameter | Configuration Value |
|---|---|
| **SAP System Host** | `YAWSS4HSBX.sapyash.com` |
| **HTTPS Port** | `44301` |
| **SAP Client** | `100` |
| **System ID (SID)** | `DEV` |
| **ABAP Release** | S/4HANA 2023 (ABAP 7.58 / 2023 Kernel) |
| **Protocol** | Native HTTPS via SAP ABAP Development Tools (ADT) REST API |

---

## 2. SAP Dictionary (DDIC) Source Tables

The catalog data stored in `backend/data/sap_cds.db` was extracted from standard SAP DDIC system tables via ADT queries:

```
+---------------------------------------------------------------------------------------+
|                               SAP S/4HANA SYSTEM TABLES                               |
+---------------------------------------------------------------------------------------+
     |                                   |                                   |
     v                                   v                                   v
+------------+                     +------------+                     +------------+
|   TADIR    |                     |   TDEVC    |                     |   DF14L    |
| Directory  |                     |  Packages  |                     | App Comps  |
+------------+                     +------------+                     +------------+
  (R3TR DDLS)                         (DEVCLASS)                        (APPL_COMP)
     \                                   |                                   /
      \                                  |                                  /
       +---------------------------------+---------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |     DD02L & DD03L DICTIONARY  |
                         |  - View Names & Metadata      |
                         |  - Field Types, Keys, Labels  |
                         +-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |      CDS DDL SOURCES & ADT    |
                         |  - Association Definitions    |
                         |  - Join Conditions & Logic    |
                         +-------------------------------+
```

1. **`TADIR` (Object Directory)**:
   * Identifies all ABAP objects of type `R3TR DDLS` (Data Definition Language Source).
   * Determines the authoritative package (`DEVCLASS`) and owner for every CDS view.
2. **`TDEVC` (Package Hierarchy)**:
   * Maps each package (`DEVCLASS`) to its parent package and software component (`DLVUNIT`).
3. **`DF14L` (Application Component Hierarchy)**:
   * Identifies the business module (e.g., `SD-MD`, `MM-PUR`, `FI-GL`) linked to each package.
4. **`DD02L` & `DD03L` (Table & Field Catalog)**:
   * `DD02L`: Provides technical names, view types, and table classifications.
   * `DD03L`: Provides technical field names (`FIELDNAME`), data types (`DATATYPE`), lengths (`LENG`), key flags (`KEYFLAG`), and text labels.
5. **CDS DDL Sources via ADT**:
   * Extracted directly from `/sap/bc/adt/ddic/ddls/sources/{cds_name}` to capture annotations (`@VDM`, `@AccessControl`), association syntax (`association [0..*] to ...`), and join criteria.

---

## 3. Domain Resolution Logic (`normalizer.py`)

A raw SAP package name like `SIMG_CFG_SD` or an application component like `SD-SLS` is not immediately human-readable. The `Normalizer` module (`backend/src/services/normalizer.py`) implements deterministic mapping from SAP metadata to **10 Standard Business Domains**:

```python
def resolve_domain_from_sap_metadata(package: str, app_component: str) -> str:
    """
    Deterministically maps SAP Package (DEVCLASS) and Application Component (DF14L)
    to one of 10 standard enterprise business domains.
    """
    pkg = (package or "").upper()
    comp = (app_component or "").upper()

    # Rule 1: Sales & Distribution
    if comp.startswith("SD") or "SD_" in pkg or pkg.startswith("VA"):
        return "SD"

    # Rule 2: Materials Management / Purchasing / Inventory
    if comp.startswith("MM") or comp.startswith("LE-TRA") or "MM_" in pkg or pkg.startswith("ME"):
        return "MM"

    # Rule 3: Financial Accounting
    if comp.startswith("FI") or "FI_" in pkg or pkg.startswith("BK"):
        return "FI"

    # Rule 4: Controlling / Management Accounting
    if comp.startswith("CO") or "CO_" in pkg:
        return "CO"

    # Rule 5: Production Planning
    if comp.startswith("PP") or "PP_" in pkg:
        return "PP"

    # Rule 6: Quality Management
    if comp.startswith("QM") or "QM_" in pkg:
        return "QM"

    # Rule 7: Plant Maintenance
    if comp.startswith("PM") or "PM_" in pkg:
        return "PM"

    # Rule 8: Human Capital Management
    if comp.startswith("PA") or comp.startswith("PY") or comp.startswith("HCM"):
        return "HCM"

    # Rule 9: Logistics Execution & Shipping
    if comp.startswith("LE") or "LE_" in pkg:
        return "LE"

    # Rule 10: SAP Basis & Architecture
    if comp.startswith("BC") or comp.startswith("BASIS") or pkg.startswith("S_"):
        return "BASIS"

    return "CROSS_FUNCTIONAL"
```

### Domain Distribution in Catalog
* **SD (Sales and Distribution)**: ~14,200 views (Sales Orders, Invoices, Deliveries, Pricing)
* **FI (Financial Accounting)**: ~18,500 views (General Ledger, AP, AR, Asset Accounting)
* **MM (Materials Management)**: ~12,300 views (Purchase Orders, Material Master, Inventory)
* **CO (Controlling)**: ~8,900 views (Cost Centers, Profit Centers, Internal Orders)
* **PP / QM / PM (Manufacturing & Maintenance)**: ~11,400 views (Work Centers, Inspection Lots, Equipment)
* **BASIS / Cross-Functional**: Remaining views (Security, Change Documents, Workflow)

---

## 4. Metadata Sync Architecture (Incremental Sync)

To keep the local catalog current without downloading all 86,296 views on every run, `CDSDiscoveryService.sync_incremental()` implements timestamp-based delta synchronization:

```
[ Local SQLite: MAX(updated_at) ]
                |
                v (Timestamp Query)
[ SAP ADT: GET /sap/bc/adt/repository/nodestructure?since=YYYYMMDDHHMMSS ]
                |
                +--> New / Modified CDS Views
                |
                v
[ Parse DDL & Update SQLite Database ]
  - INSERT OR REPLACE INTO cds_views
  - INSERT INTO cds_views_fts
  - UPDATE cds_associations
```

* **Safety & Performance**: Delta queries only fetch objects modified since the last recorded synchronization timestamp, reducing sync overhead from hours to a few seconds.
