import React, { useState } from 'react';
import { Network, Code, Layers, Info } from 'lucide-react';

export const StudioPreview: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'graph' | 'editor'>('graph');

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5 backdrop-blur mt-6">
      <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
        <div className="flex items-center space-x-2">
          <Layers className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-gray-200">
            Data Model & CDS Studio Foundation
          </span>
        </div>
        <div className="flex space-x-1 bg-gray-950 p-1 rounded-lg border border-gray-800">
          <button
            onClick={() => setActiveTab('graph')}
            className={`flex items-center space-x-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
              activeTab === 'graph' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Network className="w-3.5 h-3.5" />
            <span>Data Model Flow</span>
          </button>
          <button
            onClick={() => setActiveTab('editor')}
            className={`flex items-center space-x-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
              activeTab === 'editor' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Code className="w-3.5 h-3.5" />
            <span>Monaco CDS DDL</span>
          </button>
        </div>
      </div>

      {activeTab === 'graph' ? (
        <div className="h-64 rounded-lg bg-gray-950/70 border border-gray-800 flex flex-col items-center justify-center text-center p-6 space-y-3">
          <div className="p-3 bg-blue-500/10 rounded-full border border-blue-500/20 text-blue-400">
            <Network className="w-6 h-6" />
          </div>
          <div>
            <h4 className="text-xs font-semibold text-gray-200">React Flow Canvas Architecture</h4>
            <p className="text-[11px] text-gray-400 max-w-md mt-1">
              Visual entity-relationship canvas scaffolded with <code className="text-blue-400">@xyflow/react</code>. Ready to render live CDS View Entity nodes, associations (<code className="text-blue-400">[1..1]</code>, <code className="text-blue-400">[0..*]</code>), and join edges once SAP discovery is connected.
            </p>
          </div>
          <div className="flex items-center space-x-2 text-[10px] text-gray-400 bg-gray-900 px-3 py-1 rounded-full border border-gray-800">
            <Info className="w-3 h-3 text-amber-400" />
            <span>No real SAP discovery data loaded (System unconnected — Canvas ready for live objects)</span>
          </div>
        </div>
      ) : (
        <div className="h-64 rounded-lg bg-gray-950/70 border border-gray-800 flex flex-col items-center justify-center text-center p-6 space-y-3">
          <div className="p-3 bg-emerald-500/10 rounded-full border border-emerald-500/20 text-emerald-400">
            <Code className="w-6 h-6" />
          </div>
          <div>
            <h4 className="text-xs font-semibold text-gray-200">Monaco Editor Foundation</h4>
            <p className="text-[11px] text-gray-400 max-w-md mt-1">
              Embedded ABAP CDS DDL editor scaffolded with <code className="text-emerald-400">@monaco-editor/react</code>. Built to support CDS annotations syntax highlighting, auto-completion, and live ADT syntax check upon SAP connection.
            </p>
          </div>
          <div className="flex items-center space-x-2 text-[10px] text-gray-400 bg-gray-900 px-3 py-1 rounded-full border border-gray-800">
            <Info className="w-3 h-3 text-amber-400" />
            <span>Editor Grammar: ABAP CDS View Entities (Awaiting live SAP DDL via ADT)</span>
          </div>
        </div>
      )}
    </div>
  );
};
