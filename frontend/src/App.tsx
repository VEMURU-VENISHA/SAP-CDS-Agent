import React, { useEffect, useState } from 'react';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { MetricCards } from './components/dashboard/MetricCards';
import { RecentPipelines } from './components/dashboard/RecentPipelines';
import { StudioPreview } from './components/dashboard/StudioPreview';
import { fetchHealth } from './services/api';
import { HealthStatus, PipelineResult, CDSDraft } from './types';

export function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [latestDraft, setLatestDraft] = useState<CDSDraft | null>(null);

  // Dynamic session metrics tracking actual user executions only
  const [metrics, setMetrics] = useState({
    totalPipelines: 0,
    reuseCount: 0,
    extendCount: 0,
    createCount: 0,
    pendingApprovals: 0,
  });

  useEffect(() => {
    let isMounted = true;
    const checkHealth = async () => {
      try {
        const data = await fetchHealth();
        if (isMounted) setHealth(data);
      } catch (err) {
        console.warn('Backend not yet reachable:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const handlePipelineExecuted = (result: PipelineResult) => {
    if (result.cds_draft) {
      setLatestDraft(result.cds_draft);
    }
    setMetrics((prev) => ({
      totalPipelines: prev.totalPipelines + 1,
      reuseCount: prev.reuseCount + (result.decision.action === 'REUSE' ? 1 : 0),
      extendCount: prev.extendCount + (result.decision.action === 'EXTEND' ? 1 : 0),
      createCount: prev.createCount + (result.decision.action === 'CREATE' ? 1 : 0),
      pendingApprovals: prev.pendingApprovals + 1,
    }));
  };

  const handleDecisionApproved = () => {
    setMetrics((prev) => ({
      ...prev,
      pendingApprovals: Math.max(0, prev.pendingApprovals - 1),
    }));
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      {/* Navigation Sidebar */}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header health={health} loading={loading} />

        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Executive KPI Overview - strictly honest empty states & real counts */}
          <MetricCards metrics={metrics} />

          {/* Business Requirement Intake & Agent Orchestration */}
          <RecentPipelines
            onPipelineExecuted={handlePipelineExecuted}
            onDecisionApproved={handleDecisionApproved}
          />

          {/* Data Model Visualization & Monaco CDS Preview */}
          <StudioPreview cdsDraft={latestDraft} />
        </main>
      </div>
    </div>
  );
}

export default App;
