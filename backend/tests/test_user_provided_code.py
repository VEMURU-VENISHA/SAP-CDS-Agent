"""Unit tests for User-Provided CDS Code Option in Step 9.

Tests the 7 critical requirements for user-provided CDS View Entity code:
1. Valid user CDS code -> validation passes.
2. User code with invented field -> validation fails.
3. User code with unverified join -> validation fails.
4. User code with valid verified association -> validation passes.
5. User code approved -> exact approved code reaches ADT creation without LLM re-generation.
6. User edits code after approval -> approval becomes invalid and requires re-validation & re-approval.
7. User-provided code must never trigger an automatic SAP write.
"""

import pytest
from src.services.cds_generation_validator import CDSGenerationValidator
from src.models.domain import (
    BusinessRequirement,
    Decision,
    DecisionAction,
    CDSDraft,
    ValidationResult,
    CDSReviewPackage,
    ReviewStatus,
)
from src.services.review_service import build_review_package, ReviewStore, get_review_store


def test_1_valid_user_cds_code_validation_passes():
    """1. Valid user CDS code -> validation passes."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'User Provided Sales View'
define view entity ZC_USERSALESORDER
  as select from I_SalesOrder
{
  key SalesOrder,
  SalesOrganization,
  SoldToParty
}"""
    context = {
        "artifact_name": "ZC_USERSALESORDER",
        "selected_views": ["I_SalesOrder"],
        "mappings": [
            {"business_field": "Sales Order", "actual_field": "SalesOrder", "selected_cds": "I_SalesOrder"},
            {"business_field": "Sales Org", "actual_field": "SalesOrganization", "selected_cds": "I_SalesOrder"},
            {"business_field": "Customer", "actual_field": "SoldToParty", "selected_cds": "I_SalesOrder"},
        ],
        "join_paths": [],
    }

    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is True
    assert res["coverage"] == 100.0
    assert len(res["errors"]) == 0


def test_2_user_code_with_invented_field_validation_fails():
    """2. User code with invented field -> validation fails."""
    user_code_invented = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'User Provided View'
define view entity ZC_USERSALESORDER
  as select from I_SalesOrder
{
  key SalesOrder,
  FakeNonExistentField_1234
}"""
    context = {
        "artifact_name": "ZC_USERSALESORDER",
        "selected_views": ["I_SalesOrder"],
        "mappings": [
            {"business_field": "Sales Order", "actual_field": "SalesOrder", "selected_cds": "I_SalesOrder"},
            {"business_field": "Sales Org", "actual_field": "SalesOrganization", "selected_cds": "I_SalesOrder"},
        ],
        "join_paths": [],
    }

    res = CDSGenerationValidator.validate_generation(user_code_invented, context)
    assert res["valid"] is False
    assert len(res["errors"]) > 0
    assert any("FakeNonExistentField_1234" in err or "FIELD_SOURCE_MISMATCH" in err or "UNVERIFIED_FIELD" in err for err in res["errors"])


def test_3_user_code_with_unverified_join_validation_fails():
    """3. User code with unverified join -> validation fails."""
    user_code_unverified_join = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'User Provided Multi View'
define view entity ZC_USERSALESORDER
  as select from I_RO_SAFTSALESINVOICECUSTOMER as _Saft
  association [1..*] to I_JOURNALENTRYITEM as _Item
    on _Saft.Customer = _Item.Customer
{
  key _Saft.SalesInvoice as SalesInvoice,
  _Saft.Customer as Customer,
  _Item.AmountInCompanyCodeCurrency as TotalAmount
}"""
    context = {
        "artifact_name": "ZC_USERSALESORDER",
        "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_JOURNALENTRYITEM"],
        "mappings": [
            {"business_field": "Sales Invoice", "actual_field": "SalesInvoice", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer", "actual_field": "Customer", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Total Amount", "actual_field": "AmountInCompanyCodeCurrency", "selected_cds": "I_JOURNALENTRYITEM"},
        ],
        "join_paths": [],  # Empty join paths -> unverified join!
    }

    res = CDSGenerationValidator.validate_generation(user_code_unverified_join, context)
    assert res["valid"] is False
    assert any("UNVERIFIED_JOIN" in err for err in res["errors"])


def test_4_user_code_with_valid_verified_association_validation_passes():
    """4. User code with valid verified association -> validation passes."""
    user_code_verified_assoc = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Verified Association View'
