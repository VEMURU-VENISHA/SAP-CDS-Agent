import React from 'react';
import { ShieldCheck, Server, AlertTriangle } from 'lucide-react';
import { HealthStatus } from '../../types';

interface HeaderProps {
  health: HealthStatus | null;
  loading: boolean;
}

export const Header: React.FC<HeaderProps> = ({ health, loading }) => {
  return (
    <header className="h-16 bg-gray-900/80 backdrop-blur border-b border-gray-800 flex items-center justify-between px-6 z-10 sticky top-0">
      <div className="flex items-center space-x-3">
        <div className="h-9 w-9 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400 font-bold text-lg shadow-sm">
          ⚡
        </div>
        <div>
          <h1 className="text-base font-semibold text-gray-100 leading-tight">
            SAP CDS Intelligence & Automation Platform
          </h1>
          <p className="text-xs text-gray-400">
            Target System: <span className="text-blue-400 font-mono">DEV (Client 100)</span> | Release: <span className="text-gray-300">S/4HANA 2023 (S4CORE 108 SP03)</span>
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        {/* Guardrail badge */}
        <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-300 border border-amber-500/30">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Milestone 1: Unconnected Guardrail Active</span>
        </div>

        {/* Backend health status indicator */}
        <div className="flex items-center space-x-2 px-3 py-1 rounded-md bg-gray-800/80 border border-gray-700 text-xs">
          <Server className="w-3.5 h-3.5 text-gray-400" />
          <span className="text-gray-400">Backend:</span>
          {loading ? (
            <span className="text-gray-500 animate-pulse">Connecting...</span>
          ) : health?.status === 'healthy' ? (
            <span className="flex items-center text-emerald-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block mr-1.5 animate-pulse"></span>
              Online (v{health.version})
            </span>
          ) : (
            <span className="text-red-400 font-medium">Offline</span>
          )}
        </div>

        {/* User profile avatar */}
        <div className="flex items-center space-x-2 border-l border-gray-800 pl-4">
          <div className="h-8 w-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white text-xs font-semibold">
            AD
          </div>
          <div className="text-left hidden md:block">
            <div className="text-xs font-medium text-gray-200">ABAP Lead Architect</div>
            <div className="text-[10px] text-gray-400">Senior Reviewer</div>
          </div>
        </div>
      </div>
    </header>
  );
};
