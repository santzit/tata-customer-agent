'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  getAccounts,
  getInboxes,
  getConversations,
  getConversationMessages,
  Account,
  Inbox,
  Conversation,
  Message,
} from '@/lib/api';

function formatTime(ts?: number) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString();
}

function ConversationRow({
  conv,
  selected,
  onClick,
}: {
  conv: Conversation;
  selected: boolean;
  onClick: () => void;
}) {
  // The backend maps Chatwoot's meta.sender into a top-level `contact` field.
  const name =
    (conv.contact as { name?: string } | undefined)?.name ??
    `#${conv.id}`;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-blue-50 transition-colors ${
        selected ? 'bg-blue-50 border-l-4 border-l-blue-500' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <span className="font-medium text-sm text-gray-900 truncate">{name}</span>
        <span
          className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
            conv.status === 'open'
              ? 'bg-green-100 text-green-700'
              : conv.status === 'resolved'
              ? 'bg-gray-100 text-gray-600'
              : 'bg-yellow-100 text-yellow-700'
          }`}
        >
          {conv.status ?? 'unknown'}
        </span>
      </div>
      <div className="text-xs text-gray-400">{formatTime(conv.last_activity_at)}</div>
    </button>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  // message_type: 0 = incoming, 1 = outgoing (agent), 2 = activity, 3 = bot
  const isBot = msg.message_type === 3;
  const isAgent = msg.message_type === 1;
  const isIncoming = msg.message_type === 0;

  const bgClass = isBot
    ? 'bg-purple-50 border border-purple-200'
    : isAgent
    ? 'bg-blue-50 border border-blue-200'
    : isIncoming
    ? 'bg-white border border-gray-200'
    : 'bg-gray-50 border border-gray-100 text-gray-500 italic text-xs';

  const senderLabel = isBot
    ? '🤖 Bot'
    : isAgent
    ? `🧑‍💼 ${msg.sender?.name ?? 'Agent'}`
    : isIncoming
    ? `👤 ${msg.sender?.name ?? 'Contact'}`
    : 'Activity';

  return (
    <div className={`rounded-xl p-4 ${bgClass}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-600">{senderLabel}</span>
        <span className="text-xs text-gray-400">{formatTime(msg.created_at)}</span>
      </div>
      <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
        {msg.content || <em className="text-gray-400">No content</em>}
      </p>
    </div>
  );
}

export default function ConversationsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<number | ''>('');
  const [selectedInbox, setSelectedInbox] = useState<number | ''>('');
  const [limit, setLimit] = useState(50);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getAccounts()
      .then(setAccounts)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedAccount === '') {
      setInboxes([]);
      setSelectedInbox('');
      return;
    }
    getInboxes(Number(selectedAccount))
      .then(setInboxes)
      .catch(() => setInboxes([]));
    setSelectedInbox('');
  }, [selectedAccount]);

  const loadConversations = useCallback(async () => {
    setLoadingConvs(true);
    setError('');
    setSelectedConv(null);
    setMessages([]);
    try {
      const data = await getConversations(
        limit,
        selectedAccount !== '' ? Number(selectedAccount) : undefined,
        selectedInbox !== '' ? Number(selectedInbox) : undefined
      );
      setConversations(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingConvs(false);
    }
  }, [limit, selectedAccount, selectedInbox]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  async function selectConversation(conv: Conversation) {
    setSelectedConv(conv);
    setLoadingMsgs(true);
    setMessages([]);
    try {
      const data = await getConversationMessages(
        conv.id,
        selectedAccount !== '' ? Number(selectedAccount) : undefined
      );
      setMessages(data);
    } catch {
      setMessages([]);
    } finally {
      setLoadingMsgs(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-gray-900">Conversations</h1>
        <p className="text-gray-500 mt-1">Browse and inspect support conversations.</p>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Account</label>
          <select
            value={selectedAccount}
            onChange={(e) =>
              setSelectedAccount(e.target.value === '' ? '' : Number(e.target.value))
            }
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Inbox</label>
          <select
            value={selectedInbox}
            onChange={(e) =>
              setSelectedInbox(e.target.value === '' ? '' : Number(e.target.value))
            }
            disabled={selectedAccount === ''}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
          >
            <option value="">All inboxes</option>
            {inboxes.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Limit</label>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Main panel */}
      <div className="flex flex-1 gap-4 min-h-0 overflow-hidden">
        {/* Left: conversation list */}
        <div className="w-1/3 bg-white rounded-xl border border-gray-200 shadow-sm overflow-y-auto flex flex-col">
          {loadingConvs ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm py-8">
              Loading conversations…
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-400 py-8">
              <p className="text-3xl mb-2">💬</p>
              <p className="text-sm">No conversations found.</p>
            </div>
          ) : (
            conversations.map((conv) => (
              <ConversationRow
                key={conv.id}
                conv={conv}
                selected={selectedConv?.id === conv.id}
                onClick={() => selectConversation(conv)}
              />
            ))
          )}
        </div>

        {/* Right: messages */}
        <div className="flex-1 bg-white rounded-xl border border-gray-200 shadow-sm overflow-y-auto">
          {!selectedConv ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400 py-16">
              <p className="text-4xl mb-3">👈</p>
              <p className="font-medium">Select a conversation</p>
              <p className="text-sm mt-1">to view its messages</p>
            </div>
          ) : loadingMsgs ? (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm py-8">
              Loading messages…
            </div>
          ) : (
            <div className="p-5 space-y-3">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-semibold text-gray-800">
                  Conversation #{selectedConv.id}
                </h2>
                <span className="text-xs text-gray-400">{messages.length} message(s)</span>
              </div>
              {messages.length === 0 ? (
                <div className="text-center text-gray-400 py-8">No messages.</div>
              ) : (
                messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
