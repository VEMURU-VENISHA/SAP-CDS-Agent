import asyncio
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
import sys

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from src.config import get_settings
from src.sap.adt_client import SAPADTClient


async def test_enrichment():
    db_path = backend_dir / "data" / "sap_cds.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT package FROM cds_views WHERE package NOT IN ('SAP_STANDARD', 'CUSTOM_DEV', '') AND package IS NOT NULL"
    )
    pkgs = [r[0] for r in c.fetchall()]
    print(f"Distinct authentic packages in SQLite: {len(pkgs)}")

    settings = get_settings()
    client = SAPADTClient(settings)
    hc = await client._get_client()
    headers = client._get_auth_headers()
    headers["Accept"] = "application/xml, text/xml, */*"

    resolved = 0
    for pkg in pkgs[:20]:
        try:
            resp = await hc.get(f"/sap/bc/adt/packages/{pkg.lower()}", headers=headers)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                comp = ""
                desc = ""
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if tag == "applicationComponent":
                        comp = el.attrib.get("name") or el.attrib.get(
                            "{http://www.sap.com/adt/packages}name", ""
                        )
                        desc = el.attrib.get("description") or el.attrib.get(
                            "{http://www.sap.com/adt/packages}description", ""
                        )
                print(f"Package: {pkg:28} -> AppComp: {comp:18} ({desc})")
                resolved += 1
            else:
                print(f"Package: {pkg:28} -> HTTP {resp.status_code}")
        except Exception as e:
            print(f"Package: {pkg:28} -> Error: {e}")

    print(f"\nResolved {resolved}/20 sample packages successfully!")
    conn.close()


if __name__ == "__main__":
    asyncio.run(test_enrichment())