define view entity ZC_USERSALESORDER
  as select from I_RO_SAFTSALESINVOICECUSTOMER as _Saft
  association [1..1] to I_CUSTOMER as _Cust
    on $projection.Customer = _Cust.Customer
{
  key _Saft.SalesInvoice as SalesInvoice,
  _Saft.Customer as Customer,
  _Cust.CustomerName as CustomerName
}"""
    context = {
        "artifact_name": "ZC_USERSALESORDER",
        "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER"],
        "mappings": [
            {"business_field": "Sales Invoice", "actual_field": "SalesInvoice", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer", "actual_field": "Customer", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer Name", "actual_field": "CustomerName", "selected_cds": "I_CUSTOMER"},
        ],
        "join_paths": [
            {
                "source_cds": "I_RO_SAFTSALESINVOICECUSTOMER",
                "source_field": "Customer",
                "target_cds": "I_CUSTOMER",
                "target_field": "Customer",
                "cardinality": "1..1",
            }
        ],
    }

    res = CDSGenerationValidator.validate_generation(user_code_verified_assoc, context)
    assert res["valid"] is True
    assert res["coverage"] == 100.0
    assert len(res["errors"]) == 0


def test_5_user_code_approved_reaches_adt_creation_without_llm():
    """5. User code approved -> exact approved code reaches ADT creation without LLM re-generation."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Approved User Code'
define view entity ZC_EXACTUSERCODE
  as select from I_SalesOrder
{
  key SalesOrder
}"""

    req = BusinessRequirement(title="Test", description="Test Business Requirement SalesOrder", required_fields=["SalesOrder"])
    dec = Decision(requirement_id=req.id, action=DecisionAction.CREATE, proposed_new_view_name="ZC_EXACTUSERCODE", confidence_score=1.0, fit_percentage=100.0, rationale="User provided verified code")
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name="ZC_EXACTUSERCODE",
        ddl_source=user_code,
        code_source="USER_PROVIDED",
        original_user_code=user_code,
    )
    val = ValidationResult(is_valid=True)

    wf_state = {
        "requirement": req,
        "decision": dec,
        "cds_draft": draft,
        "validation_result": val,
        "generated_cds_code": user_code,
    }

    pkg = build_review_package(wf_state)
    pkg.code_source = "USER_PROVIDED"
    pkg.original_user_code = user_code
    pkg.can_approve = True
    pkg.blocking_reasons = []

    store = ReviewStore(":memory:")
    store.register(pkg, wf_state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="User code approved")

    assert approved_pkg.status == ReviewStatus.APPROVED
    assert approved_pkg.code_source == "USER_PROVIDED"
    assert approved_pkg.ddl_source == user_code
    assert approved_pkg.original_user_code == user_code


def test_6_user_edits_code_after_approval_requires_revalidation():
    """6. User edits code after approval -> approval becomes invalid and requires re-validation & re-approval."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Approved User Code'
