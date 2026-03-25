"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { accountsApi, settingsApi, type Account, type AppSettings, type SetupStatus } from "@/lib/api";

export default function DashboardPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; label: string }>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      accountsApi.list(),
      settingsApi.get(),
      settingsApi.setupStatus(),
    ]).then(([accts, cfg, status]) => {
      setAccounts(accts);
      setAppSettings(cfg);
      setSetupStatus(status);
    }).finally(() => setLoading(false));
  }, []);

  async function testConnection(id: number) {
    setTestResults((p) => ({ ...p, [id]: { ok: false, label: "Testing…" } }));
    const res = await accountsApi.test(id);
    setTestResults((p) => ({
      ...p,
      [id]: {
        ok: res.ok,
        label: res.ok ? `✓ ${res.account_name || "Connected"}` : `✗ ${res.error || "Failed"}`,
      },
    }));
  }

  if (loading) {
    return <div className="text-gray-400 py-12 text-center">Loading…</div>;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        {setupStatus && !setupStatus.setup_complete && (
          <Link
            href="/setup"
            className="text-sm px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            Complete Setup →
          </Link>
        )}
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatusCard
          label="Accounts"
          value={String(accounts.filter((a) => a.is_active).length)}
          sub="active connection(s)"
          ok={accounts.some((a) => a.is_active && a.api_token_set)}
        />
        <StatusCard
          label="OpenAI"
          value={appSettings?.openai_api_key_set ? "Configured" : "Not set"}
          sub={appSettings?.llm_model ?? "–"}
          ok={!!appSettings?.openai_api_key_set}
        />
        <StatusCard
          label="Setup"
          value={setupStatus?.setup_complete ? "Complete" : "Incomplete"}
          sub={
            setupStatus?.setup_complete
              ? "Ready to receive webhooks"
              : "Finish the setup wizard"
          }
          ok={!!setupStatus?.setup_complete}
        />
      </div>

      {/* Accounts table */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-800">Chatwoot Accounts</h2>
          <Link
            href="/accounts"
            className="text-sm text-indigo-600 hover:underline"
          >
            Manage →
          </Link>
        </div>
        {accounts.length === 0 ? (
          <div className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center text-gray-400">
            No accounts configured.{" "}
            <Link href="/accounts" className="text-indigo-600 hover:underline">
              Add one
            </Link>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {accounts.map((acct) => (
              <div key={acct.id} className="flex items-center justify-between px-5 py-4">
                <div>
                  <div className="font-medium text-sm">{acct.name || `Account #${acct.id}`}</div>
                  <div className="text-xs text-gray-400">
                    {acct.chatwoot_base_url} · ID {acct.chatwoot_account_id}
                  </div>
                  <div className="mt-0.5 flex gap-2">
                    <Badge ok={acct.is_active} label={acct.is_active ? "Active" : "Inactive"} />
                    <Badge ok={acct.api_token_set} label={acct.api_token_set ? "Token set" : "No token"} />
                  </div>
                </div>
                <button
                  onClick={() => testConnection(acct.id)}
                  className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600"
                >
                  {testResults[acct.id]?.label ?? "Test connection"}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatusCard({
  label,
  value,
  sub,
  ok,
}: {
  label: string;
  value: string;
  sub: string;
  ok: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-500 font-medium">{label}</span>
        <span className={`w-2.5 h-2.5 rounded-full ${ok ? "bg-green-400" : "bg-yellow-400"}`} />
      </div>
      <div className="text-xl font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  );
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${
        ok ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
      }`}
    >
      {label}
    </span>
  );
}
