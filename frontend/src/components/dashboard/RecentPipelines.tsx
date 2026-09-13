import React, { useState } from 'react';
import { Play, CheckCircle, Loader2, Sparkles, FileCode2, AlertCircle, BookmarkPlus } from 'lucide-react';
import { analyzeRequirement, submitHumanApproval } from '../../services/api';
import { PipelineResult } from '../../types';

interface RecentPipelinesProps {
  onPipelineExecuted?: (result: PipelineResult) => void;
  onDecisionApproved?: (decisionId: string) => void;
}

export const RecentPipelines: React.FC<RecentPipelinesProps> = ({
  onPipelineExecuted,
  onDecisionApproved,
}) => {
  // Empty default state - no seeded text submitted automatically
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [entities, setEntities] = useState('');
  const [fields, setFields] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<string | null>(null);

  const handleLoadSample = () => {
    setTitle('[SAMPLE] Sales Order Analytics Model');
    setDescription(
      '[SAMPLE TEMPLATE] Analytical view combining sales order headers with customer billing amount and delivery status.'
    );
    setEntities('SalesOrder, Customer');
    setFields('SalesOrderID, SoldToParty, NetAmount, DeliveryStatus');
  };

  const handleRunPipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !description.trim()) {
      setError('Please provide a title and requirement statement before running the pipeline.');
      return;
    }

    setLoading(true);
    setError(null);
    setApprovalStatus(null);

    try {
      const res = await analyzeRequirement({
        title: title.trim(),
        description: description.trim(),
        business_domain: 'Sales & Distribution',
        required_entities: entities.split(',').map((e) => e.trim()).filter(Boolean),
        required_fields: fields.split(',').map((f) => f.trim()).filter(Boolean),
      });
      setResult(res);
      if (onPipelineExecuted) {
        onPipelineExecuted(res);
      }
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
      if (onDecisionApproved) {
        onDecisionApproved(result.decision.id);
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* Left Input Form */}
      <div className="lg:col-span-5 bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-200">
            <Sparkles className="w-4 h-4 text-blue-400" />
            <span>Business / Data Requirement Intake</span>
          </div>
          <button
            type="button"
            onClick={handleLoadSample}
            className="flex items-center space-x-1 text-[11px] text-blue-400 hover:text-blue-300 font-medium bg-blue-500/10 hover:bg-blue-500/20 px-2 py-1 rounded border border-blue-500/30 transition-colors"
            title="Populates sample text for testing. Does not submit automatically."
          >
            <BookmarkPlus className="w-3 h-3" />
            <span>Fill Sample Template</span>
          </button>
        </div>

        <form onSubmit={handleRunPipeline} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Requirement Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Sales Order Analytics View (Example)"
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
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
              placeholder="e.g. Need an analytical CDS view joining sales order items with customer postal code and net amount..."
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Anticipated Business Entities (Optional hints, comma-separated)
            </label>
            <input
              type="text"
              value={entities}
              onChange={(e) => setEntities(e.target.value)}
              placeholder="e.g. SalesOrder, Customer (Hints only)"
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Requested Business Fields (Optional hints, comma-separated)
            </label>
            <input
              type="text"
              value={fields}
              onChange={(e) => setFields(e.target.value)}
              placeholder="e.g. SalesOrderID, NetAmount, CustomerName"
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
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
                <span>Execute Agent Pipeline</span>
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
                Agent Orchestration Output
              </span>
            </div>
            {result && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-gray-800 text-blue-300">
                Actual Events Logged: {result.audit_events_count}
              </span>
            )}
          </div>

          {!result ? (
            <div className="text-center py-14 px-4 text-gray-500 space-y-3">
              <div className="p-3 bg-gray-800/40 rounded-full w-12 h-12 mx-auto flex items-center justify-center text-gray-400">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <p className="text-xs font-semibold text-gray-300">No pipeline runs yet</p>
                <p className="text-[11px] text-gray-400 max-w-sm mx-auto">
                  No real SAP discovery data has been queried yet because the SAP connector is unconnected.
                </p>
                <p className="text-[11px] text-gray-500 max-w-sm mx-auto">
                  Submit a requirement to execute the multi-agent pipeline and generate a structured evaluation.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Notice regarding Unconnected SAP */}
              <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[11px] text-amber-300 flex items-center space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>
                  <strong>Unconnected Mode Note:</strong> SAP catalog discovery was bypassed per Milestone 1 guardrails. Zero synthetic SAP metadata was returned.
                </span>
              </div>

              {/* Decision Action Banner */}
              <div className="p-4 rounded-lg bg-gray-950 border border-gray-800 flex items-start justify-between">
                <div>
                  <div className="text-xs text-gray-400">Recommended Action:</div>
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
                    <span className="text-xs text-gray-400 font-mono">
                      (Fit: {result.decision.fit_percentage}%)
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
                  <span>Synthesized ABAP CDS View Entity Draft Skeleton:</span>
                  <span className="text-[10px] text-amber-400 font-mono">Draft Skeleton (Unconnected)</span>
                </div>
                <pre className="p-3.5 rounded-lg bg-gray-950 border border-gray-800 text-[11px] font-mono text-gray-300 overflow-x-auto max-h-48 leading-relaxed">
                  {result.generated_code_preview}
                </pre>
              </div>

              {/* Human Governance Approval Banner */}
              <div className="p-3.5 rounded-lg bg-blue-950/20 border border-blue-800/40 flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="text-xs font-medium text-blue-300">
                    Human Approval Gate
                  </div>
                  <div className="text-[11px] text-gray-400">
                    {approvalStatus === 'APPROVED'
                      ? 'Approved by Lead Architect (audit recorded)'
                      : 'Mandatory sign-off required prior to any SAP DEV activation'}
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
