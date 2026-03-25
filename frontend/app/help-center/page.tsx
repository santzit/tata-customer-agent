"use client";

import { useEffect, useState, useCallback } from "react";
import { helpCenterApi, accountsApi, type Article, type Account } from "@/lib/api";

export default function HelpCenterPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [search, setSearch] = useState("");
  const [portalFilter, setPortalFilter] = useState("");
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncAccountId, setSyncAccountId] = useState<string>("");

  const portalSlugs = Array.from(
    new Set(articles.map((a) => a.portal_slug).filter(Boolean))
  ) as string[];

  const loadArticles = useCallback(() => {
    setLoading(true);
    helpCenterApi
      .articles({
        search: search || undefined,
        portal_slug: portalFilter || undefined,
      })
      .then(setArticles)
      .finally(() => setLoading(false));
  }, [search, portalFilter]);

  useEffect(() => {
    accountsApi.list().then(setAccounts);
    loadArticles();
  }, [loadArticles]);

  async function triggerSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const acctId = syncAccountId ? Number(syncAccountId) : undefined;
      const res = await helpCenterApi.sync(acctId);
      setSyncMsg(res.message);
      loadArticles();
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Help Center</h1>
        <div className="flex gap-2 items-center flex-wrap">
          <select
            value={syncAccountId}
            onChange={(e) => setSyncAccountId(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            <option value="">All accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={String(a.id)}>
                {a.name || `Account #${a.id}`}
              </option>
            ))}
          </select>
          <button
            onClick={triggerSync}
            disabled={syncing}
            className="px-4 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "↻ Refresh HC"}
          </button>
        </div>
      </div>

      {syncMsg && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
          {syncMsg}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search articles…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && loadArticles()}
          className="flex-1 min-w-48 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <select
          value={portalFilter}
          onChange={(e) => setPortalFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All portals</option>
          {portalSlugs.map((slug) => (
            <option key={slug} value={slug}>
              {slug}
            </option>
          ))}
        </select>
        <button
          onClick={loadArticles}
          className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600"
        >
          Filter
        </button>
      </div>

      {/* Count */}
      {!loading && (
        <p className="text-sm text-gray-400">
          {articles.length} article{articles.length !== 1 ? "s" : ""} in the RAG store
        </p>
      )}

      {/* Articles list */}
      {loading ? (
        <div className="text-gray-400 py-12 text-center">Loading…</div>
      ) : articles.length === 0 ? (
        <div className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center text-gray-400">
          No articles found.
          {!search && !portalFilter && (
            <span> Click &quot;↻ Refresh HC&quot; to sync from Chatwoot.</span>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {articles.map((article) => (
            <div key={article.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900 truncate">
                    {article.title || article.id}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5 line-clamp-2">
                    {article.text.slice(0, 180)}
                    {article.text.length > 180 ? "…" : ""}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {article.portal_name && (
                    <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full">
                      {article.portal_name}
                    </span>
                  )}
                  {article.portal_slug && (
                    <span className="text-xs text-gray-400 font-mono">
                      {article.portal_slug}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
