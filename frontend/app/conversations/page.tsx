"use client";

import { useEffect, useState } from "react";
import { conversationsApi, type Message } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  sent: "bg-green-50 text-green-700",
  pending: "bg-yellow-50 text-yellow-700",
  failed: "bg-red-50 text-red-700",
};

function formatDate(iso: string) {
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function ConversationsPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    conversationsApi
      .recent(10)
      .then(setMessages)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Conversations</h1>
        <button
          onClick={load}
          disabled={loading}
          className="text-sm px-4 py-2 border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600 disabled:opacity-50"
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      <p className="text-sm text-gray-500">
        Last 10 outgoing agent responses, newest first.
      </p>

      {error && (
        <div className="bg-red-50 text-red-700 text-sm p-3 rounded-lg">{error}</div>
      )}

      {loading ? (
        <div className="text-gray-400 py-12 text-center">Loading…</div>
      ) : messages.length === 0 ? (
        <div className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center text-gray-400">
          No messages yet. Responses appear here once Tata replies to a customer.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {messages.map((msg) => (
            <div key={msg.id} className="px-5 py-4 space-y-1">
              {/* Header row */}
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-gray-400">
                    Conv #{msg.chatwoot_conv_id}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      STATUS_STYLES[msg.status] ?? "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {msg.status}
                  </span>
                  {msg.send_attempts > 1 && (
                    <span className="text-xs text-gray-400">
                      {msg.send_attempts} attempt{msg.send_attempts !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                <span className="text-xs text-gray-400 shrink-0">
                  {formatDate(msg.created_at)}
                </span>
              </div>

              {/* Message content */}
              <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                {msg.content}
              </p>

              {/* Error (failed messages) */}
              {msg.error && (
                <p className="text-xs text-red-500 mt-1">Error: {msg.error}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
