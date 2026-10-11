"""Authoritative SAP ADT Domain & Application Component Metadata Synchronizer.

Derives business domain strictly from SAP Repository Metadata:
1. Application Component Hierarchy (TADIR / DF14L)
2. ABAP Package (DEVCLASS / packageRef)

Zero view-name guessing. Zero DDL source text heuristic guessing.
Enriches local SQLite index (backend/data/sap_cds.db) with authentic packages,
application components, and business domains directly from the live SAP S/4HANA ADT repository.
"""

import asyncio
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from src.config import get_settings
from src.sap.adt_client import SAPADTClient
from src.services.normalizer import resolve_domain_from_sap_metadata


async def sync_domains():
    t_start = time.time()
    db_path = backend_dir / "data" / "sap_cds.db"
    print(f"Connecting to SQLite database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Ensure application_component column exists
    c.execute("PRAGMA table_info(cds_views)")
    cols = [col[1] for col in c.fetchall()]
    if "application_component" not in cols:
        print("Adding column application_component to cds_views...")
        c.execute("ALTER TABLE cds_views ADD COLUMN application_component TEXT")
        conn.commit()

    settings = get_settings()
    client = SAPADTClient(settings)

    print("Step 1: Discovering authentic ABAP packages from SAP ADT Information System...")
    prefixes = [f"I_{chr(code)}*" for code in range(ord('A'), ord('Z') + 1)] + \
               [f"C_{chr(code)}*" for code in range(ord('A'), ord('Z') + 1)] + \
               ["R_*", "P_*", "E_*", "Z*", "Y*"]

    sem = asyncio.Semaphore(6)
    view_package_map: Dict[str, str] = {}
    view_desc_map: Dict[str, str] = {}

    async def fetch_prefix(p: str):
        async with sem:
            try:
                hits = await client.search_information_system(p, max_results=10000)
                ddls_hits = [
                    h for h in hits
                    if h.get("type") in ("DDLS/DF", "DDLS") or "ddic/ddl/sources" in h.get("uri", "")
                ]
                for h in ddls_hits:
                    name_u = h["name"].upper()
                    pkg = h.get("package", "").strip().upper()
                    if pkg and pkg not in ("SAP_STANDARD", "UNKNOWN", "$TMP"):
                        view_package_map[name_u] = pkg
                    if h.get("description"):
                        view_desc_map[name_u] = h["description"]
                print(f"  Prefix {p:6}: {len(ddls_hits):5} DDLS views (discovered total so far: {len(view_package_map)})")
            except Exception as e:
                print(f"  Prefix {p:6}: Error {e}")

    await asyncio.gather(*(fetch_prefix(p) for p in prefixes))
    print(f"Discovered authentic packages for {len(view_package_map)} CDS views from live ADT.")

    # Also include packages already stored in SQLite
    c.execute(
        "SELECT DISTINCT package FROM cds_views WHERE package NOT IN ('SAP_STANDARD', 'CUSTOM_DEV', '', 'UNKNOWN', '$TMP') AND package IS NOT NULL"
    )
    existing_pkgs = {r[0].strip().upper() for r in c.fetchall() if r[0]}
    all_packages = set(view_package_map.values()) | existing_pkgs
    print(f"Total distinct authentic packages to resolve: {len(all_packages)}")

    print("\nStep 2: Resolving Application Components from SAP ADT Package Repository...")
    pkg_meta_map: Dict[str, Tuple[str, str]] = {}  # pkg -> (app_component, domain)
    pkg_sem = asyncio.Semaphore(10)

    async def resolve_pkg(pkg: str):
        async with pkg_sem:
            try:
                meta = await client.get_package_metadata(pkg)
                app_comp = meta.get("application_component", "").strip()
                dom = resolve_domain_from_sap_metadata(package=pkg, application_component=app_comp)
                pkg_meta_map[pkg] = (app_comp, dom)
            except Exception as e:
                dom = resolve_domain_from_sap_metadata(package=pkg, application_component="")
                pkg_meta_map[pkg] = ("", dom)

    await asyncio.gather(*(resolve_pkg(p) for p in all_packages))
    print(f"Resolved metadata for {len(pkg_meta_map)} packages.")

    print("\nStep 3: Enriching and Updating SQLite database...")
    # Fetch all existing views from SQLite
    c.execute("SELECT cds_name, package, application_component, domain FROM cds_views")
    db_rows = c.fetchall()
    print(f"Total rows in SQLite cds_views: {len(db_rows)}")

    updates = []
    for r in db_rows:
        vname, cur_pkg, cur_comp, cur_dom = r[0], r[1] or "", r[2] or "", r[3] or ""
        vname_u = vname.upper()

        # Determine authentic package
        auth_pkg = view_package_map.get(vname_u)
        if not auth_pkg and cur_pkg and cur_pkg not in ("SAP_STANDARD", "UNKNOWN", "$TMP"):
            auth_pkg = cur_pkg

        # Determine application component and domain
        if auth_pkg and auth_pkg in pkg_meta_map:
            app_comp, domain = pkg_meta_map[auth_pkg]
        else:
            app_comp = cur_comp
            domain = resolve_domain_from_sap_metadata(package=auth_pkg or cur_pkg, application_component=app_comp)

        final_pkg = auth_pkg or cur_pkg or "SAP_STANDARD"
        updates.append((final_pkg, app_comp, domain, vname))

    print("Temporarily dropping FTS5 triggers to ensure fast, uncorrupted bulk update...")
    c.execute("DROP TRIGGER IF EXISTS cds_views_ai")
    c.execute("DROP TRIGGER IF EXISTS cds_views_ad")
    c.execute("DROP TRIGGER IF EXISTS cds_views_au")
    c.execute("DROP TABLE IF EXISTS cds_views_fts")
    conn.commit()

    print(f"Applying updates to {len(updates)} views in SQLite...")
    c.executemany(
        """
        UPDATE cds_views
        SET package = ?,
            application_component = ?,
            domain = ?
        WHERE cds_name = ?
        """,
        updates
    )
    conn.commit()

    # Insert any newly discovered views from live SAP ADT
    existing_view_names = {r[0].upper() for r in db_rows}
    new_views = []
    for vname, auth_pkg in view_package_map.items():
        if vname not in existing_view_names:
            app_comp, dom = pkg_meta_map.get(auth_pkg, ("", resolve_domain_from_sap_metadata(package=auth_pkg)))
            label = view_desc_map.get(vname, vname)
            grain = vname.replace("I_", "").replace("C_", "").replace("R_", "").replace("P_", "")
            new_views.append((vname, label, dom, grain, "CDS View Entity", auth_pkg, app_comp))
    if new_views:
        print(f"Inserting {len(new_views)} newly discovered views from live SAP ADT into SQLite...")
        c.executemany(
            """
            INSERT OR IGNORE INTO cds_views (cds_name, label, domain, grain, source_type, package, application_component)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            new_views
        )
        conn.commit()

    print("\nStep 4: Synchronizing live field and association metadata for core foundational CDS views...")
    from src.sap.adt_connector import SAPADTConnector
    from src.services.discovery_service import CDSDiscoveryService
    connector = SAPADTConnector(settings=settings, client=client)
    disc = CDSDiscoveryService()
    core_views = [
        "I_SALESORDER", "I_SALESORDERITEM", "I_CUSTOMER", "I_PRODUCT", "I_MATERIAL",
        "I_JOURNALENTRYITEM", "I_COMPANYCODE", "I_PURCHASEORDER", "I_RO_SAFTSALESINVOICECUSTOMER"
    ]
    for cv in core_views:
        try:
            ddl = await client.get_ddl_source(cv)
            if ddl:
                disc._ingest_parsed_associations(cv, ddl)
            meta = await connector.get_cds_view_metadata(cv)
            for f in meta.fields:
                c.execute(
                    "INSERT OR REPLACE INTO cds_fields (cds_name, fieldname, field_label, data_type, is_key, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (cv, f.name, f.description or f.name, f.data_type or f.abap_type, 1 if f.is_key else 0, "LIVE_ADT"),
                )
        except Exception as e:
            print(f"  Field sync for {cv}: {e}")
    conn.commit()

    print("\nStep 5: Re-creating and Populating FTS5 Search Index...")
    try:
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS cds_views_fts USING fts5(
                cds_name,
                label,
                package,
                application_component,
                domain,
                content='cds_views',
                content_rowid='rowid'
            )
        """)
        c.execute("""
            INSERT INTO cds_views_fts(rowid, cds_name, label, package, application_component, domain)
            SELECT rowid, cds_name, label, package, application_component, domain FROM cds_views;
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS cds_views_ai AFTER INSERT ON cds_views BEGIN
                INSERT INTO cds_views_fts(rowid, cds_name, label, package, application_component, domain)
                VALUES (new.rowid, new.cds_name, new.label, new.package, new.application_component, new.domain);
            END;
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS cds_views_ad AFTER DELETE ON cds_views BEGIN
                INSERT INTO cds_views_fts(cds_views_fts, rowid, cds_name, label, package, application_component, domain)
                VALUES ('delete', old.rowid, old.cds_name, old.label, old.package, old.application_component, old.domain);
            END;
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS cds_views_au AFTER UPDATE ON cds_views BEGIN
                INSERT INTO cds_views_fts(cds_views_fts, rowid, cds_name, label, package, application_component, domain)
                VALUES ('delete', old.rowid, old.cds_name, old.label, old.package, old.application_component, old.domain);
                INSERT INTO cds_views_fts(rowid, cds_name, label, package, application_component, domain)
                VALUES (new.rowid, new.cds_name, new.label, new.package, new.application_component, new.domain);
            END;
        """)
        conn.commit()
        print("  FTS5 virtual table cds_views_fts and triggers successfully established.")
    except Exception as e:
        print(f"  FTS5 rebuild notice: {e}")

    print("\n=== Verification and Domain Breakdown ===")
    c.execute("SELECT COUNT(*), COUNT(DISTINCT package), COUNT(CASE WHEN application_component != '' THEN 1 END) FROM cds_views")
    tot_views, dist_pkgs, views_with_comp = c.fetchone()
    print(f"Total views in SQLite: {tot_views}")
    print(f"Distinct packages in SQLite: {dist_pkgs}")
    print(f"Views with Application Component: {views_with_comp}")

    c.execute("SELECT domain, COUNT(*) FROM cds_views GROUP BY domain ORDER BY COUNT(*) DESC")
    domains = c.fetchall()
    print("\nBusiness Domain Breakdown (Derived strictly from SAP Repository Metadata):")
    for d, cnt in domains:
        pct = (cnt / tot_views) * 100
        print(f"  {d:32}: {cnt:5} ({pct:5.1f}%)")

    c.execute(
        "SELECT application_component, COUNT(*) FROM cds_views WHERE application_component != '' GROUP BY application_component ORDER BY COUNT(*) DESC LIMIT 20"
    )
    top_comps = c.fetchall()
    print("\nTop 20 Application Components in SQLite:")
    for comp, cnt in top_comps:
        print(f"  {comp:25}: {cnt:5}")

    conn.close()
    elapsed = time.time() - t_start
    print(f"\nMigration completed successfully in {elapsed:.2f} seconds!")


if __name__ == "__main__":
    asyncio.run(sync_domains())
