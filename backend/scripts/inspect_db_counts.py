import sqlite3
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
data_db = backend_dir / "data" / "sap_cds.db"
platform_db = backend_dir / "platform_data.db"
output_file = backend_dir / "scripts" / "db_inspection_results.txt"

lines = []

def inspect(db_path, label):
    lines.append(f"=== Inspecting {label} ({db_path}) ===")
    if not db_path.exists():
        lines.append("  FILE DOES NOT EXIST!")
        return
    lines.append(f"  File size: {db_path.stat().st_size} bytes")
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in c.fetchall()]
        lines.append(f"  Tables: {tables}")
        for t in tables:
            try:
                c.execute(f"SELECT COUNT(*) FROM {t}")
                cnt = c.fetchone()[0]
                lines.append(f"    Table '{t}': {cnt} rows")
            except Exception as e:
                lines.append(f"    Table '{t}': error {e}")
        conn.close()
    except Exception as e:
        lines.append(f"  Error inspecting DB: {e}")

inspect(data_db, "backend/data/sap_cds.db")
lines.append("")
inspect(platform_db, "backend/platform_data.db")

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("Wrote results to db_inspection_results.txt")
