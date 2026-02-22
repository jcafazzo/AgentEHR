import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AgentEHR - Clinical AI Assistant',
  description: 'AI-powered clinical assistant for Electronic Health Records',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-bg-main min-h-screen" suppressHydrationWarning>
        {children}
      </body>
    </html>
  )
}
