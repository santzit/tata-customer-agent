'use client';

import { useEffect, useState } from 'react';
import { getAccounts, getTokenApis, saveTokenApi, Account } from '@/lib/api';

interface AccountRow extends Account {
  tokenApi: string;
  saving: boolean;
  saved: boolean;
  error: string;
}

export default function AccountsPage() {
  const [rows, setRows] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    Promise.all([getAccounts(), getTokenApis()])
      .then(([accounts, tokens]) => {
        setRows(
          accounts.map((a) => ({
            ...a,
            tokenApi: tokens[String(a.id)] ?? '',
            saving: false,
            saved: false,
            error: '',
          }))
        );
      })
      .catch((e) => setLoadError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  function updateToken(id: number, value: string) {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, tokenApi: value, saved: false, error: '' } : r))
    );
  }

  async function handleSave(id: number) {
    const row = rows.find((r) => r.id === id);
    if (!row) return;
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, saving: true, error: '' } : r)));
    try {
      await saveTokenApi(id, row.tokenApi.trim());
      setRows((prev) =>
        prev.map((r) => (r.id === id ? { ...r, saving: false, saved: true } : r))
      );
    } catch (e) {
      setRows((prev) =>
        prev.map((r) =>
          r.id === id ? { ...r, saving: false, error: String(e) } : r
        )
      );
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Accounts</h1>
        <p className="text-gray-500 mt-1">
          Accounts are retrieved directly from Chatwoot. Set the Bot Token API for each account.
        </p>
      </div>

      {loadError && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <svg className="animate-spin h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Loading accounts from Chatwoot…
        </div>
      ) : rows.length === 0 && !loadError ? (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-yellow-800 text-sm">
          No accounts found. Make sure <code className="bg-yellow-100 px-1 rounded">CHATWOOT_MASTER_TOKEN</code> is set
          and the token has access to at least one account.
        </div>
      ) : (
        <div className="space-y-4">
          {rows.map((row) => (
            <div
              key={row.id}
              className="bg-white rounded-xl border border-gray-200 shadow-sm p-6"
            >
              {/* Account header */}
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">{row.name}</h2>
                  <span className="text-xs text-gray-400">Account ID: {row.id}</span>
                </div>
                <span className="text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full font-mono">
                  #{row.id}
                </span>
              </div>

              {/* Read-only Chatwoot fields */}
              {Object.entries(row)
                .filter(([k]) => !['id', 'name', 'tokenApi', 'saving', 'saved', 'error'].includes(k))
                .slice(0, 4)
                .map(([k, v]) => (
                  <div key={k} className="flex gap-2 text-xs text-gray-500 mb-1">
                    <span className="font-medium text-gray-600 capitalize min-w-[80px]">
                      {k.replace(/_/g, ' ')}:
                    </span>
                    <span className="font-mono truncate">{String(v ?? '—')}</span>
                  </div>
                ))}

              {/* Bot Token API */}
              <div className="mt-4 pt-4 border-t border-gray-100">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Bot Token API
                  <span className="ml-2 text-xs text-gray-400 font-normal">
                    (stored locally, used for bot message authentication)
                  </span>
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={row.tokenApi}
                    onChange={(e) => updateToken(row.id, e.target.value)}
                    placeholder="Enter bot token API…"
                    className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    onClick={() => handleSave(row.id)}
                    disabled={row.saving}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium rounded-lg text-sm transition-colors whitespace-nowrap"
                  >
                    {row.saving ? 'Saving…' : 'Save'}
                  </button>
                </div>
                {row.saved && (
                  <p className="mt-1.5 text-xs text-green-600">✅ Saved successfully</p>
                )}
                {row.error && (
                  <p className="mt-1.5 text-xs text-red-600">❌ {row.error}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
