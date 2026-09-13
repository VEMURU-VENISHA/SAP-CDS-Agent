import React, { useEffect, useState } from 'react';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { MetricCards } from './components/dashboard/MetricCards';
import { RecentPipelines } from './components/dashboard/RecentPipelines';
import { StudioPreview } from './components/dashboard/StudioPreview';
import { fetchHealth } from './services/api';
import { HealthStatus } from './types';

export function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

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

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden font-sans">
      {/* Navigation Sidebar */}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header health={health} loading={loading} />

        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Executive KPI Overview */}
          <MetricCards />

          {/* Business Requirement Intake & Agent Orchestration */}
          <RecentPipelines />

          {/* Data Model Visualization & Monaco CDS Preview */}
          <StudioPreview />
        </main>
      </div>
    </div>
  );
}

export default App;