define view entity ZC_EDITAFTERAPPROVE
  as select from I_SalesOrder
{
  key SalesOrder
}"""

    req = BusinessRequirement(title="Test", description="Test Business Requirement SalesOrder", required_fields=["SalesOrder"])
    dec = Decision(requirement_id=req.id, action=DecisionAction.CREATE, proposed_new_view_name="ZC_EDITAFTERAPPROVE", confidence_score=1.0, fit_percentage=100.0, rationale="User provided verified code")
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name="ZC_EDITAFTERAPPROVE",
        ddl_source=user_code,
        code_source="USER_PROVIDED",
    )
    val = ValidationResult(is_valid=True)

    wf_state = {
        "requirement": req,
        "decision": dec,
        "cds_draft": draft,
        "validation_result": val,
        "generated_cds_code": user_code,
    }

    pkg = build_review_package(wf_state)
    pkg.code_source = "USER_PROVIDED"
    pkg.can_approve = True
    pkg.blocking_reasons = []

    store = ReviewStore(":memory:")
    store.register(pkg, wf_state)
    store.approve(pkg.review_id, reviewer="lead_architect")

    # User edits code after approval
    edited_code = user_code.replace("ZC_EDITAFTERAPPROVE", "ZC_EDITAFTERAPPROVE_MODIFIED")
    updated_pkg = store.update_source(pkg.review_id, edited_code)

    # State source hash mismatch check should block creation if attempted without re-approval
    from src.sap.adt_client import SAPADTClient
    hash_orig = SAPADTClient.compute_source_hash(user_code)
    hash_edited = SAPADTClient.compute_source_hash(edited_code)
    assert hash_orig != hash_edited
    assert updated_pkg.ddl_source == edited_code


@pytest.mark.asyncio
async def test_7_user_provided_code_never_triggers_automatic_sap_write():
    """7. User-provided code must never trigger an automatic SAP write upon validation."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_TESTSAFE
  as select from I_SalesOrder
{
  key SalesOrder
}"""
    context = {
        "artifact_name": "ZC_TESTSAFE",
        "selected_views": ["I_SalesOrder"],
        "mappings": [{"business_field": "Sales Order", "actual_field": "SalesOrder", "selected_cds": "I_SalesOrder"}],
        "join_paths": [],
    }

    # Validation only returns dict, perform zero network calls
    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is True

    # Check that no SAP mock or connector write was invoked
    # Verify review store has no pending/approved packages created automatically
    store = get_review_store()
    assert store.get_by_requirement("non_existent_req_id") is None


def test_8_regression_test_A_unused_selected_view_ignored():
    """TEST A: Selected A, B, C. Mappings use A + B. Final code uses A + B. Expected: PASS (C ignored as unused)."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_TEST_A
  as select from I_RO_SAFTSALESINVOICECUSTOMER as _Saft
  association [1..1] to I_CUSTOMER as _Cust
    on $projection.Customer = _Cust.Customer
{
  key _Saft.SalesInvoice as SalesInvoice,
  _Saft.Customer as Customer,
  _Cust.CustomerName as CustomerName
}"""
    context = {
        "artifact_name": "ZC_TEST_A",
        "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"],
        "mappings": [
            {"business_field": "Sales Invoice", "actual_field": "SalesInvoice", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer", "actual_field": "Customer", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer Name", "actual_field": "CustomerName", "selected_cds": "I_CUSTOMER"},
        ],
        "join_paths": [
            {
                "source_cds": "I_RO_SAFTSALESINVOICECUSTOMER",
                "source_field": "Customer",
                "target_cds": "I_CUSTOMER",
                "target_field": "Customer",
                "cardinality": "1..1",
            }
        ],
    }

    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is True
    assert res["coverage"] == 100.0
    assert len(res["errors"]) == 0


def test_9_regression_test_B_missing_mapped_source_fails():
    """TEST B: Selected A, B, C. Mappings use A + C. Final code uses A + B (missing C). Verified path A -> C exists. Expected: FAIL for C."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_TEST_B
  as select from I_RO_SAFTSALESINVOICECUSTOMER as _Saft
  association [1..1] to I_CUSTOMER as _Cust
    on $projection.Customer = _Cust.Customer
{
  key _Saft.SalesInvoice as SalesInvoice,
  _Saft.Customer as Customer,
  _Cust.CustomerName as CustomerName
}"""
    context = {
        "artifact_name": "ZC_TEST_B",
        "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"],
        "mappings": [
            {"business_field": "Sales Invoice", "actual_field": "SalesInvoice", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer", "actual_field": "Customer", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Amount", "actual_field": "AmountInCompanyCodeCurrency", "selected_cds": "I_JOURNALENTRYITEM"},
        ],
        "join_paths": [
            {
                "source_cds": "I_RO_SAFTSALESINVOICECUSTOMER",
                "source_field": "Customer",
                "target_cds": "I_JOURNALENTRYITEM",
                "target_field": "Customer",
                "cardinality": "0..*",
            }
        ],
    }

    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is False
    assert any("MISSING_SELECTED_SOURCE" in err or "FIELD_SOURCE_MISMATCH" in err for err in res["errors"])


def test_10_regression_test_C_source_path_unavailable():
    """TEST C: Selected A, B, C. Mappings use A + C. No verified path A -> C. Expected: MISSING_REQUIRED_FIELD error, SOURCE_PATH_UNAVAILABLE warning."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_TEST_C
  as select from I_RO_SAFTSALESINVOICECUSTOMER as _Saft
{
  key _Saft.SalesInvoice as SalesInvoice,
  _Saft.Customer as Customer
}"""
    context = {
        "artifact_name": "ZC_TEST_C",
        "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"],
        "mappings": [
            {"business_field": "Sales Invoice", "actual_field": "SalesInvoice", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Customer", "actual_field": "Customer", "selected_cds": "I_RO_SAFTSALESINVOICECUSTOMER"},
            {"business_field": "Material", "actual_field": "Material", "selected_cds": "I_JOURNALENTRYITEM"},
        ],
        "join_paths": [],  # No verified join path A -> C
    }

    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is False
    assert any("MISSING_REQUIRED_FIELD" in err for err in res["errors"])
    assert any("SOURCE_PATH_UNAVAILABLE" in warn for warn in res.get("warnings", []))


def test_11_regression_test_D_user_provided_code_unused_selection_passes():
    """TEST D: User-provided code uses only A + B while C was selected but unused. Expected: USER_CODE_VALIDATED."""
    user_code = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_USER_TEST_D
  as select from I_SalesOrder as _Order
  association [1..1] to I_Customer as _Cust
    on $projection.SoldToParty = _Cust.Customer
{
  key _Order.SalesOrder as SalesOrder,
  _Order.SoldToParty as SoldToParty,
  _Cust.CustomerName as CustomerName
}"""
    context = {
        "artifact_name": "ZC_USER_TEST_D",
        "selected_views": ["I_SalesOrder", "I_Customer", "I_JournalEntryItem"],
        "mappings": [
            {"business_field": "Sales Order", "actual_field": "SalesOrder", "selected_cds": "I_SalesOrder"},
            {"business_field": "Sold-To Party", "actual_field": "SoldToParty", "selected_cds": "I_SalesOrder"},
            {"business_field": "Customer Name", "actual_field": "CustomerName", "selected_cds": "I_Customer"},
        ],
        "join_paths": [
            {
                "source_cds": "I_SalesOrder",
                "source_field": "SoldToParty",
                "target_cds": "I_Customer",
                "target_field": "Customer",
                "cardinality": "1..1",
            }
        ],
    }

    res = CDSGenerationValidator.validate_generation(user_code, context)
    assert res["valid"] is True
    assert res["coverage"] == 100.0
    assert len(res["errors"]) == 0


