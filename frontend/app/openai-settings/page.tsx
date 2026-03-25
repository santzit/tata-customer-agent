"use client";

import { useEffect, useState } from "react";
import { settingsApi, type SettingsPayload } from "@/lib/api";

export default function OpenAISettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [openaiKeySet, setOpenaiKeySet] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [llmModel, setLlmModel] = useState("gpt-4.1");
  const [llmProvider, setLlmProvider] = useState("openai");
  const [apiEndpoint, setApiEndpoint] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("text-embedding-3-small");
  const [embeddingDim, setEmbeddingDim] = useState(1536);
  const [delay, setDelay] = useState(120);
  const [logLevel, setLogLevel] = useState("info");
  const [webhookTokenSet, setWebhookTokenSet] = useState(false);
  const [newWebhookToken, setNewWebhookToken] = useState("");

  useEffect(() => {
    settingsApi.get().then((s) => {
      setOpenaiKeySet(s.openai_api_key_set);
      setLlmModel(s.llm_model);
      setLlmProvider(s.llm_provider);
      setApiEndpoint(s.openai_api_endpoint);
      setEmbeddingModel(s.embedding_model);
      setEmbeddingDim(s.embedding_dimension);
      setDelay(s.response_delay_seconds);
      setLogLevel(s.log_level);
      setWebhookTokenSet(s.webhook_token_set);
    }).finally(() => setLoading(false));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const payload: SettingsPayload = {
        llm_model: llmModel,
        llm_provider: llmProvider,
        openai_api_endpoint: apiEndpoint,
        embedding_model: embeddingModel,
        embedding_dimension: embeddingDim,
        response_delay_seconds: delay,
        log_level: logLevel,
      };
      if (newKey) payload.openai_api_key = newKey;
      if (newWebhookToken) payload.webhook_token = newWebhookToken;
      const updated = await settingsApi.update(payload);
      setOpenaiKeySet(updated.openai_api_key_set);
      setWebhookTokenSet(updated.webhook_token_set);
      setNewKey("");
      setNewWebhookToken("");
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="text-gray-400 py-12 text-center">Loading…</div>;

  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-2xl font-bold text-gray-900">OpenAI Settings</h1>

      {saved && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
          ✓ Settings saved
        </div>
      )}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* OpenAI credentials */}
      <section className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-800">API Key</h2>
        <div>
          <div className="text-sm text-gray-500 mb-2">
            Status:{" "}
            <span className={openaiKeySet ? "text-green-600 font-medium" : "text-yellow-600 font-medium"}>
              {openaiKeySet ? "Configured" : "Not set"}
            </span>
          </div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {openaiKeySet ? "Replace API Key (leave blank to keep current)" : "API Key *"}
          </label>
          <input
            type="password"
            placeholder="sk-..."
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <p className="text-xs text-gray-400 mt-1">Found at platform.openai.com/api-keys</p>
        </div>
      </section>

      {/* LLM settings */}
      <section className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-800">Model</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">LLM Model</label>
            <select
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="gpt-4.1">gpt-4.1</option>
              <option value="gpt-4o">gpt-4o</option>
              <option value="gpt-4-turbo">gpt-4-turbo</option>
              <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="openai">OpenAI</option>
              <option value="azure">Azure OpenAI</option>
            </select>
          </div>
        </div>
        {llmProvider === "azure" && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Azure Endpoint</label>
            <input
              type="url"
              placeholder="https://<resource>.cognitiveservices.azure.com/openai/v1/"
              value={apiEndpoint}
              onChange={(e) => setApiEndpoint(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
        )}
      </section>

      {/* Embedding */}
      <section className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-800">Embeddings</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Embedding Model</label>
            <select
              value={embeddingModel}
              onChange={(e) => {
                setEmbeddingModel(e.target.value);
                setEmbeddingDim(e.target.value.includes("large") ? 3072 : 1536);
              }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="text-embedding-3-small">text-embedding-3-small (1536)</option>
              <option value="text-embedding-3-large">text-embedding-3-large (3072)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Dimension</label>
            <input
              type="number"
              value={embeddingDim}
              onChange={(e) => setEmbeddingDim(Number(e.target.value))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
        </div>
      </section>

      {/* Agent behaviour */}
      <section className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-800">Agent Behaviour</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Response Delay (seconds)
            </label>
            <input
              type="number"
              min={0}
              value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              Silence window before the agent replies. 0 = reply immediately.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Log Level</label>
            <select
              value={logLevel}
              onChange={(e) => setLogLevel(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="debug">debug</option>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="error">error</option>
            </select>
          </div>
        </div>
      </section>

      {/* Webhook token */}
      <section className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-800">Webhook Security</h2>
        <div>
          <div className="text-sm text-gray-500 mb-2">
            Token:{" "}
            <span className={webhookTokenSet ? "text-green-600 font-medium" : "text-gray-400"}>
              {webhookTokenSet ? "Configured" : "Not set (open)"}
            </span>
          </div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {webhookTokenSet ? "Replace Webhook Token (leave blank to keep)" : "Webhook Token (optional)"}
          </label>
          <input
            type="password"
            placeholder="Set to require X-Chatwoot-Signature header"
            value={newWebhookToken}
            onChange={(e) => setNewWebhookToken(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>
      </section>

      {/* Save button */}
      <div className="flex justify-end">
        <button
          onClick={save}
          disabled={saving}
          className="px-6 py-2 font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
