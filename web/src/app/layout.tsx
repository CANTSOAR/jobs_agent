import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Jobs Agent',
  description: 'AI-powered job search agent that finds the best roles for you.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
