"""Tests for Core Domain Models."""

from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSLayer,
    DataModel,
    DataModelAssociation,
    DataModelEntity,
    Decision,
    DecisionAction,
    DeploymentRequest,
    DeploymentStatus,
    FieldMapping,
    MappingType,
    TargetUseCase,
    ValidationResult,
)


def test_business_requirement_model():
    req = BusinessRequirement(
        title="Sales Order Analytics View",
        description="Need a CDS view joining Sales Order Header and Item with Net Amount and Customer Name",
        business_domain="Sales & Distribution",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder", "Customer"],
        required_fields=["SalesOrderID", "ItemNumber", "NetAmount", "SoldToParty"],
        filter_criteria=["CreationDate >= 20230101"],
    )
    assert req.id is not None
    assert req.title == "Sales Order Analytics View"
    assert len(req.required_fields) == 4


def test_cds_candidate_model():
    candidate = CDSCandidate(
        view_name="I_SalesOrderAnalytics",
        sql_view_name="ISALESORDERAN",
        description="Sales Order Analytics Cube",
        layer=CDSLayer.COMPOSITE,
        confidence_score=0.92,
        source_tables=["VBAK", "VBAP"],
        available_fields=["SalesOrder", "SalesOrderItem", "NetAmount"],
        key_fields=["SalesOrder", "SalesOrderItem"],
    )
    assert candidate.view_name == "I_SalesOrderAnalytics"
    assert candidate.layer == CDSLayer.COMPOSITE
    assert candidate.confidence_score == 0.92


def test_field_mapping_model():
    mapping = FieldMapping(
        requirement_field="NetAmount",
        matched_field="NetAmountInTransactionCurrency",
        source_entity="I_SalesOrder",
        data_type="abap.curr(15,2)",
        mapping_type=MappingType.DIRECT_MATCH,
        confidence=0.98,
    )
    assert mapping.requirement_field == "NetAmount"
    assert mapping.mapping_type == MappingType.DIRECT_MATCH


def test_decision_model():
    decision = Decision(
        requirement_id="req-1234",
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrderAnalytics",
        confidence_score=0.96,
        fit_percentage=96.5,
        rationale="View I_SalesOrderAnalytics covers 96% of required fields.",
        missing_fields=[],
        human_approval_required=True,
        is_approved=False,
    )
    assert decision.action == DecisionAction.REUSE
    assert decision.human_approval_required is True
    assert decision.is_approved is False


def test_data_model():
    model = DataModel(
        name="ZC_SalesOrderOverview",
        root_entity="I_SalesOrder",
        entities=[
            DataModelEntity(name="I_SalesOrder", layer=CDSLayer.BASIC, fields=["SalesOrder", "SoldToParty"]),
            DataModelEntity(name="I_Customer", layer=CDSLayer.BASIC, fields=["Customer", "CustomerName"]),
        ],
        associations=[
            DataModelAssociation(
                source_entity="I_SalesOrder",
                target_entity="I_Customer",
                cardinality="[0..1]",
                on_condition="$projection.SoldToParty = _Customer.Customer",
                alias="_Customer",
            )
        ],
    )
    assert model.name == "ZC_SalesOrderOverview"
    assert len(model.associations) == 1
    assert model.associations[0].alias == "_Customer"


def test_validation_result_model():
    res = ValidationResult(
        is_valid=True,
        syntax_errors=[],
        naming_convention_violations=[],
        clean_core_compliance_score=98.0,
        governance_warnings=[],
    )
    assert res.is_valid is True
    assert res.clean_core_compliance_score == 98.0


def test_deployment_request_model():
    req = DeploymentRequest(
        object_name="ZC_SalesAnalytics",
        package="ZSALES",
        transport_request="DEVK900010",
        requester="developer_jane",
        status=DeploymentStatus.PENDING_APPROVAL,
    )
    assert req.object_name == "ZC_SalesAnalytics"
    assert req.status == DeploymentStatus.PENDING_APPROVAL
