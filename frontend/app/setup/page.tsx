'use client';

import Link from 'next/link';

const steps = [
  {
    href: '/accounts',
    icon: '🏢',
    title: 'Configure Accounts',
    description:
      'View all Chatwoot accounts and set the Bot Token API for each. Accounts are loaded automatically from Chatwoot — no manual entry needed.',
    cta: 'Go to Accounts →',
    color: 'blue',
  },
  {
    href: '/openai',
    icon: '🤖',
    title: 'OpenAI Configuration',
    description:
      'Set your OpenAI API key, model, and parameters. Configuration is stored securely in the local database.',
    cta: 'Go to OpenAI Config →',
    color: 'purple',
  },
  {
    href: '/help-center',
    icon: '📚',
    title: 'Help Center (RAG)',
    description:
      "Sync Help Center articles from Chatwoot into the local vector store. These articles are used as the AI agent's knowledge base.",
    cta: 'Go to Help Center →',
    color: 'green',
  },
];

const colorMap: Record<string, string> = {
  blue: 'bg-blue-600 hover:bg-blue-700',
  purple: 'bg-purple-600 hover:bg-purple-700',
  green: 'bg-green-600 hover:bg-green-700',
};

export default function SetupPage() {
  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Getting Started</h1>
        <p className="text-gray-500 mt-1">
          Follow the steps below to configure Tata Agent. Accounts and Chatwoot data are
          retrieved automatically — no credentials need to be entered here.
        </p>
      </div>

      <div className="space-y-4">
        {steps.map(({ href, icon, title, description, cta, color }, idx) => (
          <div
            key={href}
            className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 flex gap-5"
          >
            <div className="flex-shrink-0">
              <span className="flex items-center justify-center w-10 h-10 rounded-full bg-gray-100 text-xl">
                {icon}
              </span>
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">
                  Step {idx + 1}
                </span>
              </div>
              <h2 className="text-base font-semibold text-gray-900 mb-1">{title}</h2>
              <p className="text-sm text-gray-500 mb-4">{description}</p>
              <Link
                href={href}
                className={`inline-flex items-center gap-1 text-white font-medium text-sm py-2 px-4 rounded-lg transition-colors ${colorMap[color]}`}
              >
                {cta}
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