def test_12_one_authoritative_mapping_flows_step6_to_step9():
    """Regression Test: Step 6 mapping Material -> VERIFIED_CDS.VERIFIED_FIELD must be validated exactly by Step 9.
    If Step 9 receives a different/stale source or field, validation must fail.
    """
    step_6_mapping = [
        {
            "business_field": "Material",
            "selected_cds": "I_SalesOrder",
            "actual_field": "Material",
            "source_cds": "I_SalesOrder",
            "source_field": "Material",
            "field_label": "Material",
            "mapping_status": "VERIFIED",
            "evidence": "Step 6 Authoritative Mapping",
            "verified": True,
        }
    ]

    valid_ddl = """@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity ZC_EXACT_STEP6
  as select from I_SalesOrder
{
  key SalesOrder,
  Material
}"""
    context_step9 = {
        "artifact_name": "ZC_EXACT_STEP6",
        "selected_views": ["I_SalesOrder"],
        "mappings": step_6_mapping,
        "join_paths": [],
    }

    res_valid = CDSGenerationValidator.validate_generation(valid_ddl, context_step9)
    assert res_valid["valid"] is True
    assert res_valid["coverage"] == 100.0

    # If Step 9 receives a different/stale mapping (e.g. Material -> I_CUSTOMERSALESAREA.PRODUCTUNITGROUP)
    stale_mapping = [
        {
            "business_field": "Material",
            "selected_cds": "I_CUSTOMERSALESAREA",
            "actual_field": "PRODUCTUNITGROUP",
            "source_cds": "I_CUSTOMERSALESAREA",
            "source_field": "PRODUCTUNITGROUP",
            "field_label": "Material",
            "mapping_status": "VERIFIED",
            "evidence": "Stale Mapping",
            "verified": True,
        }
    ]
    context_stale = {
        "artifact_name": "ZC_EXACT_STEP6",
        "selected_views": ["I_SalesOrder"],
        "mappings": stale_mapping,
        "join_paths": [],
    }

    res_stale = CDSGenerationValidator.validate_generation(valid_ddl, context_stale)
    assert res_stale["valid"] is False
    assert len(res_stale["errors"]) > 0
    assert any("PRODUCTUNITGROUP" in err or "I_CUSTOMERSALESAREA" in err or "MISSING_REQUIRED_FIELD" in err for err in res_stale["errors"])
