export type DecisionAction = 'REUSE' | 'EXTEND' | 'CREATE' | 'INSUFFICIENT_EVIDENCE';

export type EvidenceLevel =
  | 'LEVEL_1_EXACT_FIELD'
  | 'LEVEL_2_LABEL_MATCH'
  | 'LEVEL_3_VERIFIED_ASSOCIATION'
  | 'LEVEL_4_HEURISTIC_SYNONYM'
  | 'LEVEL_5_UNVERIFIED_SUGGESTION'
  | 'LEVEL_6_MISSING';

export interface HealthStatus {
  status: string;
  app_name: string;
  version: string;
  environment: string;
  timestamp: string;
  database: {
    status: string;
    driver: string;
  };
  sap_connector: {
    status: string;
    system_id: string;
    client: string;
    s4hana_release: string;
    s4core_release: string;
    basis_release: string;
    is_connected: boolean;
  };
}

export interface BusinessRequirement {
  id: string;
  title: string;
  description: string;
  business_domain: string;
  target_use_case: string;
  required_entities: string[];
  required_fields: string[];
  filter_criteria: string[];
  created_at: string;
}

export interface StructuredRequirement {
  dimensions: string[];
  measures: string[];
  attributes: string[];
  parameters: string[];
  filters: string[];
  all_requested_concepts: string[];
}

export interface CDSCandidate {
  view_name: string;
  sql_view_name?: string;
  description: string;
  layer: 'BASIC' | 'COMPOSITE' | 'CONSUMPTION';
  release_status: string;
  confidence_score: number;
  source_tables: string[];
  associations: string[];
  available_fields: string[];
  key_fields: string[];
  is_extendable: boolean;
}

export interface FieldMapping {
  requirement_field: string;
  matched_field?: string;
  source_entity?: string;
  data_type?: string;
  mapping_type: 'DIRECT_MATCH' | 'ASSOCIATION_HOP' | 'CALCULATED' | 'MISSING' | 'UNRESOLVED';
  evidence_level: EvidenceLevel;
  evidence_detail: string;
  association_target_view?: string;
  association_target_field?: string;
  confidence: number;
}

export interface CandidateEvaluation {
  candidate: CDSCandidate;
  rank: number;
  rank_score: number;
  coverage_percentage: number;
  matched_concepts: string[];
  missing_concepts: string[];
  field_mappings: FieldMapping[];
  scoring_breakdown: Record<string, number>;
  is_extension_viable: boolean;
  suitability_reason: string;
}

export interface Decision {
  id: string;
  requirement_id: string;
  action: DecisionAction;
  recommended_view?: string;
  confidence_score: number;
  fit_percentage: number;
  rationale: string;
  missing_fields: string[];
  proposed_new_view_name?: string;
  proposed_extension_name?: string;
  requires_composition?: boolean;
  complementary_views?: string[];
  evaluated_candidates?: CandidateEvaluation[];
  structured_requirement?: StructuredRequirement;
  evidence_summary?: string[];
  warnings?: string[];
  tradeoffs: string[];
  human_approval_required: boolean;
  is_approved: boolean;
  approved_by?: string;
}

export type DraftElementType =
  | 'SOURCE_VIEW'
  | 'FIELD'
  | 'ASSOCIATION'
  | 'PARAMETER'
  | 'ANNOTATION'
  | 'FILTER';

export interface ElementEvidenceRecord {
  element_name: string;
  element_type: DraftElementType;
  source_entity?: string;
  relationship?: string;
  evidence_level: EvidenceLevel;
  evidence_detail: string;
  confidence: number;
  is_verified: boolean;
}

export interface DraftFieldElement {
  field_name: string;
  alias?: string;
  source_expression: string;
  source_entity: string;
  data_type?: string;
  is_key: boolean;
  evidence: ElementEvidenceRecord;
}

export interface DraftAssociationElement {
  association_name: string;
  target_entity: string;
  cardinality: string;
  on_condition: string;
  is_verified: boolean;
  evidence: ElementEvidenceRecord;
}

export interface DraftParameterElement {
  parameter_name: string;
  data_type: string;
  default_value?: string;
  evidence: ElementEvidenceRecord;
}

export type SAPValidationStatus =
  | 'PASS'
  | 'WARNING'
  | 'ERROR'
  | 'UNAVAILABLE'
  | 'INSUFFICIENT_EVIDENCE';

export interface SAPCheckMessage {
  uri?: string;
  severity: string;
  short_text: string;
  msgid?: string;
  msgno?: string;
  variables: string[];
  line?: number;
  column?: number;
  raw_safe_metadata?: Record<string, any>;
}

export interface SAPCheckrunResult {
  status: SAPValidationStatus;
  reporter?: string;
  triggering_uri?: string;
  check_report_status?: string;
  messages: SAPCheckMessage[];
  http_status?: number;
  content_type?: string;
  reason?: string;
}

export interface ValidationResult {
  is_valid: boolean;
  syntax_errors: string[];
  naming_convention_violations: string[];
  clean_core_compliance_score: number;
  governance_warnings: string[];
  details: Array<{ check: string; passed: boolean; detail: string }>;
  sap_validation_status?: SAPValidationStatus;
  sap_checkrun_result?: SAPCheckrunResult;
  sap_checkrun_reason?: string;
}

export interface CDSDraft {
  id: string;
  requirement_id: string;
  decision_action: DecisionAction;
  object_name: string;
  object_type: string;
  proposed_layer: 'BASIC' | 'COMPOSITE' | 'CONSUMPTION';
  source_views: string[];
  fields: DraftFieldElement[];
  associations: DraftAssociationElement[];
  parameters: DraftParameterElement[];
  filters: string[];
  annotations: Record<string, any>;
  ddl_source: string;
  evidence_per_element: ElementEvidenceRecord[];
  warnings: string[];
  validation_errors: string[];
  generation_status: string;
  sap_validation_status?: SAPValidationStatus;
  unresolved_items: string[];
  created_at: string;
}

export interface PipelineResult {
  requirement: BusinessRequirement;
  structured_requirement?: StructuredRequirement;
  evaluated_candidates?: CandidateEvaluation[];
  decision: Decision;
  generated_code_preview: string;
  cds_draft?: CDSDraft;
  validation_result?: ValidationResult;
  current_step: string;
  audit_events_count: number;
}

