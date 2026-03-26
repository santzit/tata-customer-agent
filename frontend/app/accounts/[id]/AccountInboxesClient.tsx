'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getAccountInboxes, syncAccountInboxes, DbInbox } from '@/lib/api';

export default function AccountInboxesClient() {
  const params = useParams();
  const accountId = Number(params.id);

  const [inboxes, setInboxes] = useState<DbInbox[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');

  const loadInboxes = useCallback(() => {
    setLoading(true);
    setLoadError('');
    getAccountInboxes(accountId)
      .then(setInboxes)
      .catch((e) => setLoadError(String(e)))
      .finally(() => setLoading(false));
  }, [accountId]);

  useEffect(() => {
    loadInboxes();
  }, [loadInboxes]);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg('');
    try {
      const result = await syncAccountInboxes(accountId);
      setSyncMsg(`✅ Synced ${result.synced} inbox(es) from Chatwoot`);
      loadInboxes();
    } catch (e) {
      setSyncMsg(`❌ Sync failed: ${String(e)}`);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      {/* Breadcrumb */}
      <div className="mb-4 text-sm text-gray-500 flex items-center gap-1">
        <Link href="/accounts" className="hover:text-indigo-600">Accounts</Link>
        <span>/</span>
        <span className="text-gray-800 font-medium">Account #{accountId} — Inboxes</span>
      </div>

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Inboxes</h1>
          <p className="text-gray-500 mt-1 text-sm">
            Inboxes for account <strong>#{accountId}</strong>. Click <strong>Sync from Chatwoot</strong> to import.
            Click an inbox to view its Help Center articles.
          </p>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="ml-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium rounded-lg text-sm transition-colors whitespace-nowrap flex items-center gap-2"
        >
          {syncing ? (
            <>
              <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Syncing…
            </>
          ) : (
            '🔄 Sync from Chatwoot'
          )}
        </button>
      </div>

      {syncMsg && (
        <div className={`mb-4 p-3 rounded-lg text-sm ${syncMsg.startsWith('✅') ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {syncMsg}
        </div>
      )}

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
          Loading inboxes…
        </div>
      ) : inboxes.length === 0 && !loadError ? (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-yellow-800 text-sm">
          No inboxes found for this account. Click <strong>Sync from Chatwoot</strong> to import inboxes.
        </div>
      ) : (
        <div className="space-y-3">
          {inboxes.map((inbox) => (
            <Link
              key={inbox.id}
              href={`/accounts/${accountId}/${inbox.id}`}
              className="block bg-white rounded-xl border border-gray-200 shadow-sm p-5 hover:border-indigo-300 hover:shadow-md transition-all group"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-gray-900 group-hover:text-indigo-600">
                    {inbox.name}
                  </h2>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs text-gray-400">Inbox ID: {inbox.id}</span>
                    {inbox.portal_slug ? (
                      <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
                        📚 HC: {inbox.portal_slug}
                      </span>
                    ) : (
                      <span className="text-xs bg-gray-50 text-gray-500 border border-gray-200 px-2 py-0.5 rounded-full">
                        No Help Center linked
                      </span>
                    )}
                  </div>
                </div>
                <span className="text-gray-400 group-hover:text-indigo-500 text-lg">→</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
