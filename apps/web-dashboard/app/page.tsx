'use client';

import React from 'react';
import Link from 'next/link';
import { Terminal, Shield, Zap, Box, ArrowRight } from 'lucide-react';

export default function HomePage() {
  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 24px' }}>
      {/* Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '80px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: '10px', background: 'linear-gradient(135deg, #ff5e18, #ff8c42)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: '20px' }}>
            🔥
          </div>
          <span style={{ fontSize: '22px', fontWeight: 'bold', letterSpacing: '-0.5px' }}>agni-dev</span>
        </div>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <Link href="/login" style={{ color: 'var(--text-muted)', fontSize: '14px', fontWeight: 500 }}>Sign In</Link>
          <Link href="/activate" style={{ color: '#ff8c42', fontSize: '14px', fontWeight: 600 }}>Activate Machine</Link>
          <Link href="/dashboard" className="glow-btn" style={{ padding: '8px 18px', fontSize: '14px' }}>Dashboard</Link>
        </div>
      </header>

      {/* Hero */}
      <section style={{ textAlign: 'center', marginBottom: '80px' }}>
        <div className="badge badge-pro" style={{ marginBottom: '20px' }}>Fast Coding Agent Engine</div>
        <h1 style={{ fontSize: '56px', fontWeight: 800, lineHeight: 1.15, marginBottom: '24px', letterSpacing: '-1.5px' }}>
          Autonomous Code Intelligence, <br />
          <span style={{ background: 'linear-gradient(135deg, #ff5e18, #ffaa00)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            Decoupled for Speed.
          </span>
        </h1>
        <p style={{ fontSize: '18px', color: 'var(--text-muted)', maxWidth: '680px', margin: '0 auto 40px auto', lineHeight: 1.6 }}>
          Run the exact same LangGraph + Tree-sitter AST engine headlessly in GitHub Actions, interactively in your terminal via <code style={{ color: '#ffaa00', background: '#1c2233', padding: '2px 6px', borderRadius: '4px' }}>agni code</code>, or on your Web Dashboard.
        </p>

        <div style={{ display: 'flex', gap: '16px', justifyContent: 'center' }}>
          <Link href="/signup" className="glow-btn" style={{ padding: '14px 28px', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            Get Started Free <ArrowRight size={18} />
          </Link>
          <Link href="/activate" className="glass-panel" style={{ padding: '14px 28px', fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Terminal size={18} color="#ff8c42" /> Connect Terminal (agni login)
          </Link>
        </div>
      </section>

      {/* Features Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '20px', marginBottom: '80px' }}>
        <div className="glass-panel" style={{ padding: '28px' }}>
          <Zap size={28} color="#ff5e18" style={{ marginBottom: '16px' }} />
          <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px' }}>Dual-Model Router</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.5 }}>
            Tier-1 Architect scopes problems; Tier-2 Fast Executor performs mechanical edits at 250+ tokens/sec.
          </p>
        </div>

        <div className="glass-panel" style={{ padding: '28px' }}>
          <Shield size={28} color="#00f2fe" style={{ marginBottom: '16px' }} />
          <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px' }}>Sub-ms Ed25519 Auth</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.5 }}>
            Zero-latency asymmetric JWT verification on the local daemon backed by RFC 8628 Device Flow.
          </p>
        </div>

        <div className="glass-panel" style={{ padding: '28px' }}>
          <Box size={28} color="#10b981" style={{ marginBottom: '16px' }} />
          <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px' }}>Pre-Warmed Sandbox</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.5 }}>
            Docker sandbox pool executes tests in ~30ms with automatic stderr trace compression.
          </p>
        </div>
      </div>
    </div>
  );
}
