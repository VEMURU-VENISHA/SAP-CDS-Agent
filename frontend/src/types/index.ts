export type DecisionAction = 'REUSE' | 'EXTEND' | 'CREATE';

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
  tradeoffs: string[];
  human_approval_required: boolean;
  is_approved: boolean;
  approved_by?: string;
}

export interface PipelineResult {
  requirement: BusinessRequirement;
  decision: Decision;
  generated_code_preview: string;
  current_step: string;
  audit_events_count: number;
}
