import React from 'react';
import {
  LayoutDashboard,
  Search,
  GitBranch,
  Cpu,
  ShieldCheck,
  History,
  FileCode,
  Settings as SettingsIcon,
} from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab }) => {
  const menuItems = [
    { id: 'dashboard', label: 'Executive Overview', icon: LayoutDashboard },
    { id: 'pipeline', label: 'Agent Pipeline', icon: Cpu },
    { id: 'catalog', label: 'SAP VDM Catalog', icon: Search },
    { id: 'studio', label: 'Data Model & CDS Studio', icon: FileCode },
    { id: 'decision', label: 'Decision Matrix', icon: GitBranch },
    { id: 'governance', label: 'Approvals & Governance', icon: ShieldCheck },
    { id: 'audit', label: 'Audit Trail & Impact', icon: History },
    { id: 'settings', label: 'Landscape Settings', icon: SettingsIcon },
  ];

  return (
    <aside className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col justify-between shrink-0">
      <div className="p-4 space-y-6">
        <div className="px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-400">
          Core Workspaces
        </div>
        <nav className="space-y-1">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                    : 'text-gray-300 hover:bg-gray-800/80 hover:text-white'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-gray-400'}`} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="p-4 border-t border-gray-800 text-[11px] text-gray-500 space-y-1">
        <div>Architecture: <span className="text-gray-300">Clean Core / VDM</span></div>
        <div>Release Target: <span className="text-gray-300">S/4HANA 2023</span></div>
        <div className="text-gray-400 pt-1 font-mono">ADT Transport: None (Unconnected)</div>
      </div>
    </aside>
  );
};
