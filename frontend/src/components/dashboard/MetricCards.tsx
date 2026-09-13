import React from 'react';
import { RefreshCw, PlusCircle, CheckCircle2, ShieldAlert } from 'lucide-react';

export const MetricCards: React.FC = () => {
  const cards = [
    {
      title: 'REUSE Ratio (VDM First)',
      value: '78.4%',
      subtitle: 'Target: >75% Standard View Reuse',
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/20',
    },
    {
      title: 'EXTEND Proposals',
      value: '14',
      subtitle: 'CDS View Entity Extensions',
      icon: RefreshCw,
      color: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
      borderColor: 'border-blue-500/20',
    },
    {
      title: 'CREATE Proposals',
      value: '5',
      subtitle: 'Custom View Entities (Z_*)',
      icon: PlusCircle,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      borderColor: 'border-amber-500/20',
    },
    {
      title: 'Pending Human Approvals',
      value: '2',
      subtitle: 'Senior Architect Sign-off Gate',
      icon: ShieldAlert,
      color: 'text-purple-400',
      bgColor: 'bg-purple-500/10',
      borderColor: 'border-purple-500/20',
    },
  ];

  return (
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
              <div className="text-2xl font-bold text-gray-100">{card.value}</div>
              <div className="text-[11px] text-gray-400 mt-1">{card.subtitle}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
