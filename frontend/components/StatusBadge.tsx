'use client';

import { useEffect, useState } from 'react';
import { getStatus, Status } from '@/lib/api';

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${ok ? 'bg-green-400' : 'bg-red-400'}`}
    />
  );
}

export default function StatusBadge() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getStatus()
      .then(setStatus)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs text-red-400">
        <Dot ok={false} />
        Backend unreachable
      </div>
    );
  }

  if (!status) {
    return <div className="text-xs text-gray-400">Loading status…</div>;
  }

  return (
    <div className="flex items-center gap-4 text-xs text-gray-600">
      <span className="flex items-center gap-1.5">
        <Dot ok={status.chatwoot_connected} />
        Chatwoot
      </span>
      <span className="flex items-center gap-1.5">
        <Dot ok={status.db_connected} />
        Database
      </span>
      <span className="flex items-center gap-1.5">
        <Dot ok={status.openai_configured} />
        OpenAI
      </span>
    </div>
  );
}
