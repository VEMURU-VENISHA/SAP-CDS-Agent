import React from 'react';
import { HealthStatus } from '../../types';

interface HeaderProps {
  health: HealthStatus | null;
  loading: boolean;
}

export const Header: React.FC<HeaderProps> = ({ health, loading }) => {
  const isAdtConnected = health?.sap_connector?.is_connected ?? false;
  const isBackendOnline = health?.status === 'healthy';
  const systemId = health?.sap_connector?.system_id || 'DEV';
  const clientId = health?.sap_connector?.client || '100';

  return (
    <header className="h-16 bg-white border-b border-[#D9E4F0] flex items-center justify-between px-6 z-10 sticky top-0 shadow-xs">
      {/* Title and Logo */}
      <div className="flex items-center space-x-3">
        <div className="h-9 w-9 rounded-lg bg-[#0A6ED1] text-white flex items-center justify-center font-bold text-base shadow-sm">
          ⚡
        </div>
        <div>
          <h1 className="text-sm font-bold text-[#0F2747] leading-none">
            SAP CDS Intelligence Agent
          </h1>
          <p className="text-[11px] text-[#5F7187] font-medium mt-1">
            Clean Core VDM Discovery &amp; Automated ABAP Creation
          </p>
        </div>
      </div>

      {/* Target System & Status Badges */}
      <div className="flex items-center space-x-3 text-xs">
        {/* Environment badge */}
        <div className="px-3 py-1.5 rounded-lg bg-[#F4F8FC] border border-[#D9E4F0] text-[#172B4D] font-medium flex items-center gap-1.5">
          <span className="text-[#5F7187]">Environment:</span>
          <span className="text-[#0A6ED1] font-mono font-semibold">
            SAP S/4HANA {systemId} Client {clientId}
          </span>
        </div>

        {/* SAP ADT Status badge */}
        <div
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border font-medium transition ${
            isAdtConnected
              ? 'bg-[#E8F8F3] text-[#00A878] border-[#00A878]/30'
              : 'bg-amber-50 text-amber-700 border-amber-300'
          }`}
        >
          <span
            className={`w-2 h-2 rounded-full inline-block ${
              isAdtConnected ? 'bg-[#00A878] animate-pulse' : 'bg-amber-500'
            }`}
          />
          <span>{isAdtConnected ? 'SAP ADT Connected' : 'SAP ADT Guardrail Mode'}</span>
        </div>

        {/* Backend health status indicator */}
        <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#F4F8FC] border border-[#D9E4F0] font-medium">
          <span className="text-[#5F7187]">Backend</span>
          {loading ? (
            <span className="text-[#5F7187] animate-pulse">Checking...</span>
          ) : isBackendOnline ? (
            <span className="flex items-center text-[#00A878]">
              <span className="w-2 h-2 rounded-full bg-[#00A878] inline-block mr-1.5 animate-pulse" />
              Online
            </span>
          ) : (
            <span className="flex items-center text-red-600">
              <span className="w-2 h-2 rounded-full bg-red-600 inline-block mr-1.5" />
              Offline
            </span>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;

