'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Key, Shield, Trash2, Plus, ArrowLeft, Check, Copy } from 'lucide-react';

interface HeadlessKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string;
}

interface LlmKey {
  id: string;
  provider: string;
  created_at: string;
}

export default function ApiKeysSettingsPage() {
  const [headlessKeys, setHeadlessKeys] = useState<HeadlessKey[]>([]);
  const [llmKeys, setLlmKeys] = useState<LlmKey[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [createdLiveKey, setCreatedLiveKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // BYOK Form
  const [selectedProvider, setSelectedProvider] = useState<'ANTHROPIC' | 'GOOGLE' | 'OPENAI' | 'COHERE'>('ANTHROPIC');
  const [providerApiKey, setProviderApiKey] = useState('');
  const [byokSuccess, setByokSuccess] = useState('');

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchKeys();
  }, []);

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('agni_access_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const [hRes, lRes] = await Promise.all([
        fetch('/api/v1/keys/headless', { headers }),
        fetch('/api/v1/keys/llm', { headers })
      ]);

      if (hRes.ok) setHeadlessKeys(await hRes.json());
      if (lRes.ok) setLlmKeys(await lRes.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateHeadlessKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;

    try {
      const token = localStorage.getItem('agni_access_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch('/api/v1/keys/headless', {
        method: 'POST',
        headers,
        body: JSON.stringify({ name: newKeyName.trim(), scopes: ['read', 'write', 'sandbox', 'telemetry'] })
      });

      if (res.ok) {
        const data = await res.json();
        setCreatedLiveKey(data.api_key);
        setNewKeyName('');
        fetchKeys();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteHeadlessKey = async (id: string) => {
    try {
      const token = localStorage.getItem('agni_access_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`/api/v1/keys/headless/${id}`, { method: 'DELETE', headers });
      if (res.ok) fetchKeys();
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveLlmKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!providerApiKey.trim()) return;

    try {
      const token = localStorage.getItem('agni_access_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch('/api/v1/keys/llm', {
        method: 'POST',
        headers,
        body: JSON.stringify({ provider: selectedProvider, api_key: providerApiKey.trim() })
      });

      if (res.ok) {
        setByokSuccess(`Saved encrypted ${selectedProvider} API key to vault.`);
        setProviderApiKey('');
        setTimeout(() => setByokSuccess(''), 4000);
        fetchKeys();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteLlmKey = async (id: string) => {
    try {
      const token = localStorage.getItem('agni_access_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`/api/v1/keys/llm/${id}`, { method: 'DELETE', headers });
      if (res.ok) fetchKeys();
    } catch (e) {
      console.error(e);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '40px 24px', minHeight: '100vh' }}>
      <div style={{ marginBottom: '32px' }}>
        <Link href="/dashboard" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '14px', marginBottom: '16px' }}>
          <ArrowLeft size={16} /> Back to Dashboard
        </Link>
        <h1 style={{ fontSize: '32px', fontWeight: 800 }}>API Keys &amp; BYOK Vault</h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '6px' }}>
          Manage headless CI/CD tokens (<code style={{ color: '#ffaa00' }}>agni_sk_live_...</code>) and AES-256-GCM encrypted provider credentials.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '32px' }}>
        {/* Section 1: Headless CI/CD Keys */}
        <div className="glass-panel" style={{ padding: '28px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
            <Key size={22} color="#ff5e18" />
            <h2 style={{ fontSize: '20px', fontWeight: 700 }}>Headless API Keys</h2>
          </div>

          <form onSubmit={handleCreateHeadlessKey} style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
            <input
              className="input-field"
              type="text"
              placeholder="Key Name (e.g., GitHub Actions CI)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              required
            />
            <button type="submit" className="glow-btn" style={{ padding: '0 18px', display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}>
              <Plus size={16} /> Create
            </button>
          </form>

          {createdLiveKey && (
            <div style={{ background: 'rgba(255, 94, 24, 0.1)', border: '1px solid rgba(255, 94, 24, 0.4)', borderRadius: '8px', padding: '16px', marginBottom: '24px' }}>
              <div style={{ fontSize: '12px', color: '#ffaa00', fontWeight: 600, marginBottom: '6px' }}>
                ⚠️ Save this key now! It will never be shown again.
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#070a12', padding: '10px 12px', borderRadius: '6px' }}>
                <code style={{ fontSize: '13px', color: '#ff773d' }}>{createdLiveKey}</code>
                <button
                  type="button"
                  onClick={() => copyToClipboard(createdLiveKey)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                >
                  {copied ? <Check size={16} color="#10b981" /> : <Copy size={16} />}
                </button>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {headlessKeys.map((k) => (
              <div key={k.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0a0d16', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>{k.name}</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                    {k.key_prefix}••••••••
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteHeadlessKey(k.id)}
                  style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', padding: '4px' }}
                  title="Revoke Key"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            {headlessKeys.length === 0 && !loading && (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '24px 0' }}>
                No headless keys created yet.
              </div>
            )}
          </div>
        </div>

        {/* Section 2: BYOK Provider Vault */}
        <div className="glass-panel" style={{ padding: '28px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
            <Shield size={22} color="#00f2fe" />
            <h2 style={{ fontSize: '20px', fontWeight: 700 }}>Bring Your Own Key (BYOK)</h2>
          </div>

          <form onSubmit={handleSaveLlmKey} style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                LLM Provider
              </label>
              <select
                className="input-field"
                value={selectedProvider}
                onChange={(e: any) => setSelectedProvider(e.target.value)}
              >
                <option value="ANTHROPIC">Anthropic (Claude 3.7 Sonnet / Opus)</option>
                <option value="GOOGLE">Google Gemini (Gemini 3.8 / 2.0 Flash)</option>
                <option value="OPENAI">OpenAI (GPT-4o / GPT-5)</option>
                <option value="COHERE">Cohere (Rerank v3.5)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                Provider API Key
              </label>
              <input
                className="input-field"
                type="password"
                placeholder="sk-ant-... or AIzaSy..."
                value={providerApiKey}
                onChange={(e) => setProviderApiKey(e.target.value)}
                required
              />
            </div>

            <button type="submit" className="glow-btn" style={{ padding: '12px', fontSize: '14px' }}>
              Save Encrypted Key
            </button>
          </form>

          {byokSuccess && (
            <div style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#34d399', padding: '10px 14px', borderRadius: '8px', fontSize: '13px', marginBottom: '20px' }}>
              {byokSuccess}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>
              Configured Vault Keys
            </div>
            {llmKeys.map((k) => (
              <div key={k.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0a0d16', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div>
                  <span className="badge badge-pro">{k.provider}</span>
                  <span style={{ fontSize: '12px', color: '#10b981', marginLeft: '10px' }}>AES-256-GCM Encrypted</span>
                </div>
                <button
                  onClick={() => handleDeleteLlmKey(k.id)}
                  style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', padding: '4px' }}
                  title="Delete Provider Key"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            {llmKeys.length === 0 && !loading && (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '24px 0' }}>
                No BYOK provider keys stored. Default platform routing is used.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
