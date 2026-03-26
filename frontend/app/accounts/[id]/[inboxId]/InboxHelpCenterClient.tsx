'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getInboxHelpCenter, syncHelpCenter, Article } from '@/lib/api';

export default function InboxHelpCenterClient() {
  const params = useParams();
  const accountId = Number(params.id);
  const inboxId = Number(params.inboxId);

  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const [search, setSearch] = useState('');
  const [locale, setLocale] = useState('');
  const [selected, setSelected] = useState<Article | null>(null);

  const loadArticles = useCallback(() => {
    setLoading(true);
    setLoadError('');
    getInboxHelpCenter(accountId, inboxId, search || undefined, locale || undefined)
      .then(setArticles)
      .catch((e) => setLoadError(String(e)))
      .finally(() => setLoading(false));
  }, [accountId, inboxId, search, locale]);

  useEffect(() => {
    loadArticles();
  }, [loadArticles]);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg('');
    try {
      const result = await syncHelpCenter(accountId);
      setSyncMsg(`✅ Synced ${result.synced} article(s) from Chatwoot Help Center`);
      loadArticles();
    } catch (e) {
      setSyncMsg(`❌ Sync failed: ${String(e)}`);
    } finally {
      setSyncing(false);
    }
  }

  const locales = articles
    .map((article) => article.locale)
    .filter((value): value is string => Boolean(value))
    .reduce<string[]>((unique, value) => (unique.includes(value) ? unique : [...unique, value]), []);

  return (
    <div className="max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <div className="mb-4 text-sm text-gray-500 flex items-center gap-1 flex-wrap">
        <Link href="/accounts" className="hover:text-indigo-600">Accounts</Link>
        <span>/</span>
        <Link href={`/accounts/${accountId}`} className="hover:text-indigo-600">Account #{accountId}</Link>
        <span>/</span>
        <span className="text-gray-800 font-medium">Inbox #{inboxId} — Help Center</span>
      </div>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Help Center</h1>
          <p className="text-gray-500 mt-1 text-sm">
            Articles associated with Inbox <strong>#{inboxId}</strong> (filtered by linked portal).
            These articles are used as RAG context for this inbox.
          </p>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="ml-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium rounded-lg text-sm transition-colors whitespace-nowrap flex items-center gap-2 shrink-0"
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
            '🔄 Sync HC from Chatwoot'
          )}
        </button>
      </div>

      {syncMsg && (
        <div className={`mb-4 p-3 rounded-lg text-sm ${syncMsg.startsWith('✅') ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {syncMsg}
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search articles…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px] focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <select
          value={locale}
          onChange={(e) => setLocale(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">All locales</option>
          {locales.map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </select>
      </div>

      {loadError && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {loadError}
        </div>
      )}

      <div className="flex gap-4 h-[calc(100vh-300px)] min-h-[400px]">
        {/* Left panel: article list */}
        <div className="w-1/2 overflow-y-auto space-y-2 pr-2">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm p-4">
              <svg className="animate-spin h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Loading articles…
            </div>
          ) : articles.length === 0 ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-yellow-800 text-sm">
              {search || locale
                ? 'No articles match the filters.'
                : 'No articles linked to this inbox. Click Sync HC from Chatwoot, then make sure this inbox has a linked portal.'}
            </div>
          ) : (
            articles.map((article) => (
              <button
                key={String(article.id)}
                onClick={() => setSelected(article)}
                className={`w-full text-left p-4 rounded-xl border transition-all ${
                  selected?.id === article.id
                    ? 'bg-indigo-50 border-indigo-300 shadow-sm'
                    : 'bg-white border-gray-200 hover:border-indigo-200 hover:shadow-sm'
                }`}
              >
                <div className="font-medium text-gray-900 text-sm line-clamp-2">{article.title}</div>
                <div className="flex items-center gap-2 mt-1">
                  {article.locale && (
                    <span className="text-xs text-gray-400">{article.locale}</span>
                  )}
                  {typeof article.portal_slug === 'string' && (
                    <span className="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">
                      {article.portal_slug}
                    </span>
                  )}
                </div>
                {article.content && (
                  <p className="mt-1 text-xs text-gray-500 line-clamp-2">
                    {String(article.content).replace(/<[^>]+>/g, '')}
                  </p>
                )}
              </button>
            ))
          )}
          <div className="pt-2 text-xs text-gray-400 text-center">
            {articles.length} article{articles.length !== 1 ? 's' : ''} · source: local DB
          </div>
        </div>

        {/* Right panel: article content */}
        <div className="w-1/2 bg-white border border-gray-200 rounded-xl overflow-y-auto p-6">
          {selected ? (
            <>
              <div className="flex items-start justify-between mb-4">
                <h2 className="text-lg font-bold text-gray-900">{selected.title}</h2>
                <div className="flex gap-2 ml-4 shrink-0">
                  {selected.locale && (
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
                      {selected.locale}
                    </span>
                  )}
                  {typeof selected.portal_slug === 'string' && (
                    <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded">
                      📚 {selected.portal_slug}
                    </span>
                  )}
                </div>
              </div>
              <div
                className="prose prose-sm max-w-none text-gray-700"
                dangerouslySetInnerHTML={{ __html: String(selected.content || '') }}
              />
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm">
              Select an article to view its content
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
