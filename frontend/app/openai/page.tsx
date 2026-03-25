'use client';

import { useEffect, useState } from 'react';
import { getOpenAIConfig, saveOpenAIConfig, OpenAIConfig } from '@/lib/api';

const MODEL_SUGGESTIONS = [
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'gpt-4',
  'gpt-3.5-turbo',
];

export default function OpenAIPage() {
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('gpt-4o');
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
      await saveOpenAIConfig({ api_key: apiKey, model, params: parsed });
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
          Set up the OpenAI API key and model parameters used by the AI agent.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
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
            Your OpenAI API key. Never commit this to source control.
          </p>
        </div>

        {/* Model */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            list="model-suggestions"
            placeholder="gpt-4o"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <datalist id="model-suggestions">
            {MODEL_SUGGESTIONS.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <p className="text-xs text-gray-400 mt-1">
            Model identifier. Suggestions: {MODEL_SUGGESTIONS.join(', ')}.
          </p>
        </div>

        {/* Parameters JSON */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Parameters <span className="text-gray-400 font-normal">(JSON)</span>
          </label>
          <textarea
            value={paramsText}
            onChange={(e) => {
              setParamsText(e.target.value);
              setParamsError('');
            }}
            rows={8}
            spellCheck={false}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          {paramsError && (
            <p className="text-xs text-red-600 mt-1">{paramsError}</p>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Additional parameters passed to the OpenAI API (e.g. temperature, max_tokens).
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
