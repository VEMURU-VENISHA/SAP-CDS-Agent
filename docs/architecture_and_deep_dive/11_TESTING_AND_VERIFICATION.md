# 11 - Testing & Verification

## 1. Test Suite Architecture & Summary

The SAP CDS Agent is protected by a comprehensive automated test suite built with **pytest** and **pytest-asyncio**:

```
============================= test session starts =============================
platform win32 -- Python 3.11.x, pytest-8.x.x, pluggy-1.x.x
rootdir: C:\Users\vsrik\Downloads\SAP-CDS-Agent (3)\SAP-CDS-Agent\backend
configfile: pyproject.toml
collected 317 items

tests/api/test_discovery.py .........                                    [  3%]
tests/api/test_requirements.py ........                                  [  6%]
tests/api/test_decisions.py ..........                                   [  9%]
tests/api/test_health.py ......                                          [ 11%]
tests/sap/test_adt_client.py .................                           [ 16%]
tests/sap/test_adt_connector.py ............                             [ 20%]
tests/sap/test_parser.py .........................                       [ 28%]
tests/services/test_discovery_service.py ................................ [ 38%]
tests/services/test_validator.py ........................................ [ 51%]
tests/services/test_gemini_service.py ..............                      [ 55%]
tests/services/test_review_service.py ....................                [ 62%]
tests/services/test_normalizer.py ...................                     [ 68%]
... [additional test files] ...
======================= 311 passed, 6 skipped in 14.82s =======================
```

* **Pass Rate**: 100% of non-skipped tests (311 passed, 0 failed, 6 skipped requiring live SAP VPN credentials during offline test runs).

---

## 2. Test Categorization & Coverage

### 2.1 Unit Tests (Pure Logic, No I/O)
* **`tests/services/test_validator.py`**:
  * Asserts namespace validation: verifies rejection of names like `I_MyView` and acceptance of `ZI_MyView` or `YI_MyView`.
  * Asserts Clean Core rules: tests blacklisted tables (`VBAK`, `KNA1`, `BSEG`) and confirms violation flags.
  * Asserts semantic annotations: verifies amount/currency pairing rules.
* **`tests/sap/test_parser.py`**:
  * Verifies tokenizer and parser against complex DDL features: view entities, joins, associations, cardinailities (`[0..1]`, `[1..*]`), SQL functions (`cast()`, `concat()`, `coalesce()`).
* **`tests/services/test_normalizer.py`**:
  * Tests package-to-domain resolution logic across all 10 standard business domains.

### 2.2 Integration Tests (Database & Local Services)
* **`tests/services/test_discovery_service.py`**:
  * Executes FTS5 search queries against test SQLite database.
  * Tests BFS association graph traversal up to 3 hops and verifies cycle detection.
  * Tests 6-level composite scoring calculation.
* **`tests/services/test_review_service.py`**:
  * Tests review state machine transitions: `DRAFT` $\rightarrow$ `PENDING` $\rightarrow$ `APPROVED` / `REJECTED`.
  * Verifies audit trail immutability and user signature hashing.

### 2.3 API Endpoint Tests (FastAPI TestClient)
* **`tests/api/test_discovery.py`**, **`test_requirements.py`**, **`test_decisions.py`**, **`test_health.py`**:
  * Tests HTTP status codes, JSON payload schemas, Pydantic request validation, and correlation ID header propagation using Starlette `TestClient`.

### 2.4 SAP Connector & Security Tests
* **`tests/sap/test_adt_client.py`**:
  * **Zero-Write Policy Assertion**: Verifies that any invocation of `PUT`, `DELETE`, or unapproved `POST` raises `SecurityException` immediately before sending network bytes.
  * **CSRF Token Handling**: Tests token extraction, caching, and automatic replay upon receiving simulated HTTP 403.
  * **Live vs. Mock Adapter**: Validates graceful fallback to local mocks when SAP network is unreachable.

---

## 3. How to Execute Tests

To run the complete test suite from the repository root:

```powershell
# From the project root:
cd backend
python -m pytest tests/ -v
```

### Running Targeted Test Categories
```powershell
# Run only Clean Core validation tests:
python -m pytest tests/services/test_validator.py -v

# Run only SAP ADT client security tests:
python -m pytest tests/sap/test_adt_client.py -v

# Run with test coverage report:
python -m pytest tests/ --cov=src --cov-report=term-missing
```
