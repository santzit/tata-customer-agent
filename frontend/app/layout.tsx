import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/Navbar';
import StatusBadge from '@/components/StatusBadge';

export const metadata: Metadata = {
  title: 'Tata Customer Agent',
  description: 'AI-powered customer support agent dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <div className="flex min-h-screen">
          <Navbar />
          <div className="flex-1 flex flex-col">
            <header className="h-12 bg-white border-b border-gray-200 flex items-center justify-end px-6 shadow-sm">
              <StatusBadge />
            </header>
            <main className="flex-1 p-6 overflow-auto">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
