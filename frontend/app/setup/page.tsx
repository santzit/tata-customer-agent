'use client';

import { useEffect, useState } from 'react';
import { getAccounts, getInboxes, saveTokenApi, Account, Inbox } from '@/lib/api';
import Link from 'next/link';

export default function SetupPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<number | ''>('');
  const [selectedInbox, setSelectedInbox] = useState<number | ''>('');
  const [tokenApi, setTokenApi] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingInboxes, setLoadingInboxes] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getAccounts()
      .then(setAccounts)
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingAccounts(false));
  }, []);

  useEffect(() => {
    if (selectedAccount === '') {
      setInboxes([]);
      return;
    }
    setLoadingInboxes(true);
    getInboxes(Number(selectedAccount))
      .then(setInboxes)
      .catch(() => setInboxes([]))
      .finally(() => setLoadingInboxes(false));
  }, [selectedAccount]);

  async function handleSave() {
    if (selectedAccount === '' || !tokenApi.trim()) {
      setSaveMsg('Please select an account and enter a Token API.');
      return;
    }
    setSaving(true);
    setSaveMsg('');
    try {
      await saveTokenApi(Number(selectedAccount), tokenApi.trim());
      setSaveMsg('✅ Configuration saved successfully!');
    } catch (e) {
      setSaveMsg(`❌ Error: ${String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Setup</h1>
        <p className="text-gray-500 mt-1">
          Select an account and inbox from your Chatwoot instance, then set the bot Token API.
        </p>
      </div>

      {/* Step 1 — Account & Inbox (loaded from Chatwoot) */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 mb-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
            1
          </span>
          <h2 className="text-lg font-semibold text-gray-800">Chatwoot Account &amp; Inbox</h2>
        </div>
        <p className="text-xs text-gray-400 mb-5 ml-11">
          Accounts and inboxes are read directly from your Chatwoot instance via{' '}
          <code className="bg-gray-100 px-1 rounded">CHATWOOT_MASTER_TOKEN</code>.
        </p>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Account</label>
            {loadingAccounts ? (
              <div className="text-sm text-gray-400">Loading accounts from Chatwoot…</div>
            ) : (
              <select
                value={selectedAccount}
                onChange={(e) => {
                  setSelectedAccount(e.target.value === '' ? '' : Number(e.target.value));
                  setSelectedInbox('');
                }}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Select account —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} (#{a.id})
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Inbox <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            {loadingInboxes ? (
              <div className="text-sm text-gray-400">Loading inboxes…</div>
            ) : (
              <select
                value={selectedInbox}
                onChange={(e) =>
                  setSelectedInbox(e.target.value === '' ? '' : Number(e.target.value))
                }
                disabled={selectedAccount === ''}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
              >
                <option value="">— Select inbox —</option>
                {inboxes.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name} (#{i.id})
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
      </div>

      {/* Step 2 — Bot Token API */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 mb-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
            2
          </span>
          <h2 className="text-lg font-semibold text-gray-800">Bot Token API</h2>
        </div>
        <p className="text-xs text-gray-400 mb-5 ml-11">
          The Token API is used by the Tata bot to authenticate its API responses.
          It is stored per Chatwoot account in the local database.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Token API
            </label>
            <input
              type="text"
              value={tokenApi}
              onChange={(e) => setTokenApi(e.target.value)}
              placeholder="Enter the bot Token API value"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">
              This is the <strong>bot's</strong> response token — not your Chatwoot user API key.
              Stored in the local DB and linked to the selected account above.
            </p>
          </div>

          {saveMsg && (
            <div
              className={`p-3 rounded-lg text-sm ${
                saveMsg.startsWith('✅')
                  ? 'bg-green-50 border border-green-200 text-green-700'
                  : 'bg-red-50 border border-red-200 text-red-700'
              }`}
            >
              {saveMsg}
            </div>
          )}

          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {saving ? 'Saving…' : 'Save Configuration'}
          </button>
        </div>
      </div>

      {/* Step 3 — OpenAI */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <div className="flex items-center gap-3 mb-3">
          <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
            3
          </span>
          <h2 className="text-lg font-semibold text-gray-800">OpenAI Configuration</h2>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Configure your OpenAI API key and model settings for the AI agent.
        </p>
        <Link
          href="/openai"
          className="inline-flex items-center gap-2 bg-gray-900 hover:bg-gray-700 text-white font-medium py-2.5 px-5 rounded-lg text-sm transition-colors"
        >
          Go to OpenAI Config →
        </Link>
      </div>
    </div>
  );
}
