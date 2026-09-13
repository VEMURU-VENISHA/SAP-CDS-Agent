import React, { useState } from 'react';
import { Play, CheckCircle, ArrowRight, Loader2, Sparkles, FileCode2 } from 'lucide-react';
import { analyzeRequirement, submitHumanApproval } from '../../services/api';
import { PipelineResult } from '../../types';

export const RecentPipelines: React.FC = () => {
  const [title, setTitle] = useState('Sales Order Fulfillment Analytics');
  const [description, setDescription] = useState(
    'Require an analytical data model combining sales order headers and item fulfillment status, customer postal code, and net billing amount for quarterly reporting.'
  );
  const [entities, setEntities] = useState('SalesOrder, Customer, DeliveryDocument');
  const [fields, setFields] = useState('SalesOrderID, SoldToParty, NetAmount, DeliveryStatus, PostalCode');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<string | null>(null);

  const handleRunPipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setApprovalStatus(null);

    try {
      const res = await analyzeRequirement({
        title,
        description,
        business_domain: 'Sales & Distribution',
        required_entities: entities.split(',').map((e) => e.trim()).filter(Boolean),
        required_fields: fields.split(',').map((f) => f.trim()).filter(Boolean),
      });
      setResult(res);
    } catch (err: any) {
      setError(err?.message || 'Pipeline execution failed');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!result?.decision?.id) return;
    try {
      await submitHumanApproval(result.decision.id, true, 'lead_architect');
      setApprovalStatus('APPROVED');
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* Left Input Form */}
      <div className="lg:col-span-5 bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur">
        <div className="flex items-center space-x-2 text-sm font-semibold text-gray-200 mb-4">
          <Sparkles className="w-4 h-4 text-blue-400" />
          <span>New Business / Data Requirement Intake</span>
        </div>

        <form onSubmit={handleRunPipeline} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Requirement Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Natural Language Requirement (Statement of Need)
            </label>
            <textarea
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Anticipated SAP Entities (Comma-separated)
            </label>
            <input
              type="text"
              value={entities}
              onChange={(e) => setEntities(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Requested Business Fields (Comma-separated)
            </label>
            <input
              type="text"
              value={fields}
              onChange={(e) => setFields(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold py-2.5 rounded-lg flex items-center justify-center space-x-2 transition-all shadow-md shadow-blue-600/20 disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Orchestrating 9 Agents...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Analyze & Formulate Decision</span>
              </>
            )}
          </button>
        </form>

        {error && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-xs">
            {error}
          </div>
        )}
      </div>

      {/* Right Output / Pipeline Results */}
      <div className="lg:col-span-7 bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
            <div className="flex items-center space-x-2">
              <FileCode2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold text-gray-200">
                Agent Orchestration Output & Recommendation
              </span>
            </div>
            {result && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-gray-800 text-blue-300">
                Events Logged: {result.audit_events_count}
              </span>
            )}
          </div>

          {!result ? (
            <div className="text-center py-16 text-gray-500 space-y-2">
              <p className="text-xs">
                Submit a business requirement to trigger the 9-agent intelligence pipeline.
              </p>
              <p className="text-[11px] text-gray-600">
                Pipeline will evaluate: Discovery → Semantic Mapping → Decision (REUSE/EXTEND/CREATE) → DDL Draft → Governance Gate.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Decision Action Banner */}
              <div className="p-4 rounded-lg bg-gray-950 border border-gray-800 flex items-start justify-between">
                <div>
                  <div className="text-xs text-gray-400">Strategic Recommendation:</div>
                  <div className="flex items-center space-x-2 mt-1">
                    <span
                      className={`px-2.5 py-0.5 rounded-md text-xs font-bold ${
                        result.decision.action === 'REUSE'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : result.decision.action === 'EXTEND'
                          ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40'
                          : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      }`}
                    >
                      {result.decision.action}
                    </span>
                    <span className="text-xs text-gray-300 font-mono">
                      Confidence: {(result.decision.confidence_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-2 leading-relaxed">
                    {result.decision.rationale}
                  </p>
                </div>
              </div>

              {/* Generated ABAP CDS Code Preview */}
              <div>
                <div className="text-xs font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                  <span>Synthesized ABAP CDS View Entity Draft:</span>
                  <span className="text-[10px] text-gray-500 font-mono">Target: S/4HANA 2023 DDL</span>
                </div>
                <pre className="p-3.5 rounded-lg bg-gray-950 border border-gray-800 text-[11px] font-mono text-gray-300 overflow-x-auto max-h-48 leading-relaxed">
                  {result.generated_code_preview}
                </pre>
              </div>

              {/* Human Governance Approval Banner */}
              <div className="p-3.5 rounded-lg bg-blue-950/20 border border-blue-800/40 flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="text-xs font-medium text-blue-300">
                    Human-in-the-Loop Governance Gate
                  </div>
                  <div className="text-[11px] text-gray-400">
                    {approvalStatus === 'APPROVED'
                      ? 'Approved by Lead Architect (audit recorded)'
                      : 'Approval required before workbench activation'}
                  </div>
                </div>

                {approvalStatus === 'APPROVED' ? (
                  <span className="flex items-center text-xs text-emerald-400 font-medium px-3 py-1 bg-emerald-500/10 rounded-md">
                    <CheckCircle className="w-3.5 h-3.5 mr-1" /> Approved
                  </span>
                ) : (
                  <button
                    onClick={handleApprove}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium transition-colors"
                  >
                    Authorize Draft
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
