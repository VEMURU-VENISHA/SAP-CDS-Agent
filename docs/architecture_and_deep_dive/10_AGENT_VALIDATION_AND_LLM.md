# 10 - AI Synthesis, Validation & Clean Core Engine

## 1. Architectural Philosophy: AI Proposes, Deterministic Rules Verify

In enterprise SAP engineering, hallucinations can lead to production downtime, data corruption, or broken compliance audits. Therefore, the SAP CDS Agent enforces a strict architectural boundary:

```
[ Natural Language / Developer Intent ]
                   |
                   v
+-------------------------------------------------------+
|        GENERATIVE AI LAYER (Gemini 2.5 Flash)         |
|  - Semantic intent extraction                         |
|  - Entity relationship hypothesis                     |
|  - Initial DDL code drafting                          |
+-------------------------------------------------------+
                   |
                   v (Proposed DDL Artifact)
+-------------------------------------------------------+
|      DETERMINISTIC VALIDATION ENGINE (Python AST)     |
|  - 100% Rule-based Clean Core verification            |
|  - Customer namespace enforcement (Z* / Y*)           |
|  - SQL view name length and syntax constraints        |
|  - Semantic currency and quantity pairing checks      |
+-------------------------------------------------------+
        |                                       |
  [ PASSES RULES ]                       [ FAILS RULES ]
        |                                       |
        v                                       v
+-----------------------+              +-----------------------+
| LIVE SAP CHECKRUN     |              | AUTOMATED REPAIR LOOP |
| (ABAP Kernel Verif.)  |              | (Error Feedback to AI)|
+-----------------------+              +-----------------------+
```

* **The Rule**: The LLM is **never** trusted unconditionally. Every line of generated code must pass through deterministic AST linting and the SAP ABAP compiler checkrun before reaching human review.

---

## 2. Gemini 2.5 Flash Integration & Grounding

The AI engine is implemented in `backend/src/services/gemini_service.py`:
* **Model**: Google Gemini 2.5 Flash
* **Inference Parameters**: `temperature=0.1` (low temperature minimizes creative hallucination and enforces strict syntactic consistency), `max_output_tokens=2048`.

### Grounding via `HEURISTIC_SAP_VOCABULARY`
To prevent the model from inventing fictional SAP tables (e.g., `CUSTOM_SALES_TABLE`) or non-existent annotations, the system prompt injects real SAP S/4HANA vocabulary:
* Verified standard CDS view prefixes (`I_*`, `C_*`, `R_*`).
* Standard field names (`SalesOrder`, `SalesOrderItem`, `SoldToParty`, `NetAmount`, `TransactionCurrency`).
* Approved VDM annotations:
  * `@VDM.viewType: #BASIC | #COMPOSITE | #CONSUMPTION`
  * `@AccessControl.authorizationCheck: #CHECK | #NOT_REQUIRED`
  * `@EndUserText.label: '...'`
  * `@Semantics.amount.currencyCode: '...'`
  * `@Semantics.quantity.unitOfMeasure: '...'`

---

## 3. The 5-Layer Deterministic Validation Pipeline

The `CDSGenerationValidator` (`backend/src/services/cds_generation_validator.py`) inspects the DDL Abstract Syntax Tree against 5 non-negotiable rules:

### Layer 1: Customer Namespace Enforcement
* **Rule**: Custom CDS views must start with `Z` or `Y` (e.g., `ZI_SalesOrderSummary` or `YI_CustomerAging`).
* **Implementation**:
  ```python
  if not (view_name.startswith("Z") or view_name.startswith("Y")):
      return ValidationError("Namespace violation: View entity name must begin with 'Z' or 'Y'.")
  ```

### Layer 2: SQL View Append Name Validation
* **Rule**: In classical CDS views declaring `@AbapCatalog.sqlViewName`, the SQL name must be $\le 16$ characters and contain only uppercase alphanumeric characters.
* **Implementation**:
  ```python
  if sql_view_name and (len(sql_view_name) > 16 or not sql_view_name.isalnum()):
      return ValidationError(f"SQL view name '{sql_view_name}' exceeds 16 chars or contains invalid characters.")
  ```

### Layer 3: Clean Core Compliance (Zero Direct Table Queries)
* **Rule**: Under SAP Clean Core, extensions must consume released CDS views (`I_*`), not underlying transparent database tables (`VBAK`, `VBAP`, `MARA`, `KNA1`, `BSEG`).
* **Implementation**: The validator checks base data sources against a blacklist of 4,000+ classical SAP tables. Any reference to a blacklisted table immediately fails validation with Clean Core remediation guidance:
  > *"Violation: Direct query on 'VBAK' is prohibited under Clean Core. Use released interface view 'I_SalesOrder' instead."*

### Layer 4: Primary Key Declaration
* **Rule**: Every CDS view entity must declare at least one `key` element to preserve uniqueness and OData service compatibility.
* **Implementation**: Ensures that at least one field in the select list is prefixed with the keyword `key`.

### Layer 5: Currency & Unit Semantic Pairing
* **Rule**: In SAP HANA, any monetary amount field annotated with `@Semantics.amount.currencyCode` must reference an active currency field in the projection.
* **Implementation**:
  ```python
  for amount_field, currency_ref in semantic_pairs:
      if currency_ref not in projected_fields:
          return ValidationError(f"Amount field '{amount_field}' references currency '{currency_ref}', which is missing from projection.")
  ```

---

## 4. The Automated Syntax Repair Loop

When generated DDL fails either deterministic linting or the SAP ABAP checkrun compiler, the system triggers `GeminiService.repair_ddl_syntax()`:

```
[ Failed DDL ] + [ Exact Compiler Error & Line Number ]
                       |
                       v
[ Prompt: "Fix the syntax error on line 12: Field 'KUNNR' does not exist in 'I_SalesOrder'. Use 'SoldToParty'." ]
                       |
                       v
[ Gemini 2.5 Flash Synthesizes Corrected DDL ]
                       |
                       v
[ Re-Run Validation Pipeline (Up to 3 Automated Attempts) ]
```

* **Outcome**: Automatically corrects $85\%+$ of minor syntactic or field-name discrepancies without requiring manual developer debugging.
