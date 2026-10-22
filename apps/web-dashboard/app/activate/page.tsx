'use client';

import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { Terminal, ShieldCheck, CheckCircle2 } from 'lucide-react';
import Link from 'next/link';

export default function ActivateDevicePage() {
  const searchParams = useSearchParams();
  const initialCode = searchParams.get('code') || '';

  const [userCode, setUserCode] = useState(initialCode);
  const [loading, setLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [error, setError] = useState('');
  const [token, setToken] = useState('');

  useEffect(() => {
    const storedToken = localStorage.getItem('agni_access_token');
    if (storedToken) {
      setToken(storedToken);
    }
  }, []);

  const handleApprove = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const res = await fetch('/api/v1/auth/device/approve', {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_code: userCode.trim().toUpperCase() }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Authorization failed. Please ensure the code is valid.');
      }

      setSuccessMessage(data.message || 'Machine authorized successfully!');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
      <div className="glass-panel" style={{ width: '100%', maxWidth: '480px', padding: '36px' }}>
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <div style={{ width: '50px', height: '50px', borderRadius: '12px', background: 'rgba(255, 94, 24, 0.15)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: '12px' }}>
            <Terminal size={26} color="#ff5e18" />
          </div>
          <h2 style={{ fontSize: '22px', fontWeight: 700 }}>Authorize Terminal or IDE</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '4px' }}>
            RFC 8628 OAuth 2.0 Device Flow
          </p>
        </div>

        {error && (
          <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#f87171', padding: '12px', borderRadius: '8px', fontSize: '13px', marginBottom: '20px' }}>
            {error}
          </div>
        )}

        {successMessage ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <CheckCircle2 size={48} color="#10b981" style={{ margin: '0 auto 16px auto' }} />
            <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#34d399', marginBottom: '8px' }}>
              Machine Authorized!
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '24px' }}>
              Your terminal has received its Ed25519 session credentials and is ready to run autonomous coding workflows.
            </p>
            <Link href="/dashboard" className="glow-btn" style={{ padding: '10px 20px', display: 'inline-block' }}>
              Go to Observability Dashboard
            </Link>
          </div>
        ) : (
          <form onSubmit={handleApprove} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '8px', textAlign: 'center' }}>
                Confirmation Code shown in your terminal (<code style={{ color: '#ff8c42' }}>agni login</code>)
              </label>
              <input
                className="input-field"
                type="text"
                required
                maxLength={9}
                value={userCode}
                onChange={(e) => setUserCode(e.target.value)}
                placeholder="ABCD-EFGH"
                style={{ textAlign: 'center', fontSize: '24px', letterSpacing: '4px', textTransform: 'uppercase', fontWeight: 700 }}
              />
            </div>

            <div style={{ background: '#0a0d16', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '12px', color: 'var(--text-muted)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', color: 'var(--text-main)', fontWeight: 600 }}>
                <ShieldCheck size={16} color="#00f2fe" /> Secure Asymmetric Auth Handshake
              </div>
              Authorizing will issue a cryptographic token pair allowing local CLI commands to verify in &lt;1ms without calling the database.
            </div>

            <button type="submit" className="glow-btn" disabled={loading || !userCode.trim()} style={{ padding: '13px', fontSize: '15px' }}>
              {loading ? 'Authorizing Machine...' : 'Authorize Machine'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
