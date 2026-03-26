'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navItems = [
  { href: '/accounts', label: 'Accounts', icon: '🏢' },
  { href: '/help-center', label: 'Help Center', icon: '📚' },
  { href: '/conversations', label: 'Conversations', icon: '💬' },
  { href: '/openai', label: 'OpenAI Config', icon: '🤖' },
  { href: '/setup', label: 'Getting Started', icon: '⚙️' },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 min-h-screen bg-gray-900 text-white flex flex-col">
      <div className="px-6 py-5 border-b border-gray-700">
        <span className="text-lg font-bold tracking-tight text-white">Tata Agent</span>
        <span className="block text-xs text-gray-400 mt-0.5">Customer Support AI</span>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ href, label, icon }) => {
          const active = pathname === href || pathname.startsWith(href + '/');
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-300 hover:bg-gray-800 hover:text-white'
              }`}
            >
              <span>{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="px-6 py-4 border-t border-gray-700 text-xs text-gray-500">
        v0.3.x
      </div>
    </aside>
  );
}
