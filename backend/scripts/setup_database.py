"""One-Command Database Initialization & Health Setup.

Usage on any new laptop or environment:
    python backend/scripts/setup_database.py

Behavior:
1. If 'backend/data/sap_cds.db' is missing, it decompresses 'sap_cds.db.gz' in ~1.5s.
2. If neither exists, it connects to live SAP ADT to initialize from scratch.
3. Runs database integrity verification and FTS5 search validation.
"""

import gzip
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "sap_cds.db"
GZ_PATH = DATA_DIR / "sap_cds.db.gz"


def setup_database(force_repack: bool = False):
    print("=================================================================")
    print("       SAP CDS Agent: Automated Database Setup & Integrity       ")
    print("=================================================================")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # Step 1: Ensure database exists
    if not DB_PATH.exists() or force_repack:
        if GZ_PATH.exists():
            print(f"Found compressed catalog seed: {GZ_PATH.name} ({GZ_PATH.stat().st_size / (1024*1024):.2f} MB)")
            print(f"Decompressing catalog to {DB_PATH.name}...", end=" ", flush=True)
            with gzip.open(GZ_PATH, "rb") as f_in:
                with open(DB_PATH, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            dt = time.time() - t0
            print(f"DONE in {dt:.2f}s! ({DB_PATH.stat().st_size / (1024*1024):.2f} MB)")
        else:
            print("No local seed found. Running live SAP ADT synchronization...")
            import subprocess
            subprocess.run([sys.executable, str(BACKEND_DIR / "scripts" / "sync_adt_domains.py")], check=True)
            subprocess.run([sys.executable, str(BACKEND_DIR / "scripts" / "ingest_table_sources.py")], check=True)

    # Step 2: Database Integrity Check
    print("\nVerifying database schema and record counts...")
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute("PRAGMA quick_check")
    quick_check = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM cds_views")
    view_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM cds_views WHERE parent_name IS NOT NULL AND parent_name != ''")
    parent_count = c.fetchone()[0]

    try:
        c.execute("SELECT COUNT(*) FROM cds_associations")
        assoc_count = c.fetchone()[0]
    except Exception:
        assoc_count = 0

    try:
        c.execute("SELECT COUNT(*) FROM cds_joins")
        join_count = c.fetchone()[0]
    except Exception:
        join_count = 0

    # Step 3: Test FTS5 Search Speed
    t_search = time.time()
    c.execute("SELECT cds_name, label FROM cds_views_fts WHERE cds_views_fts MATCH 'sales order' LIMIT 5")
    sample_fts = c.fetchall()
    fts_latency_ms = (time.time() - t_search) * 1000

    conn.close()

    print(f" -> SQLite Quick Check:           {quick_check.upper()}")
    print(f" -> Total Cataloged CDS Views:    {view_count:,}")
    print(f" -> Views with Table Provenance:  {parent_count:,}")
    print(f" -> Indexed Associations:         {assoc_count:,}")
    print(f" -> Verified Joins:               {join_count:,}")
    print(f" -> FTS5 Full-Text Search Test:   {len(sample_fts)} results in {fts_latency_ms:.2f} ms")

def pack_database():
    """Optimizes, vacuums, and compresses sap_cds.db into sap_cds.db.gz for Git tracking."""
    print("=================================================================")
    print("       SAP CDS Agent: Packing SQLite Database into sap_cds.db.gz  ")
    print("=================================================================")
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} does not exist. Cannot pack.")
        sys.exit(1)

    print(f"1. Checkpointing WAL and optimizing {DB_PATH.name}...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.close()

    orig_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"   Database optimized: {orig_size_mb:.2f} MB")

    print(f"2. Compressing {DB_PATH.name} -> {GZ_PATH.name} (gzip)...", end=" ", flush=True)
    t0 = time.time()
    with open(DB_PATH, "rb") as f_in:
        with gzip.open(GZ_PATH, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    dt = time.time() - t0
    gz_size_mb = GZ_PATH.stat().st_size / (1024 * 1024)
    print(f"DONE in {dt:.2f}s!")
    print(f"   Compressed seed: {gz_size_mb:.2f} MB (Reduced by {100 - (gz_size_mb/orig_size_mb*100):.1f}%)")
    print("\nSUCCESS: 'backend/data/sap_cds.db.gz' is ready to be committed to Git.")


if __name__ == "__main__":
    if "--pack" in sys.argv or "--compress" in sys.argv:
        pack_database()
    else:
        force = "--force" in sys.argv
        setup_database(force_repack=force)
