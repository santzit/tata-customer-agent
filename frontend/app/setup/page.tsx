"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { accountsApi, variablesApi } from "@/lib/api";

type Step = "chatwoot" | "database" | "openai";

const STEPS: { key: Step; title: string; description: string }[] = [
  { key: "chatwoot", title: "Chatwoot Account", description: "Connect your Chatwoot instance" },
  { key: "database", title: "Database", description: "PostgreSQL connection settings" },
  { key: "openai", title: "OpenAI", description: "Set your OpenAI API key" },
];

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  /* Step 1 — Chatwoot */
  const [cwName, setCwName] = useState("");
  const [cwUrl, setCwUrl] = useState("https://app.chatwoot.com");
  const [cwAccountId, setCwAccountId] = useState("1");
  const [cwToken, setCwToken] = useState("");

  /* Step 2 — Database */
  const [pgHost, setPgHost] = useState("localhost");
  const [pgPort, setPgPort] = useState("5432");
  const [pgUser, setPgUser] = useState("postgres");
  const [pgPassword, setPgPassword] = useState("");
  const [pgDb, setPgDb] = useState("tata_agent");

  /* Step 3 — OpenAI */
  const [openaiKey, setOpenaiKey] = useState("");
  const [llmModel, setLlmModel] = useState("gpt-4.1");

  const currentStep = STEPS[step];

  function stepClass(idx: number) {
    if (idx < step) return "bg-indigo-600 text-white";
    if (idx === step) return "bg-indigo-600 text-white ring-2 ring-indigo-300";
    return "bg-gray-200 text-gray-500";
  }

  async function handleNext() {
    setError(null);
    setLoading(true);
    try {
      if (currentStep.key === "chatwoot") {
        if (!cwUrl || !cwAccountId || !cwToken) {
          setError("Base URL, Account ID and API Token are required.");
          return;
        }
        // Save Chatwoot variables
        await variablesApi.upsert([
          { key: "CHATWOOT_BASE_URL", value: cwUrl },
          { key: "CHATWOOT_ACCOUNT_ID", value: cwAccountId },
          { key: "CHATWOOT_API_TOKEN", value: cwToken },
        ]);
        // Create the account entry (without token — token is in variables)
        await accountsApi.create({
          name: cwName || "Default",
          chatwoot_account_id: Number(cwAccountId),
          is_active: true,
        });
      }

      if (currentStep.key === "database") {
        if (!pgHost || !pgPort || !pgUser || !pgDb) {
          setError("Host, Port, User and Database name are required.");
          return;
        }
        await variablesApi.upsert([
          { key: "POSTGRES_HOST", value: pgHost },
          { key: "POSTGRES_PORT", value: pgPort },
          { key: "POSTGRES_USER", value: pgUser },
          { key: "POSTGRES_PASSWORD", value: pgPassword },
          { key: "POSTGRES_DB", value: pgDb },
        ]);
      }

      if (currentStep.key === "openai") {
        if (!openaiKey) {
          setError("OpenAI API Key is required.");
          return;
        }
        await variablesApi.upsert([
          { key: "OPENAI_API_KEY", value: openaiKey },
          { key: "OPENAI_MODEL", value: llmModel },
        ]);
        router.push("/dashboard");
        return;
      }

      setStep((s) => s + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-white flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-4xl mb-2">🤖</div>
          <h1 className="text-3xl font-bold text-gray-900">Tata Agent Setup</h1>
          <p className="text-gray-500 mt-1">Let&apos;s get your agent configured in 3 steps</p>
        </div>

        {/* Step progress */}
        <div className="flex items-center justify-center gap-0 mb-8">
          {STEPS.map((s, idx) => (
            <div key={s.key} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${stepClass(idx)}`}>
                  {idx < step ? "✓" : idx + 1}
                </div>
                <span className="text-xs mt-1 text-gray-500 hidden sm:block w-20 text-center">{s.title}</span>
              </div>
              {idx < STEPS.length - 1 && (
                <div className={`h-0.5 w-16 mx-1 mb-4 ${idx < step ? "bg-indigo-600" : "bg-gray-200"}`} />
              )}
            </div>
          ))}
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-lg p-8">
          <h2 className="text-xl font-semibold text-gray-800 mb-1">{currentStep.title}</h2>
          <p className="text-sm text-gray-500 mb-6">{currentStep.description}</p>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
          )}

          {/* ---- Step 1: Chatwoot ---- */}
          {currentStep.key === "chatwoot" && (
            <div className="space-y-4">
              <Field label="Account Name" placeholder="My Chatwoot" value={cwName} onChange={setCwName} />
              <Field label="Chatwoot Base URL *" placeholder="https://app.chatwoot.com" value={cwUrl} onChange={setCwUrl} />
              <Field label="Account ID *" placeholder="1" value={cwAccountId} onChange={setCwAccountId} type="number" />
              <Field
                label="API Token *"
                placeholder="Your Chatwoot API access token"
                value={cwToken}
                onChange={setCwToken}
                type="password"
                hint="Found in Chatwoot → Profile → Access Token"
              />
            </div>
          )}

          {/* ---- Step 2: Database ---- */}
          {currentStep.key === "database" && (
            <div className="space-y-4">
              <Field label="POSTGRES_HOST *" placeholder="localhost" value={pgHost} onChange={setPgHost} hint="Database server hostname or IP address" />
              <Field label="POSTGRES_PORT *" placeholder="5432" value={pgPort} onChange={setPgPort} type="number" hint="Default PostgreSQL port: 5432" />
              <Field label="POSTGRES_USER *" placeholder="postgres" value={pgUser} onChange={setPgUser} />
              <Field label="POSTGRES_PASSWORD" placeholder="Database password" value={pgPassword} onChange={setPgPassword} type="password" />
              <Field label="POSTGRES_DB *" placeholder="tata_agent" value={pgDb} onChange={setPgDb} hint="Database name (will be created automatically if not exists)" />
            </div>
          )}

          {/* ---- Step 3: OpenAI ---- */}
          {currentStep.key === "openai" && (
            <div className="space-y-4">
              <Field
                label="OpenAI API Key *"
                placeholder="sk-..."
                value={openaiKey}
                onChange={setOpenaiKey}
                type="password"
                hint="Found at platform.openai.com/api-keys"
              />
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">LLM Model</label>
                <select
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                >
                  <option value="gpt-4.1">gpt-4.1</option>
                  <option value="gpt-4o">gpt-4o</option>
                  <option value="gpt-4-turbo">gpt-4-turbo</option>
                  <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
                </select>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="mt-8 flex justify-between">
            <button
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0 || loading}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
            >
              Back
            </button>
            <button
              onClick={handleNext}
              disabled={loading}
              className="px-6 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {loading ? "Saving…" : step === STEPS.length - 1 ? "Finish Setup" : "Next →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, placeholder, value, onChange, type = "text", hint }: {
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
