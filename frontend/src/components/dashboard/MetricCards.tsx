import React from 'react';
import { RefreshCw, PlusCircle, CheckCircle2, ShieldAlert, Info } from 'lucide-react';

interface MetricCardsProps {
  metrics?: {
    totalPipelines: number;
    reuseCount: number;
    extendCount: number;
    createCount: number;
    pendingApprovals: number;
  };
}

export const MetricCards: React.FC<MetricCardsProps> = ({ metrics }) => {
  const hasRuns = (metrics?.totalPipelines ?? 0) > 0;
  const reuseRatio = hasRuns
    ? `${(((metrics?.reuseCount ?? 0) / (metrics?.totalPipelines || 1)) * 100).toFixed(0)}%`
    : '—';

  const cards = [
    {
      title: 'REUSE Ratio (VDM First)',
      value: reuseRatio,
      subtitle: hasRuns ? 'Actual standard view reuse' : 'No pipeline runs yet',
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/20',
    },
    {
      title: 'EXTEND Proposals',
      value: String(metrics?.extendCount ?? 0),
      subtitle: hasRuns
        ? `${metrics?.extendCount} extension(s) proposed`
        : '0 — based on actual processed requirements',
      icon: RefreshCw,
      color: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
      borderColor: 'border-blue-500/20',
    },
    {
      title: 'CREATE Proposals',
      value: String(metrics?.createCount ?? 0),
      subtitle: hasRuns
        ? `${metrics?.createCount} custom view(s) proposed`
        : '0 — based on actual processed requirements',
      icon: PlusCircle,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      borderColor: 'border-amber-500/20',
    },
    {
      title: 'Pending Human Approvals',
      value: String(metrics?.pendingApprovals ?? 0),
      subtitle: hasRuns
        ? `${metrics?.pendingApprovals} awaiting review`
        : '0 — based on actual processed requirements',
      icon: ShieldAlert,
      color: 'text-purple-400',
      bgColor: 'bg-purple-500/10',
      borderColor: 'border-purple-500/20',
    },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[11px] text-gray-500 px-1">
        <span className="flex items-center space-x-1.5">
          <Info className="w-3.5 h-3.5 text-gray-400" />
          <span>Operational Metrics: strictly reflects real processed requirements (No fabricated demo data)</span>
        </span>
        <span>Target System: Unconnected</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <div
              key={idx}
              className={`p-5 rounded-xl bg-gray-900/60 border ${card.borderColor} backdrop-blur shadow-sm hover:border-gray-600 transition-colors`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-400">{card.title}</span>
                <div className={`p-2 rounded-lg ${card.bgColor}`}>
                  <Icon className={`w-4 h-4 ${card.color}`} />
                </div>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-bold text-gray-100 font-mono">{card.value}</div>
                <div className="text-[11px] text-gray-400 mt-1">{card.subtitle}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
