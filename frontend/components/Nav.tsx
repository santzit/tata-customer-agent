"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/accounts", label: "Accounts" },
  { href: "/help-center", label: "Help Center" },
  { href: "/openai-settings", label: "OpenAI" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-4 flex items-center gap-6 h-14">
        <span className="font-bold text-indigo-600 text-lg mr-4">🤖 Tata Agent</span>
        {NAV.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`text-sm font-medium px-2 py-1 rounded transition-colors ${
              pathname?.startsWith(href)
                ? "text-indigo-600 bg-indigo-50"
                : "text-gray-600 hover:text-indigo-600"
            }`}
          >
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
