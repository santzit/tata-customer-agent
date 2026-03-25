"use client";

import { useEffect, useState } from "react";
import { accountsApi, type Account, type AccountCreate, type ChatwootAccount } from "@/lib/api";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; label: string }>>({});
  const [inboxes, setInboxes] = useState<Record<number, { id: number; name: string }[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [chatwootAccounts, setChatwootAccounts] = useState<ChatwootAccount[] | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [importing, setImporting] = useState<number | null>(null);

  const [form, setForm] = useState<AccountCreate>({
    name: "",
    chatwoot_account_id: 1,
    is_active: true,
  });

  useEffect(() => { load(); }, []);

  function load() {
    setLoading(true);
    accountsApi.list().then(setAccounts).finally(() => setLoading(false));
  }

  function openNewForm() {
    setEditId(null);
    setForm({ name: "", chatwoot_account_id: 1, is_active: true });
    setError(null);
    setShowForm(true);
  }

  function openEditForm(acct: Account) {
    setEditId(acct.id);
    setForm({ name: acct.name, chatwoot_account_id: acct.chatwoot_account_id, is_active: acct.is_active });
    setError(null);
    setShowForm(true);
  }

  async function save() {
    if (!form.chatwoot_account_id) { setError("Account ID is required."); return; }
    setSaving(true);
    setError(null);
    try {
      if (editId !== null) {
        await accountsApi.update(editId, { name: form.name, chatwoot_account_id: form.chatwoot_account_id, is_active: form.is_active });
      } else {
        await accountsApi.create(form);
      }
      setShowForm(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this account?")) return;
    await accountsApi.remove(id);
    load();
  }

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

  async function loadInboxes(id: number) {
    const list = await accountsApi.inboxes(id);
    setInboxes((p) => ({ ...p, [id]: list.map((i) => ({ id: i.id as number, name: i.name as string })) }));
  }

  async function fetchFromChatwoot() {
    setFetching(true);
    setFetchError(null);
    setChatwootAccounts(null);
    try {
      const result = await accountsApi.fromChatwoot();
      setChatwootAccounts(result);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to fetch from Chatwoot");
    } finally {
      setFetching(false);
    }
  }

  async function importChatwootAccount(acct: ChatwootAccount) {
    setImporting(acct.id);
    try {
      await accountsApi.create({ name: acct.name, chatwoot_account_id: acct.id, is_active: true });
      load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // Ignore uniqueness violations (account already imported) but surface other errors
      if (!msg.toLowerCase().includes("unique") && !msg.toLowerCase().includes("duplicate") && !msg.toLowerCase().includes("already")) {
        setFetchError(`Import failed for "${acct.name}": ${msg}`);
      } else {
        // Account already exists — refresh the list so UI shows ✓ Imported
        load();
      }
    } finally {
      setImporting(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Accounts</h1>
        <div className="flex gap-2">
          <button
            onClick={fetchFromChatwoot}
            disabled={fetching}
            className="px-4 py-2 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {fetching ? "Fetching…" : "↓ Import from Chatwoot"}
          </button>
          <button
            onClick={openNewForm}
            className="px-4 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            + Add Account
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-500">
        Chatwoot credentials (Base URL, API Token) are managed in{" "}
        <a href="/variables" className="text-indigo-600 hover:underline">Variables</a>.
        Use <strong>Import from Chatwoot</strong> to automatically discover accounts.
      </p>

      {/* Chatwoot import panel */}
      {fetchError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {fetchError}
        </div>
      )}
      {chatwootAccounts !== null && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-3">
          <div className="text-sm font-medium text-blue-800">
            {chatwootAccounts.length === 0
              ? "No accounts found on the Chatwoot instance."
              : `${chatwootAccounts.length} account(s) found on Chatwoot:`}
          </div>
          {chatwootAccounts.map((acct) => {
            const alreadyImported = accounts.some((a) => a.chatwoot_account_id === acct.id);
            return (
              <div key={acct.id} className="flex items-center justify-between bg-white rounded-lg px-4 py-2 border border-blue-100">
                <div>
                  <span className="font-medium text-sm">{acct.name}</span>
                  <span className="text-xs text-gray-400 ml-2">ID: {acct.id}</span>
                  {acct.role && <span className="text-xs text-gray-400 ml-2">({acct.role})</span>}
                </div>
                {alreadyImported ? (
                  <span className="text-xs text-green-600 font-medium">✓ Imported</span>
                ) : (
                  <button
                    onClick={() => importChatwootAccount(acct)}
                    disabled={importing === acct.id}
                    className="text-xs px-3 py-1 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {importing === acct.id ? "Importing…" : "Import"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-semibold">{editId ? "Edit Account" : "Add Account"}</h2>
            {error && <p className="text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>}
            <FormField label="Name" placeholder="My Chatwoot" value={form.name ?? ""} onChange={(v) => setForm({ ...form, name: v })} />
            <FormField
              label="Account ID *"
              placeholder="1"
              value={String(form.chatwoot_account_id)}
              type="number"
              onChange={(v) => setForm({ ...form, chatwoot_account_id: Number(v) })}
              hint="The numeric Chatwoot account ID (found in your Chatwoot URL)"
            />
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.is_active ?? true}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              Active
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
              <button onClick={save} disabled={saving} className="px-5 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-gray-400 py-8 text-center">Loading…</div>
      ) : accounts.length === 0 ? (
        <div className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center text-gray-400">
          No accounts yet. Click &quot;Add Account&quot; to connect your Chatwoot instance.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {accounts.map((acct) => (
            <div key={acct.id} className="px-5 py-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-medium text-sm">{acct.name || `Account #${acct.id}`}</div>
                  <div className="text-xs text-gray-400 mt-0.5">Chatwoot ID: {acct.chatwoot_account_id}</div>
                  <div className="mt-1">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${acct.is_active ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {acct.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap justify-end">
                  <button onClick={() => testConnection(acct.id)} className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600">
                    {testResults[acct.id]?.label ?? "Test"}
                  </button>
                  <button onClick={() => loadInboxes(acct.id)} className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600">
                    Inboxes
                  </button>
                  <button onClick={() => openEditForm(acct)} className="text-xs px-3 py-1.5 border border-indigo-200 rounded-lg hover:bg-indigo-50 text-indigo-600">
                    Edit
                  </button>
                  <button onClick={() => remove(acct.id)} className="text-xs px-3 py-1.5 border border-red-200 rounded-lg hover:bg-red-50 text-red-600">
                    Delete
                  </button>
                </div>
              </div>
              {inboxes[acct.id] && (
                <div className="mt-3">
                  <div className="text-xs font-medium text-gray-500 mb-1">Inboxes</div>
                  <div className="flex flex-wrap gap-2">
                    {inboxes[acct.id].length === 0 ? (
                      <span className="text-xs text-gray-400">No inboxes found</span>
                    ) : (
                      inboxes[acct.id].map((inbox) => (
                        <span key={inbox.id} className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                          {inbox.name}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FormField({ label, placeholder, value, onChange, type = "text", hint }: {
  label: string; placeholder: string; value: string;
  onChange: (v: string) => void; type?: string; hint?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}
