"""Tests for SAP_CREATION_TEST_BYPASS_VALIDATION temporary development bypass mode."""

import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.config import get_settings
from src.models.domain import (
    BusinessRequirement,
    CDSReviewPackage,
    Decision,
    DecisionAction,
    ReviewStatus,
    SAPCreationResult,
)
from src.services.review_service import get_review_store
from src.core.exceptions import (
    GovernanceApprovalRequiredError,
    SAPConflictError,
    SAPSecurityError,
    SAPTransportRequestError,
)

client = TestClient(app)


def make_unapproved_package_with_failed_validation(review_id: str = "test-bypass-rev-1") -> CDSReviewPackage:
    """Helper to create a review package with can_approve=False and failed validation status."""
    req = BusinessRequirement(
        title="Test Bypass",
        description="Test bypass requirement description",
        required_fields=["SalesOrder"],
    )
    dec = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_TESTSALESVIEW",
        confidence_score=0.9,
        fit_percentage=80.0,
        rationale="Bypass test decision",
    )
    return CDSReviewPackage(
        review_id=review_id,
        requirement_id=req.id,
        original_requirement=req,
        decision=dec,
        decision_confidence=0.9,
        decision_rationale="Bypass test decision",
        status=ReviewStatus.PENDING_REVIEW,
        can_approve=False,
        blocking_reasons=[
            "UNVERIFIED_JOIN: Unverified join condition generated between 'I_RO_SAFTSALESINVOICECUSTOMER' and 'I_JOURNALENTRYITEM'."
        ],
        object_name="ZC_TESTSALESVIEW",
        decision_action=DecisionAction.CREATE,
        ddl_source="define view entity ZC_TESTSALESVIEW as select from I_RO_SAFTSALESINVOICECUSTOMER { key SalesOrder }",
        reviewer=None,
        review_timestamp=None,
    )


@pytest.mark.asyncio
async def test_bypass_false_blocks_creation_on_validation_failure():
    """Requirement 12a: bypass=false + validation failure -> creation blocked."""
    store = get_review_store()
    pkg = make_unapproved_package_with_failed_validation("rev-bypass-false")
    store.register(pkg, {})

    with patch.object(get_settings(), "SAP_CREATION_TEST_BYPASS_VALIDATION", False):
        with pytest.raises(GovernanceApprovalRequiredError) as exc:
            await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900123")
        assert "Blocked" in str(exc.value) or "expected 'APPROVED'" in str(exc.value)


@pytest.mark.asyncio
async def test_bypass_true_allows_creation_flow_on_validation_failure():
    """Requirement 12b: bypass=true + validation failure -> existing ADT creation flow is reached."""
    store = get_review_store()
    pkg = make_unapproved_package_with_failed_validation("rev-bypass-true")
    # Simulate reviewer signoff on package metadata
    pkg.reviewer = "human_gatekeeper"
    from datetime import datetime, timezone
    pkg.review_timestamp = datetime.now(timezone.utc)
    store.register(pkg, {})

    mock_connector = MagicMock()
    mock_connector.create_cds_in_sap = AsyncMock(
        return_value=SAPCreationResult(
            success=True,
            operation="CREATE",
            review_id=pkg.review_id,
            sap_object_name="ZC_TESTSALESVIEW",
            repository_uri="/sap/bc/adt/ddic/ddl/sources/zc_testsalesview",
            object_type="DDLS/DF",
            package="ZTRAINING_2026",
            activation_status="ACTIVE",
            transport_request="DEVK900123",
            sap_http_status=200,
            sap_write_performed=True,
        )
    )

    with patch.object(get_settings(), "SAP_CREATION_TEST_BYPASS_VALIDATION", True):
        res = await store.execute_sap_creation(
            pkg.review_id,
            transport_request="DEVK900123",
            connector=mock_connector,
        )
        assert res.success is True
        assert res.sap_object_name == "ZC_TESTSALESVIEW"
        # Verify existing ADT connector method was invoked with exact source
        mock_connector.create_cds_in_sap.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_artifact_name_still_blocks_even_with_bypass():
    """Requirement 12c: Invalid Z/Y artifact name still blocks creation under bypass mode."""
    store = get_review_store()
    pkg = make_unapproved_package_with_failed_validation("rev-bad-name")
    pkg.object_name = "INVALID_NAME_NO_Z_OR_Y"
    pkg.reviewer = "human_gatekeeper"
    from datetime import datetime, timezone
    pkg.review_timestamp = datetime.now(timezone.utc)
    store.register(pkg, {})

    from src.sap.adt_connector import SAPADTConnector
    connector = SAPADTConnector(settings=get_settings())

    with patch.object(get_settings(), "SAP_CREATION_TEST_BYPASS_VALIDATION", True):
        with pytest.raises(SAPSecurityError) as exc:
            await connector.create_cds_in_sap(pkg, transport_request="DEVK900123")
        assert "customer namespace rules" in str(exc.value) or "Invalid SAP CDS name" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_transport_request_still_blocks_even_with_bypass():
    """Requirement 12d: Missing / invalid transport request still blocks creation under bypass mode."""
    store = get_review_store()
    pkg = make_unapproved_package_with_failed_validation("rev-bad-tr")
    pkg.reviewer = "human_gatekeeper"
    from datetime import datetime, timezone
    pkg.review_timestamp = datetime.now(timezone.utc)
    store.register(pkg, {})

    with patch.object(get_settings(), "SAP_CREATION_TEST_BYPASS_VALIDATION", True):
        with pytest.raises(SAPTransportRequestError) as exc:
            await store.execute_sap_creation(pkg.review_id, transport_request="INVALID_TR_FORMAT")
        assert "Invalid Workbench Transport Request" in str(exc.value)


@pytest.mark.asyncio
async def test_sap_collision_still_blocks_even_with_bypass():
    """Requirement 12e: SAP object collision still blocks creation under bypass mode."""
    store = get_review_store()
    pkg = make_unapproved_package_with_failed_validation("rev-collision")
    pkg.reviewer = "human_gatekeeper"
    from datetime import datetime, timezone
    pkg.review_timestamp = datetime.now(timezone.utc)
    store.register(pkg, {})

    mock_client = MagicMock()
    mock_client.validate_sap_object_name.return_value = True
    mock_client.validate_transport_request.return_value = True
    # Simulate pre-flight GET returning existing DDL -> collision!
    mock_client.get_ddl_source = AsyncMock(return_value="define view entity ZC_TESTSALESVIEW as select from I_RO_SAFTSALESINVOICECUSTOMER { key SalesOrder }")

    from src.sap.adt_connector import SAPADTConnector
    connector = SAPADTConnector(settings=get_settings())
    connector.client = mock_client

    with patch.object(get_settings(), "SAP_CREATION_TEST_BYPASS_VALIDATION", True):
        with pytest.raises(SAPConflictError) as exc:
            await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900123", connector=connector)
        assert "already exists in SAP" in str(exc.value)
