import React, { useState } from 'react';
import {
  Play,
  CheckCircle,
  Loader2,
  Sparkles,
  FileCode2,
  AlertCircle,
  BookmarkPlus,
  ShieldCheck,
  Layers,
  ArrowRight,
  Filter,
  Check,
  X,
  AlertTriangle,
  Info,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { analyzeRequirement, submitHumanApproval } from '../../services/api';
import { CandidateEvaluation, FieldMapping, PipelineResult } from '../../types';

interface RecentPipelinesProps {
  onPipelineExecuted?: (result: PipelineResult) => void;
  onDecisionApproved?: (decisionId: string) => void;
}

export const RecentPipelines: React.FC<RecentPipelinesProps> = ({
  onPipelineExecuted,
  onDecisionApproved,
}) => {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [entities, setEntities] = useState('');
  const [fields, setFields] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<string | null>(null);
  const [expandedCandidate, setExpandedCandidate] = useState<string | null>(null);

  const handleLoadSample = () => {
    setTitle('Sales Order Item Analytics');
    setDescription(
      'We need an analytical CDS view combining SalesOrder header with Material items, NetAmount, SoldToParty, and OrderQuantity where status is Completed.'
    );
    setEntities('SalesOrder, Customer');
    setFields('SalesOrder, Material, NetAmount, SoldToParty, OrderQuantity');
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

  const renderEvidenceBadge = (level: string) => {
    switch (level) {
      case 'LEVEL_1_EXACT_FIELD':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
            L1: Exact Field
          </span>
        );
      case 'LEVEL_2_LABEL_MATCH':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-teal-500/20 text-teal-300 border border-teal-500/30">
            L2: Label Match
          </span>
        );
      case 'LEVEL_3_VERIFIED_ASSOCIATION':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
            L3: Verified Assoc
          </span>
        );
      case 'LEVEL_4_HEURISTIC_SYNONYM':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
            L4: Heuristic Synonym
          </span>
        );
      case 'LEVEL_5_UNVERIFIED_SUGGESTION':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-orange-500/20 text-orange-300 border border-orange-500/30">
            L5: Unverified LLM
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
            L6: Missing / Unresolved
          </span>
        );
    }
  };

  const structured = result?.structured_requirement || result?.decision?.structured_requirement;
  const evaluations: CandidateEvaluation[] =
    result?.evaluated_candidates && result.evaluated_candidates.length > 0
      ? result.evaluated_candidates
      : result?.decision?.evaluated_candidates || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* Left Input Form */}
      <div className="lg:col-span-5 bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-200">
            <Sparkles className="w-4 h-4 text-blue-400" />
            <span>Business / Data Requirement Intake</span>
          </div>
          <button
            type="button"
            onClick={handleLoadSample}
            className="flex items-center space-x-1 text-[11px] text-blue-400 hover:text-blue-300 font-medium bg-blue-500/10 hover:bg-blue-500/20 px-2 py-1 rounded border border-blue-500/30 transition-colors"
            title="Populates sample text for testing."
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
              placeholder="e.g. Sales Order Item Analytics"
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
              placeholder="e.g. We need an analytical CDS view combining SalesOrder header with Material items, NetAmount, SoldToParty, and OrderQuantity..."
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
              placeholder="e.g. SalesOrder, Customer"
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
              placeholder="e.g. SalesOrder, Material, NetAmount, SoldToParty"
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
                <span>Executing Semantic Decision Engine...</span>
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
          <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-xs">
            {error}
          </div>
        )}
      </div>

      {/* Right Output / Pipeline Results */}
      <div className="lg:col-span-7 bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur flex flex-col justify-between space-y-4">
        <div>
          <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
            <div className="flex items-center space-x-2">
              <FileCode2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold text-gray-200">
                Decision Engine & Semantic Mapping Output
              </span>
            </div>
            {result && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-gray-800 text-blue-300">
                Audit Events: {result.audit_events_count}
              </span>
            )}
          </div>

          {!result ? (
            <div className="text-center py-16 px-4 text-gray-500 space-y-3">
              <div className="p-3 bg-gray-800/40 rounded-full w-12 h-12 mx-auto flex items-center justify-center text-gray-400">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <p className="text-xs font-semibold text-gray-300">Awaiting Pipeline Execution</p>
                <p className="text-[11px] text-gray-400 max-w-sm mx-auto">
                  Submit a requirement to extract dimensions, measures, attributes, and evaluate against verified SAP CDS metadata.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Extracted Semantic Concepts Badges */}
              {structured && (
                <div className="p-3.5 rounded-lg bg-gray-950 border border-gray-800 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-gray-300 flex items-center space-x-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-blue-400" />
                      <span>Extracted Business Concepts</span>
                    </span>
                    <span className="text-[10px] text-gray-500">Dynamic NL Concept Parser</span>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {structured.dimensions.map((d) => (
                      <span
                        key={d}
                        className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-300 border border-blue-500/20"
                        title="Dimension"
                      >
                        Dim: {d}
                      </span>
                    ))}
                    {structured.measures.map((m) => (
                      <span
                        key={m}
                        className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                        title="Measure"
                      >
                        Meas: {m}
                      </span>
                    ))}
                    {structured.attributes.map((a) => (
                      <span
                        key={a}
                        className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-500/10 text-purple-300 border border-purple-500/20"
                        title="Attribute"
                      >
                        Attr: {a}
                      </span>
                    ))}
                    {structured.filters.map((f) => (
                      <span
                        key={f}
                        className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20"
                        title="Filter"
                      >
                        Filter: {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Decision Action Banner */}
              <div className="p-4 rounded-lg bg-gray-950 border border-gray-800 space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[11px] font-medium text-gray-400">Architectural Decision</div>
                    <div className="flex items-center space-x-2.5 mt-1">
                      <span
                        className={`px-3 py-1 rounded-md text-xs font-bold ${
                          result.decision.action === 'REUSE'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : result.decision.action === 'EXTEND'
                            ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40'
                            : result.decision.action === 'INSUFFICIENT_EVIDENCE'
                            ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                            : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                        }`}
                      >
                        {result.decision.action}
                      </span>
                      <span className="text-xs text-gray-300 font-mono">
                        Coverage: {result.decision.fit_percentage}% | Confidence: {Math.round(result.decision.confidence_score * 100)}%
                      </span>
                      {result.decision.requires_composition && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
                          Multi-CDS Composition
                        </span>
                      )}
                    </div>
                  </div>

                  {result.decision.recommended_view && (
                    <div className="text-right">
                      <div className="text-[10px] text-gray-500">Base Candidate</div>
                      <div className="text-xs font-mono font-semibold text-blue-400">
                        {result.decision.recommended_view}
                      </div>
                    </div>
                  )}
                  {result.decision.proposed_extension_name && (
                    <div className="text-right">
                      <div className="text-[10px] text-gray-500">Proposed Extension</div>
                      <div className="text-xs font-mono font-semibold text-cyan-400">
                        {result.decision.proposed_extension_name}
                      </div>
                    </div>
                  )}
                  {result.decision.proposed_new_view_name && (
                    <div className="text-right">
                      <div className="text-[10px] text-gray-500">Proposed Custom View</div>
                      <div className="text-xs font-mono font-semibold text-amber-400">
                        {result.decision.proposed_new_view_name}
                      </div>
                    </div>
                  )}
                </div>

                <p className="text-xs text-gray-300 leading-relaxed border-t border-gray-900 pt-2.5">
                  {result.decision.rationale}
                </p>

                {/* Composition complementary views */}
                {result.decision.requires_composition && result.decision.complementary_views && (
                  <div className="p-2.5 rounded bg-indigo-950/20 border border-indigo-800/30 text-[11px] text-indigo-300 space-y-1">
                    <div className="font-medium flex items-center space-x-1">
                      <Layers className="w-3.5 h-3.5" />
                      <span>Complementary Views Composed:</span>
                    </div>
                    <div className="flex space-x-2 font-mono text-[10px]">
                      {result.decision.complementary_views.map((v) => (
                        <span key={v} className="bg-indigo-900/40 px-2 py-0.5 rounded border border-indigo-700/40">
                          {v}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Clean-Core Trade-offs & Evidence Summary */}
                {result.decision.tradeoffs && result.decision.tradeoffs.length > 0 && (
                  <div className="space-y-1 border-t border-gray-900 pt-2">
                    <div className="text-[10px] font-semibold text-gray-400">Clean-Core Architecture Trade-offs:</div>
                    <ul className="text-[11px] text-gray-400 list-disc list-inside space-y-0.5">
                      {result.decision.tradeoffs.map((t, idx) => (
                        <li key={idx}>{t}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Warnings if any */}
                {result.decision.warnings && result.decision.warnings.length > 0 && (
                  <div className="p-2.5 rounded bg-amber-500/10 border border-amber-500/20 text-[11px] text-amber-300 space-y-1">
                    <div className="font-medium flex items-center space-x-1">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                      <span>Warnings / Evidence Gaps:</span>
                    </div>
                    <ul className="list-disc list-inside space-y-0.5 text-amber-200">
                      {result.decision.warnings.map((w, idx) => (
                        <li key={idx}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Candidate Comparison Table */}
              {evaluations.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-gray-300 flex items-center justify-between">
                    <span className="flex items-center space-x-1.5">
                      <Layers className="w-3.5 h-3.5 text-blue-400" />
                      <span>Evaluated SAP CDS Candidates ({evaluations.length})</span>
                    </span>
                    <span className="text-[10px] text-gray-500">Heuristic Ranking & Hard Overrides</span>
                  </div>

                  <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-950">
                    <table className="w-full text-[11px] text-left text-gray-300">
                      <thead className="bg-gray-900/80 text-gray-400 font-semibold border-b border-gray-800">
                        <tr>
                          <th className="px-3 py-2">Rank</th>
                          <th className="px-3 py-2">Candidate CDS View</th>
                          <th className="px-3 py-2">Layer</th>
                          <th className="px-3 py-2">Coverage</th>
                          <th className="px-3 py-2">Rank Score</th>
                          <th className="px-3 py-2">Extendable</th>
                          <th className="px-3 py-2 text-right">Details</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {evaluations.map((ev) => (
                          <React.Fragment key={ev.candidate.view_name}>
                            <tr className="hover:bg-gray-900/40 transition-colors">
                              <td className="px-3 py-2 font-mono font-bold text-blue-400">#{ev.rank}</td>
                              <td className="px-3 py-2 font-mono font-medium text-gray-200">
                                {ev.candidate.view_name}
                              </td>
                              <td className="px-3 py-2">
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-300">
                                  {ev.candidate.layer}
                                </span>
                              </td>
                              <td className="px-3 py-2 font-mono">{ev.coverage_percentage}%</td>
                              <td className="px-3 py-2 font-mono">{ev.rank_score}</td>
                              <td className="px-3 py-2">
                                {ev.candidate.is_extendable ? (
                                  <span className="text-emerald-400 flex items-center space-x-0.5">
                                    <Check className="w-3 h-3" /> <span>Yes</span>
                                  </span>
                                ) : (
                                  <span className="text-rose-400 flex items-center space-x-0.5">
                                    <X className="w-3 h-3" /> <span>No</span>
                                  </span>
                                )}
                              </td>
                              <td className="px-3 py-2 text-right">
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedCandidate(
                                      expandedCandidate === ev.candidate.view_name ? null : ev.candidate.view_name
                                    )
                                  }
                                  className="text-blue-400 hover:text-blue-300 text-[10px] font-medium"
                                >
                                  {expandedCandidate === ev.candidate.view_name ? 'Hide' : 'Mappings'}
                                </button>
                              </td>
                            </tr>

                            {/* Expanded Candidate Details */}
                            {expandedCandidate === ev.candidate.view_name && (
                              <tr className="bg-gray-900/30">
                                <td colSpan={7} className="px-4 py-3 border-t border-gray-800 space-y-2">
                                  <div className="text-[11px] text-gray-400">
                                    <strong>Evaluation:</strong> {ev.suitability_reason}
                                  </div>
                                  <div className="grid grid-cols-2 gap-2 text-[10px] font-mono text-gray-400 bg-gray-950 p-2.5 rounded border border-gray-800">
                                    <div>Direct Matches: {ev.scoring_breakdown?.direct_matches_count ?? 0}</div>
                                    <div>Assoc Extensions: {ev.scoring_breakdown?.extension_matches_count ?? 0}</div>
                                    <div>Missing Concepts: {ev.scoring_breakdown?.missing_count ?? 0}</div>
                                    <div>Unresolved Targets: {ev.scoring_breakdown?.unresolved_count ?? 0}</div>
                                  </div>

                                  {/* Field mappings for candidate */}
                                  <div className="space-y-1 mt-2">
                                    <div className="text-[10px] font-semibold text-gray-300">Field Mappings:</div>
                                    <div className="space-y-1">
                                      {ev.field_mappings.map((m, idx) => (
                                        <div
                                          key={idx}
                                          className="flex items-center justify-between text-[10px] p-1.5 rounded bg-gray-950 border border-gray-800"
                                        >
                                          <div className="flex items-center space-x-2">
                                            <span className="font-semibold text-gray-200">{m.requirement_field}</span>
                                            <ArrowRight className="w-3 h-3 text-gray-500" />
                                            <span className="font-mono text-blue-400">
                                              {m.matched_field || 'None'}
                                            </span>
                                          </div>
                                          <div className="flex items-center space-x-2">
                                            {renderEvidenceBadge(m.evidence_level)}
                                            <span className="text-gray-500 text-[9px] max-w-xs truncate" title={m.evidence_detail}>
                                              {m.evidence_detail}
                                            </span>
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="p-3 rounded-lg bg-gray-950 border border-gray-800 text-[11px] text-gray-400 flex items-center space-x-2">
                  <Info className="w-4 h-4 text-blue-400 shrink-0" />
                  <span>
                    <strong>Zero Discovered Candidates:</strong> No SAP CDS objects matched search filters in repository search. No synthetic metadata was injected.
                  </span>
                </div>
              )}

              {/* Primary Field Mapping Matrix */}
              {evaluations.length > 0 && evaluations[0].field_mappings.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-gray-300 flex items-center justify-between">
                    <span>Field Mapping Matrix ({evaluations[0].candidate.view_name})</span>
                    <span className="text-[10px] text-gray-500">6-Level Semantic Evidence Hierarchy</span>
                  </div>
                  <div className="space-y-1.5">
                    {evaluations[0].field_mappings.map((m, idx) => (
                      <div
                        key={idx}
                        className="p-2.5 rounded-lg bg-gray-950 border border-gray-800 flex items-center justify-between text-xs"
                      >
                        <div className="space-y-0.5">
                          <div className="flex items-center space-x-2">
                            <span className="font-semibold text-gray-200">{m.requirement_field}</span>
                            <ArrowRight className="w-3 h-3 text-gray-500" />
                            <span className="font-mono text-blue-400">
                              {m.matched_field || 'Unmatched'}
                            </span>
                          </div>
                          <div className="text-[10px] text-gray-500">{m.evidence_detail}</div>
                        </div>
                        <div className="flex items-center space-x-2">
                          {renderEvidenceBadge(m.evidence_level)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Generated ABAP CDS Code Preview */}
              <div>
                <div className="text-xs font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                  <span>Synthesized ABAP CDS View Entity Draft Skeleton:</span>
                  <span className="text-[10px] text-amber-400 font-mono">Draft Skeleton</span>
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

