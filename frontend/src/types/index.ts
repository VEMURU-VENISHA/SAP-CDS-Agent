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

export interface PipelineResult {
  requirement: BusinessRequirement;
  structured_requirement?: StructuredRequirement;
  evaluated_candidates?: CandidateEvaluation[];
  decision: Decision;
  generated_code_preview: string;
  current_step: string;
  audit_events_count: number;
}

