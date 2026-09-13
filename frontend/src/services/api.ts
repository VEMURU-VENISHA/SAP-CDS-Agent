import { HealthStatus, PipelineResult } from '../types';

const API_BASE = '/api/v1';

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Failed to fetch platform health: ${res.statusText}`);
  }
  return res.json();
}

export async function analyzeRequirement(payload: {
  title: string;
  description: string;
  business_domain: string;
  required_entities: string[];
  required_fields: string[];
}): Promise<PipelineResult> {
  const res = await fetch(`${API_BASE}/requirements/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || err?.detail || 'Pipeline execution failed');
  }

  return res.json();
}

export async function submitHumanApproval(decisionId: string, approved: boolean, approver: string) {
  const res = await fetch(`${API_BASE}/decisions/approval`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      decision_id: decisionId,
      approved,
      approver,
    }),
  });

  return res.json();
}
