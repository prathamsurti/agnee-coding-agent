import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Agni Dev | Ultra-Fast Coding Agent',
  description: 'Enterprise LangGraph agent daemon, tree-sitter AST, and RFC 8628 device auth.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
