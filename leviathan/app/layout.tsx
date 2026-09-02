import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Leviathan Mission Control',
  description: 'Global Asset Tracking System',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-black">{children}</body>
    </html>
  )
}
