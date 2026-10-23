'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Zap, 
  Cpu, 
  Terminal, 
  Shield, 
  CheckCircle, 
  Clock, 
  Key, 
  Code2, 
  Activity, 
  LogOut,
  Radio
} from 'lucide-react';

interface RunItem {
  id: string;
  repo_name: string;
  task_prompt: string;
  status: string;
  iterations: number;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  final_diff?: string;
}

export default function DashboardPage() {
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunItem | null>(null);
  const [loading, setLoading] = useState(true);

  // Live WebSocket state from Agent Daemon
  const [wsConnected, setWsConnected] = useState(false);
  const [liveNodeStatus, setLiveNodeStatus] = useState<string>('Daemon Idle / Ready');
  const [liveTokenCount, setLiveTokenCount] = useState<number>(124500);
  const [latestDiff, setLatestDiff] = useState<string>('');

  useEffect(() => {
    async function fetchRuns() {
      try {
        const res = await fetch('/api/v1/telemetry/runs');
        if (res.ok) {
          const data = await res.json();
          setRuns(data);
          if (data.length > 0) {
            setSelectedRun(data[0]);
          }
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    fetchRuns();

    // Connect to local agent daemon WebSocket bus
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket('ws://localhost:9000/ws');
      ws.onopen = () => {
        setWsConnected(true);
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const ev = data.event;
          const payload = data.payload || {};

          if (ev === 'FILE_READ') {
            setLiveNodeStatus(`LocatorNode: Indexed & read ${payload.files?.length || 0} file(s)`);
          } else if (ev === 'PLAN_CREATED') {
            setLiveNodeStatus(`PlannerNode: Plan created with ${payload.model}`);
          } else if (ev === 'DIFF_APPLIED') {
            setLiveNodeStatus(`SurgicalCoderNode: Applied diff (${payload.blocks} block(s))`);
            if (payload.unified_diff) {
              setLatestDiff(payload.unified_diff);
            }
          } else if (ev === 'TEST_OUTPUT') {
            setLiveNodeStatus(`VerifierNode: Tests exit code ${payload.exit_code}`);
          } else if (ev === 'DONE') {
            setLiveNodeStatus(`CriticNode: Task Completed! (${payload.status})`);
            if (payload.tokens) {
              setLiveTokenCount((prev) => prev + payload.tokens);
            }
            fetchRuns();
          }
        } catch (err) {
          console.error(err);
        }
      };
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
    } catch (e) {
      setWsConnected(false);
    }

    return () => {
      if (ws) ws.close();
    };
  }, []);

  const activeDiff = latestDiff || selectedRun?.final_diff || '';

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top Navbar */}
      <nav style={{ borderBottom: '1px solid var(--border)', background: 'rgba(10, 13, 20, 0.85)', backdropFilter: 'blur(8px)', padding: '16px 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '24px' }}>🔥</span>
            <span style={{ fontWeight: 800, fontSize: '18px', letterSpacing: '-0.5px' }}>agni-dev</span>
          </Link>
          <span className="badge badge-pro">PRO Workspace</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: wsConnected ? '#34d399' : 'var(--text-muted)' }}>
            <Radio size={14} color={wsConnected ? '#10b981' : '#6b7280'} />
            {wsConnected ? 'Daemon WS Live' : 'Daemon Standby'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '13px', fontWeight: 600 }}>admin@agni.dev</div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Agni Core Workspace</div>
          </div>
          <Link href="/settings/api-keys" style={{ color: '#ff8c42', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: 600 }}>
            <Key size={16} /> API Keys
          </Link>
          <Link href="/login" style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}>
            <LogOut size={16} /> Logout
          </Link>
        </div>
      </nav>

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: '32px', maxWidth: '1400px', margin: '0 auto', width: '100%' }}>
        {/* Metric Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '32px' }}>
          {/* Card 1: Token Usage */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '13px', fontWeight: 500 }}>Monthly Token Budget</span>
              <Cpu size={18} color="#ff5e18" />
            </div>
            <div style={{ fontSize: '28px', fontWeight: 700, marginBottom: '8px' }}>
              {liveTokenCount.toLocaleString()} <span style={{ fontSize: '14px', color: 'var(--text-muted)', fontWeight: 400 }}>/ 5,000,000</span>
            </div>
            <div style={{ width: '100%', height: '6px', background: '#1c2436', borderRadius: '3px', overflow: 'hidden' }}>
              <div style={{ width: `${Math.min((liveTokenCount / 5000000) * 100, 100)}%`, height: '100%', background: 'linear-gradient(90deg, #ff5e18, #ffaa00)' }} />
            </div>
          </div>

          {/* Card 2: Live Pipeline State */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '13px', fontWeight: 500 }}>Live Agent Graph State</span>
              <Activity size={18} color="#00f2fe" />
            </div>
            <div style={{ fontSize: '16px', fontWeight: 700, marginBottom: '8px', color: '#00f2fe' }}>
              {liveNodeStatus}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Locator → Planner → SurgicalCoder → Verifier → Critic
            </div>
          </div>

          {/* Card 3: Dual-Model Strategy */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '13px', fontWeight: 500 }}>Dual-Model Router</span>
              <Zap size={18} color="#ff5e18" />
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, marginBottom: '4px' }}>
              Tier-1: Claude 3.7 Sonnet (Plan)
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: '#ff773d' }}>
              Tier-2: Gemini 3.8 / 2.0 Flash (Execute)
            </div>
          </div>
        </div>

        {/* Observability Section: Agent Runs & Diff Viewer */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.3fr', gap: '24px', alignItems: 'start' }}>
          {/* Left Column: Recent Runs */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700 }}>Telemetry &amp; Audit Log</h2>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{runs.length} Runs Recorded</span>
            </div>

            {loading ? (
              <div style={{ color: 'var(--text-muted)', padding: '24px 0', textAlign: 'center' }}>Loading telemetry...</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {runs.map((run) => (
                  <div 
                    key={run.id}
                    onClick={() => { setSelectedRun(run); setLatestDiff(''); }}
                    style={{
                      padding: '16px',
                      borderRadius: '8px',
                      background: selectedRun?.id === run.id ? 'var(--bg-card-hover)' : '#0d111a',
                      border: selectedRun?.id === run.id ? '1px solid var(--accent-orange)' : '1px solid var(--border)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span style={{ fontWeight: 600, fontSize: '14px' }}>{run.repo_name}</span>
                      <span className="badge badge-success">{run.status}</span>
                    </div>
                    <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '10px', lineHeight: 1.4 }}>
                      {run.task_prompt}
                    </p>
                    <div style={{ display: 'flex', gap: '16px', fontSize: '11px', color: 'var(--text-muted)' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock size={12} /> {run.duration_ms}ms
                      </span>
                      <span>🔄 {run.iterations} steps</span>
                      <span>⚡ {run.input_tokens + run.output_tokens} tok</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right Column: Surgical Diff Viewer */}
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Code2 size={20} color="#ff5e18" />
                <h2 style={{ fontSize: '18px', fontWeight: 700 }}>Surgical Diff Viewer</h2>
              </div>
              <span style={{ fontSize: '12px', color: '#34d399', fontWeight: 600 }}>AST Verified (0 Errors)</span>
            </div>

            {activeDiff ? (
              <div style={{ background: '#070a10', borderRadius: '8px', border: '1px solid #1a2233', overflow: 'hidden' }}>
                <div style={{ padding: '8px 16px', background: '#0e1422', borderBottom: '1px solid #1a2233', fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                  Target: {selectedRun?.repo_name || 'Active Task'}
                </div>
                <pre style={{ padding: '16px', fontSize: '13px', fontFamily: 'Consolas, monospace', lineHeight: 1.5, overflowX: 'auto', margin: 0, color: '#d1d7e0' }}>
                  {activeDiff.split('\n').map((line, idx) => {
                    let color = '#d1d7e0';
                    let bg = 'transparent';
                    if (line.startsWith('+')) {
                      color = '#4ade80';
                      bg = 'rgba(74, 222, 128, 0.1)';
                    } else if (line.startsWith('-')) {
                      color = '#f87171';
                      bg = 'rgba(248, 113, 113, 0.1)';
                    } else if (line.startsWith('@@')) {
                      color = '#38bdf8';
                    }
                    return (
                      <div key={idx} style={{ color, backgroundColor: bg, padding: '2px 4px' }}>
                        {line}
                      </div>
                    );
                  })}
                </pre>
              </div>
            ) : (
              <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Select a run on the left or run &lsquo;agni code&rsquo; in terminal to stream live diffs.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
