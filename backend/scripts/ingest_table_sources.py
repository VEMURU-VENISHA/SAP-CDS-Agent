"""Ingest and link SAP transparent tables to CDS views from live SAP S/4HANA ADT.

Extracts:
1. Base source ('as select from <TABLE>') -> Populates cds_views.parent_name
2. Joined tables ('join <TABLE>') -> Populates cds_joins
3. Associations ('association to <VIEW>') -> Populates cds_associations
4. Stores full DDL source in cds_views.source_code
"""

import asyncio
import os
from pathlib import Path
import sqlite3
import sys

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from src.sap.adt_client import SAPADTClient
from src.sap.parser import CDSDDLParser
from src.logging_config import logger

# Authoritative standard SAP S/4HANA views covering core enterprise tables:
# MARA, MAKT, MARC, MARD, ACDOCA, BKPF, BSEG, VBAK, VBAP, VBRK, VBRP, EKKO, EKPO, KNA1, LFA1, BUT000
TARGET_VIEWS = [
    # Materials / Products (MARA, MAKT, MARC, MARD, MBEW)
    "I_PRODUCT",
    "I_MATERIAL",
    "I_PRODUCTDESCRIPTION",
    "I_MATERIALTEXT",
    "I_PRODUCTPLANT",
    "I_MATERIALPLANT",
    "I_PRODUCTVALUATION",
    
    # Financials & Universal Journal (ACDOCA, BKPF, BSEG, SKA1)
    "P_ACDOCA",
    "I_GLACCOUNTLINEITEMRAWDATA",
    "I_JOURNALENTRYITEM",
    "I_JOURNALENTRY",
    "I_OPERATIONALACCTGDOCITEM",
    "I_GLACCOUNT",
    
    # Sales & Distribution (VBAK, VBAP, VBKD, VBRK, VBRP, LIKP, LIPS)
    "I_SALESDOCUMENTBASIC",
    "I_SALESDOCUMENT",
    "I_SALESORDER",
    "I_SALESORDERITEM",
    "I_BILLINGDOCUMENT",
    "I_BILLINGDOCUMENTITEM",
    "I_DELIVERYDOCUMENT",
    "I_DELIVERYDOCUMENTITEM",
    "I_SALESDOCUMENTSCHEDULELINE",
    
    # Sourcing & Procurement (EKKO, EKPO)
    "R_PURCHASINGDOCUMENT",
    "R_PURCHASEORDER",
    "I_PURCHASEORDERAPI01",
    "I_PURCHASEORDERITEMAPI01",
    
    # Customer Master (KNA1, KNVV, KNVP)
    "I_CUSTOMER",
    "I_CUSTOMERSALESAREA",
    "I_CUSTOMERCOMPANY",
    
    # Supplier Master (LFA1, LFB1, LFM1)
    "I_SUPPLIER",
    "I_SUPPLIERCOMPANY",
    "I_SUPPLIERPURCHASINGORG",
    
    # Business Partner (BUT000)
    "I_BUSINESSPARTNER",
]

DB_PATH = BACKEND_DIR / "data" / "sap_cds.db"


async def main():
    print(f"Connecting to database at {DB_PATH}...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    client = SAPADTClient()
    print("Verifying live SAP ADT connection...")
    token = await client.fetch_csrf_token()
    if not token:
        print("ERROR: Could not fetch CSRF token from SAP ADT. Aborting.")
        return

    print(f"SAP ADT connected. Ingesting sources for {len(TARGET_VIEWS)} standard views...\n")

    success_count = 0
    tables_found = set()

    for view_name in TARGET_VIEWS:
        try:
            print(f"Fetching DDL for {view_name}...", end=" ", flush=True)
            ddl_source = await client.get_ddl_source(view_name)
            if not ddl_source:
                print("EMPTY DDL")
                continue

            # Extract base sources, joins, and associations using CDSDDLParser
            sources = CDSDDLParser.extract_sources(ddl_source)
            assocs = CDSDDLParser.extract_associations(ddl_source)

            primary_parent = sources[0].upper() if sources else None
            if primary_parent:
                tables_found.add(primary_parent)

            # Update cds_views with parent_name and source_code
            c.execute(
                """
                UPDATE cds_views 
                SET parent_name = ?, source_code = ? 
                WHERE UPPER(cds_name) = ?
                """,
                (primary_parent, ddl_source, view_name.upper()),
            )

            # If this view wasn't already in cds_views, insert it
            if c.rowcount == 0:
                c.execute(
                    """
                    INSERT OR IGNORE INTO cds_views (cds_name, label, parent_name, source_code, source_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (view_name, view_name, primary_parent, ddl_source, "CDS View Entity"),
                )

            # Ingest joined tables into cds_joins
            if len(sources) > 1:
                for joined_src in sources[1:]:
                    joined_u = joined_src.upper()
                    tables_found.add(joined_u)
                    c.execute(
                        """
                        INSERT OR REPLACE INTO cds_joins 
                        (left_entity, right_entity, join_type, source_evidence)
                        VALUES (?, ?, ?, ?)
                        """,
                        (view_name, joined_u, "LEFT OUTER JOIN", "ADT_DDL_PARSER"),
                    )

            # Ingest associations into cds_associations
            for alias, target, card, on_cond in assocs:
                c.execute(
                    """
                    INSERT OR REPLACE INTO cds_associations
                    (cds_name, target_entity, association_name, cardinality, on_condition)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (view_name, target, alias, card, on_cond),
                )

            conn.commit()
            success_count += 1
            print(f"OK (Primary Source: {primary_parent}, Joined: {sources[1:]}, Assocs: {len(assocs)})")

        except Exception as e:
            print(f"FAILED: {e}")

    conn.close()

    print(f"\n==========================================")
    print(f"Ingestion Complete!")
    print(f"Successfully processed: {success_count}/{len(TARGET_VIEWS)} views")
    print(f"Unique tables & sources extracted: {sorted(tables_found)}")
    print(f"==========================================")


if __name__ == "__main__":
    asyncio.run(main())
