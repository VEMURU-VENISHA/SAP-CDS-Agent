import py_compile
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
gemini_file = backend_dir / "src" / "services" / "gemini_service.py"
main_file = backend_dir / "src" / "main.py"
output_file = backend_dir / "scripts" / "compile_results.txt"

results = []

def check_file(filepath):
    results.append(f"Checking {filepath}...")
    try:
        py_compile.compile(str(filepath), doraise=True)
        results.append(f"  [SUCCESS] {filepath.name} compiled cleanly.")
    except Exception as e:
        results.append(f"  [FAILED] {filepath.name} compilation error: {e}")

check_file(gemini_file)
check_file(main_file)

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(results))

print("Compilation results saved to compile_results.txt")
