"use client";

import { useEffect, useState } from "react";
import { variablesApi, type TataVariable } from "@/lib/api";

/* --------------------------------------------------------------------------
 * Category definitions for display order and labels
 * -------------------------------------------------------------------------- */

const CATEGORIES: { key: string; label: string; icon: string; description: string }[] = [
  {
    key: "chatwoot",
    label: "Chatwoot",
    icon: "💬",
    description: "Connection settings for your Chatwoot instance",
  },
  {
    key: "database",
    label: "Database",
    icon: "🗄️",
    description: "PostgreSQL connection parameters",
  },
  {
    key: "openai",
    label: "OpenAI",
    icon: "🤖",
    description: "OpenAI / Azure OpenAI API configuration",
  },
  {
    key: "agent",
    label: "Agent",
    icon: "⚙️",
    description: "Tata agent behaviour settings",
  },
];

/* --------------------------------------------------------------------------
 * Page
 * -------------------------------------------------------------------------- */

export default function VariablesPage() {
  const [vars, setVars] = useState<TataVariable[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  function load() {
    setLoading(true);
    variablesApi
      .list()
      .then((rows) => {
        setVars(rows);
        // Initialise drafts: secrets show empty (user must re-enter to change)
        const init: Record<string, string> = {};
        for (const v of rows) {
          init[v.key] = v.is_secret ? "" : v.value;
        }
        setDrafts(init);
      })
      .finally(() => setLoading(false));
  }

  async function saveAll() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Only send values that the user has actually typed (non-empty for secrets
      // means intentional update; non-secrets always send current draft).
      const updates: { key: string; value: string }[] = [];
      for (const v of vars) {
        const draft = drafts[v.key] ?? "";
        if (v.is_secret) {
          // Only update if user typed something new
          if (draft !== "") updates.push({ key: v.key, value: draft });
        } else {
          updates.push({ key: v.key, value: draft });
        }
      }
      const updated = await variablesApi.upsert(updates);
      setVars(updated);
      // Reset secret drafts after save
      setDrafts((prev) => {
        const next = { ...prev };
        for (const v of updated) {
          if (v.is_secret) next[v.key] = "";
        }
        return next;
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function varsByCategory(cat: string) {
    return vars.filter((v) => v.category === cat);
  }

  if (loading) {
    return <div className="text-gray-400 py-12 text-center">Loading…</div>;
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Variables</h1>
          <p className="text-sm text-gray-500 mt-1">
            Replaces <code>.env</code> — all configuration is stored in the database.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && (
            <span className="text-sm text-green-600 font-medium">✓ Saved</span>
          )}
          <button
            onClick={saveAll}
            disabled={saving}
            className="px-5 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save All"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 text-sm p-3 rounded-lg">{error}</div>
      )}

      {/* Category sections */}
      {CATEGORIES.map((cat) => {
        const catVars = varsByCategory(cat.key);
        if (catVars.length === 0) return null;
        return (
          <section key={cat.key} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {/* Section header */}
            <div className="px-6 py-4 border-b border-gray-100 bg-gray-50">
              <div className="flex items-center gap-2">
                <span className="text-lg">{cat.icon}</span>
                <div>
                  <h2 className="text-base font-semibold text-gray-800">{cat.label}</h2>
                  <p className="text-xs text-gray-500">{cat.description}</p>
                </div>
              </div>
            </div>

            {/* Variable rows */}
            <div className="divide-y divide-gray-100">
              {catVars.map((v) => (
                <div key={v.key} className="px-6 py-4 grid grid-cols-1 sm:grid-cols-[1fr_1.5fr] gap-3 items-start">
                  {/* Label + description */}
                  <div>
                    <div className="flex items-center gap-2">
                      <code className="text-sm font-mono font-semibold text-gray-800">
                        {v.key}
                      </code>
                      {v.is_secret && (
                        <span className="text-xs px-1.5 py-0.5 bg-yellow-50 text-yellow-700 rounded font-medium">
                          secret
                        </span>
                      )}
                      {v.is_set && (
                        <span className="text-xs px-1.5 py-0.5 bg-green-50 text-green-700 rounded font-medium">
                          set
                        </span>
                      )}
                    </div>
                    {v.description && (
                      <p className="text-xs text-gray-400 mt-0.5 leading-snug">
                        {v.description}
                      </p>
                    )}
                  </div>

                  {/* Input */}
                  <input
                    type={v.is_secret ? "password" : "text"}
                    placeholder={
                      v.is_secret
                        ? v.is_set
                          ? "Leave blank to keep current value"
                          : "Enter value…"
                        : ""
                    }
                    value={drafts[v.key] ?? ""}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [v.key]: e.target.value }))
                    }
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
              ))}
            </div>
          </section>
        );
      })}

      {/* Save button at bottom */}
      <div className="flex justify-end gap-3 pb-4">
        {saved && (
          <span className="text-sm text-green-600 font-medium self-center">✓ All changes saved</span>
        )}
        <button
          onClick={saveAll}
          disabled={saving}
          className="px-6 py-2.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save All"}
        </button>
      </div>
    </div>
  );
}
