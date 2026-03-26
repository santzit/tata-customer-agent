'use client';

import { useEffect, useState } from 'react';
import { getOpenAIConfig, saveOpenAIConfig, OpenAIConfig } from '@/lib/api';

const MODEL_SUGGESTIONS = [
  'gpt-4.1',
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'gpt-4',
  'gpt-3.5-turbo',
];

const PROVIDER_OPTIONS = ['openai', 'azure', 'ollama', 'anthropic'];

export default function OpenAIPage() {
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('gpt-4.1');
  const [apiEndpoint, setApiEndpoint] = useState('');
  const [embeddingModelSmall, setEmbeddingModelSmall] = useState('');
  const [embeddingModelLarge, setEmbeddingModelLarge] = useState('');
  const [llmProvider, setLlmProvider] = useState('openai');
  const [paramsText, setParamsText] = useState('{\n  "temperature": 0.7\n}');
  const [paramsError, setParamsError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  useEffect(() => {
    getOpenAIConfig()
      .then((cfg: OpenAIConfig) => {
        if (cfg.api_key) setApiKey(cfg.api_key);
        if (cfg.model) setModel(cfg.model);
        if (cfg.api_endpoint) setApiEndpoint(cfg.api_endpoint);
        if (cfg.embedding_model_small) setEmbeddingModelSmall(cfg.embedding_model_small);
        if (cfg.embedding_model_large) setEmbeddingModelLarge(cfg.embedding_model_large);
        if (cfg.llm_provider) setLlmProvider(cfg.llm_provider);
        if (cfg.params) setParamsText(JSON.stringify(cfg.params, null, 2));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function validateParams(text: string): Record<string, unknown> | null {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  async function handleSave() {
    setParamsError('');
    const parsed = validateParams(paramsText);
    if (parsed === null) {
      setParamsError('Invalid JSON. Please fix the parameters field.');
      return;
    }
    setSaving(true);
    setSaveMsg('');
    try {
      await saveOpenAIConfig({
        api_key: apiKey,
        model,
        api_endpoint: apiEndpoint,
        embedding_model_small: embeddingModelSmall,
        embedding_model_large: embeddingModelLarge,
        llm_provider: llmProvider,
        params: parsed,
      });
      setSaveMsg('✅ OpenAI configuration saved!');
    } catch (e) {
      setSaveMsg(`❌ Error: ${String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">OpenAI Configuration</h1>
        <p className="text-gray-500 mt-1">
          Set up the LLM provider, API key, model and embedding parameters used by the AI agent.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
        {/* LLM Provider */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">LLM Provider</label>
          <select
            value={llmProvider}
            onChange={(e) => setLlmProvider(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {PROVIDER_OPTIONS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <p className="text-xs text-gray-400 mt-1">
            The LLM provider backend (openai, azure, ollama, anthropic).
          </p>
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-…"
            autoComplete="off"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            Your OpenAI (or provider) API key. Never commit this to source control.
          </p>
        </div>

        {/* API Endpoint */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API Endpoint <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={apiEndpoint}
            onChange={(e) => setApiEndpoint(e.target.value)}
            placeholder="https://api.openai.com/v1"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            Custom API base URL. Leave blank to use the provider default. Required for Azure OpenAI or Ollama.
          </p>
        </div>

        {/* Model */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">LLM Model</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            list="model-suggestions"
            placeholder="gpt-4.1"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <datalist id="model-suggestions">
            {MODEL_SUGGESTIONS.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <p className="text-xs text-gray-400 mt-1">
            Model identifier for chat completions. Suggestions: {MODEL_SUGGESTIONS.join(', ')}.
          </p>
        </div>

        {/* Embedding Model Small */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Embedding Model (Small) <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={embeddingModelSmall}
            onChange={(e) => setEmbeddingModelSmall(e.target.value)}
            placeholder="text-embedding-3-small"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            Fast/small embedding model used for RAG retrieval (e.g. text-embedding-3-small).
          </p>
        </div>

        {/* Embedding Model Large */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Embedding Model (Large) <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={embeddingModelLarge}
            onChange={(e) => setEmbeddingModelLarge(e.target.value)}
            placeholder="text-embedding-3-large"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            High-quality embedding model for document indexing (e.g. text-embedding-3-large).
          </p>
        </div>

        {/* Parameters JSON */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Extra Parameters <span className="text-gray-400 font-normal">(JSON)</span>
          </label>
          <textarea
            value={paramsText}
            onChange={(e) => {
              setParamsText(e.target.value);
              setParamsError('');
            }}
            rows={6}
            spellCheck={false}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          {paramsError && (
            <p className="text-xs text-red-600 mt-1">{paramsError}</p>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Additional parameters passed to the LLM API (e.g. temperature, max_tokens).
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
          {saving ? 'Saving…' : 'Save OpenAI Config'}
        </button>
      </div>
    </div>
  );
}
