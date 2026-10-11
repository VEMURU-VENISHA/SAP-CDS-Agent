import React, { useEffect, useState } from 'react';
import { Header } from './components/layout/Header';
import { RecentPipelines } from './components/dashboard/RecentPipelines';
import { fetchHealth } from './services/api';
import { HealthStatus } from './types';

export function App() {
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
    <div className="flex flex-col h-screen bg-[#F4F8FC] text-[#172B4D] overflow-hidden font-sans">
      {/* Compact Top Header */}
      <Header health={health} loading={loading} />

      {/* Main Workflow Area — 13-Step SAP CDS Intelligence Agent */}
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 max-w-7xl mx-auto w-full">
        <RecentPipelines health={health} />
      </main>
    </div>
  );
}

export default App;
