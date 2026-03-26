'use client';

import { useEffect, useState, useCallback } from 'react';
import { getHelpCenterArticles, syncHelpCenter, Article } from '@/lib/api';

function ArticleCard({ article }: { article: Article }) {
  const preview = typeof article.content === 'string'
    ? article.content.replace(/<[^>]+>/g, '').slice(0, 180)
    : '';
  const updatedAt = article.updated_at
    ? new Date(article.updated_at).toLocaleDateString()
    : '';

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="font-semibold text-gray-900 leading-snug">{article.title}</h3>
        {article.locale && (
          <span className="shrink-0 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">
            {article.locale}
          </span>
        )}
      </div>
      {preview && (
        <p className="text-sm text-gray-500 leading-relaxed line-clamp-3">{preview}…</p>
      )}
      {updatedAt && (
        <p className="text-xs text-gray-400 mt-3">Updated {updatedAt}</p>
      )}
    </div>
  );
}

export default function HelpCenterPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [search, setSearch] = useState('');
  const [locale, setLocale] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const [error, setError] = useState('');

  const loadArticles = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getHelpCenterArticles(search || undefined, locale || undefined);
      setArticles(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [search, locale]);

  useEffect(() => {
    loadArticles();
  }, [loadArticles]);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg('');
    try {
      const result = await syncHelpCenter();
      setSyncMsg(`✅ Synced ${result.synced} article(s) from Chatwoot.`);
      await loadArticles();
    } catch (e) {
      setSyncMsg(`❌ Sync failed: ${String(e)}`);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Help Center</h1>
        <p className="text-gray-500 mt-1">Browse locally synced knowledge base articles (source: local DB).</p>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-6 flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search articles…"
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
          type="text"
          value={locale}
          onChange={(e) => setLocale(e.target.value)}
          placeholder="Locale (e.g. en)"
          className="w-36 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={handleSync}
          disabled={syncing}
          className="shrink-0 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium px-4 py-2 rounded-lg text-sm transition-colors"
        >
          {syncing ? 'Syncing…' : '🔄 Sync from Chatwoot'}
        </button>
      </div>

      {syncMsg && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            syncMsg.startsWith('✅')
              ? 'bg-green-50 border border-green-200 text-green-700'
              : 'bg-red-50 border border-red-200 text-red-700'
          }`}
        >
          {syncMsg}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-16 text-gray-400">Loading articles…</div>
      ) : articles.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-xl border border-gray-200 text-gray-400">
          <p className="text-4xl mb-3">📭</p>
          <p className="font-medium">No articles found.</p>
          <p className="text-sm mt-1">Try syncing from Chatwoot or adjusting your search.</p>
        </div>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-4">{articles.length} article(s) · source: local DB</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {articles.map((a) => (
              <ArticleCard key={a.id} article={a} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
