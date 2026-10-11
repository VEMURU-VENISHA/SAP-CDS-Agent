import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parent.parent / "data" / "sap_cds.db"
conn = sqlite3.connect(str(db_path))
c = conn.cursor()
c.execute("SELECT DISTINCT package FROM cds_views WHERE package IS NOT NULL AND package != ''")
pkgs = [r[0] for r in c.fetchall()]
print(f"Total distinct packages: {len(pkgs)}")
print("Sample packages:")
for p in pkgs[:35]:
    print(f"  {p}")

c.execute("SELECT COUNT(*), package FROM cds_views GROUP BY package ORDER BY COUNT(*) DESC LIMIT 20")
print("\nTop 20 packages by view count:")
for cnt, pkg in c.fetchall():
    print(f"  {pkg}: {cnt}")

conn.close()
