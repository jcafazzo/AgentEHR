'use client'

import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'

// Types
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  pending_actions?: PendingAction[]
  warnings?: Warning[]
}

interface PendingAction {
  action_id: string
  action_type: string
  summary: string
  status: string
  warnings?: Warning[]
}

interface Warning {
  severity: string
  message: string
}

interface Patient {
  id: string
  name: string
  birthDate?: string
  gender?: string
}

interface PatientContext {
  patient: Patient
  activeConditions: { code: string }[]
  activeMedications: { medication: string; dosage?: string }[]
  allergies: { substance: string; reaction?: string }[]
}

// API functions
async function sendMessage(message: string, conversationId?: string): Promise<{
  content: string
  conversation_id: string
  pending_actions: PendingAction[]
  warnings: Warning[]
}> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to send message')
  }
  return response.json()
}

async function searchPatients(query: string): Promise<{ patients: Patient[] }> {
  const response = await fetch(`/api/patients/search?q=${encodeURIComponent(query)}`)
  if (!response.ok) throw new Error('Failed to search patients')
  return response.json()
}

async function getPatientSummary(patientId: string): Promise<PatientContext> {
  const response = await fetch(`/api/patients/${patientId}/summary`)
  if (!response.ok) throw new Error('Failed to get patient summary')
  return response.json()
}

// Calculate age from birthDate
function calculateAge(birthDate: string): number {
  const birth = new Date(birthDate)
  const today = new Date()
  let age = today.getFullYear() - birth.getFullYear()
  const monthDiff = today.getMonth() - birth.getMonth()
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
    age--
  }
  return age
}

// Main component
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string>()
  const [patientContext, setPatientContext] = useState<PatientContext | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [recentPatients, setRecentPatients] = useState<Patient[]>([])
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle send message
  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await sendMessage(input, conversationId)
      setConversationId(response.conversation_id)

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.content,
        timestamp: new Date(),
        pending_actions: response.pending_actions,
        warnings: response.warnings,
      }

      setMessages(prev => [...prev, assistantMessage])

      // Update pending actions
      if (response.pending_actions?.length > 0) {
        setPendingActions(prev => [...prev, ...response.pending_actions])
      }
    } catch (error) {
      console.error('Error sending message:', error)
      const errorText = error instanceof Error ? error.message : 'Unknown error occurred'
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Sorry, I encountered an error: ${errorText}`,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  // Handle patient search
  const handlePatientSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      const result = await searchPatients(searchQuery)
      setRecentPatients(result.patients)
    } catch (error) {
      console.error('Error searching patients:', error)
    }
  }

  // Handle patient select
  const handlePatientSelect = async (patient: Patient) => {
    try {
      const summary = await getPatientSummary(patient.id)
      setPatientContext(summary)
    } catch (error) {
      console.error('Error getting patient summary:', error)
    }
  }

  return (
    <div className="h-screen overflow-hidden flex">
      {/* Left Sidebar - Patient List */}
      <aside className="w-64 bg-bg-nav text-text-primary flex flex-col shrink-0 shadow-xl">
        <div className="p-6">
          {/* Logo */}
          <div className="mb-8 flex flex-col items-center">
            <div className="w-12 h-12 relative flex items-center justify-center mb-2">
              <svg className="w-full h-full text-text-primary opacity-90" viewBox="0 0 100 100">
                <circle cx="40" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
                <circle cx="60" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
                <path d="M50 30 L50 70" stroke="currentColor" strokeWidth="2" />
              </svg>
            </div>
            <h1 className="text-sm tracking-widest font-light uppercase opacity-80">AgentEHR</h1>
          </div>

          {/* Search */}
          <div className="mb-6">
            <input
              type="text"
              placeholder="Search patients..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handlePatientSearch()}
              className="w-full px-4 py-2 bg-white/10 rounded-lg text-sm placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-accent-turquoise text-white"
            />
          </div>

          {/* Patient List */}
          <nav className="space-y-1">
            {recentPatients.map((patient) => (
              <button
                key={patient.id}
                onClick={() => handlePatientSelect(patient)}
                className={`w-full px-4 py-3 text-left rounded-lg transition-colors ${
                  patientContext?.patient.id === patient.id
                    ? 'bg-white/5 border-l-2 border-accent-turquoise'
                    : 'hover:bg-white/5'
                }`}
              >
                <p className={`text-sm font-medium ${patientContext?.patient.id === patient.id ? 'text-white' : 'opacity-80'}`}>
                  {patient.name}
                </p>
                {patientContext?.patient.id === patient.id && (
                  <p className="text-[10px] opacity-60">(Selected)</p>
                )}
              </button>
            ))}
            {recentPatients.length === 0 && (
              <p className="px-4 py-2 text-sm opacity-60">
                Search for a patient to get started
              </p>
            )}
          </nav>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col relative ethereal-bg min-w-0">
        {/* Scrollable Content */}
        <div className="flex-1 p-10 overflow-y-auto">
          {/* Patient Header */}
          {patientContext ? (
            <>
              <header className="mb-12">
                <h2 className="text-4xl font-light font-serif mb-2 text-slate-800">
                  Patient Summary: {patientContext.patient.name}
                </h2>
                <p className="text-sm tracking-wide text-text-secondary font-medium">
                  DOB: {patientContext.patient.birthDate || 'Unknown'}
                  {patientContext.patient.birthDate && ` (Age: ${calculateAge(patientContext.patient.birthDate)})`}
                  {' | '}Gender: {patientContext.patient.gender || 'Unknown'}
                  {' | '}ID: {patientContext.patient.id}
                </p>
              </header>

              {/* Patient Sections */}
              <div className="max-w-3xl space-y-10 mb-10">
                {/* Active Conditions */}
                <section>
                  <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-4">
                    Active Conditions
                  </h3>
                  <ul className="pl-5 list-disc text-slate-600 space-y-2">
                    {patientContext.activeConditions.length > 0 ? (
                      patientContext.activeConditions.map((condition, i) => (
                        <li key={i}>{condition.code}</li>
                      ))
                    ) : (
                      <li>No active conditions documented</li>
                    )}
                  </ul>
                </section>

                {/* Current Medications */}
                <section>
                  <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-4">
                    Current Medications
                  </h3>
                  <ul className="pl-5 list-disc text-slate-600 space-y-2">
                    {patientContext.activeMedications.length > 0 ? (
                      patientContext.activeMedications.map((med, i) => (
                        <li key={i}>
                          {med.medication}
                          {med.dosage && ` - ${med.dosage}`}
                        </li>
                      ))
                    ) : (
                      <li>No active medications</li>
                    )}
                  </ul>
                </section>

                {/* Allergies */}
                <section>
                  <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-4">
                    Allergies
                  </h3>
                  <ul className="pl-5 list-disc text-slate-600 space-y-2">
                    {patientContext.allergies.length > 0 ? (
                      patientContext.allergies.map((allergy, i) => (
                        <li key={i}>
                          {allergy.substance}
                          {allergy.reaction && ` (${allergy.reaction})`}
                        </li>
                      ))
                    ) : (
                      <li>No known allergies documented</li>
                    )}
                  </ul>
                </section>
              </div>
            </>
          ) : (
            <header className="mb-12">
              <h2 className="text-4xl font-light font-serif mb-2 text-slate-800">
                Welcome to AgentEHR
              </h2>
              <p className="text-sm tracking-wide text-text-secondary font-medium">
                Search for a patient in the sidebar to get started
              </p>
            </header>
          )}

          {/* Chat Messages */}
          {messages.length > 0 && (
            <div className="max-w-3xl space-y-6">
              {messages.map((message) => (
                <div key={message.id}>
                  {message.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[80%] px-4 py-3 bg-slate-200 rounded-2xl rounded-br-none">
                        <p className="text-slate-800">{message.content}</p>
                      </div>
                    </div>
                  ) : (
                    <section>
                      <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-4">
                        Response:
                      </h3>
                      <div className="prose-custom text-slate-600">
                        <ReactMarkdown>{message.content}</ReactMarkdown>
                      </div>

                      {/* Warnings */}
                      {message.warnings && message.warnings.length > 0 && (
                        <div className="mt-4 space-y-2">
                          {message.warnings.map((warning, i) => (
                            <div
                              key={i}
                              className="flex items-start gap-3 p-4 bg-accent-mauve/10 rounded-lg border border-accent-mauve/20"
                            >
                              <span className="material-symbols-outlined text-accent-mauve">warning</span>
                              <p className="text-slate-700 italic">{warning.message}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </section>
                  )}
                </div>
              ))}

              {/* Loading indicator */}
              {isLoading && (
                <section>
                  <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-4">
                    Thinking...
                  </h3>
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-accent-turquoise rounded-full typing-dot" />
                    <span className="w-2 h-2 bg-accent-turquoise rounded-full typing-dot" />
                    <span className="w-2 h-2 bg-accent-turquoise rounded-full typing-dot" />
                  </div>
                </section>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Chat Input - Fixed Bottom */}
        <div className="p-8 bg-gradient-to-t from-bg-main via-bg-main/80 to-transparent">
          <div className="max-w-3xl">
            <p className="text-sm font-medium mb-4 text-slate-700">
              {patientContext
                ? `How can I assist you with ${patientContext.patient.name.split(' ')[0]}'s care today?`
                : 'How can I assist you today?'}
            </p>
            <div className="relative group">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Ask about patients, medications, or clinical questions..."
                className="w-full bg-transparent border-b border-slate-200 py-3 pr-10 focus:outline-none focus:border-accent-turquoise transition-colors placeholder:text-slate-400 text-sm italic"
              />
              <button
                onClick={handleSend}
                disabled={isLoading || !input.trim()}
                className="absolute right-0 top-1/2 -translate-y-1/2 text-slate-300 hover:text-accent-turquoise transition-colors disabled:opacity-50"
              >
                <span className="material-symbols-outlined">send</span>
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* Right Panel - Context */}
      <aside className="w-80 bg-bg-panel backdrop-blur-sm border-l border-slate-200 flex flex-col shrink-0">
        {/* Header Icons */}
        <header className="p-6 flex justify-end gap-4 text-slate-400 border-b border-slate-100">
          <button className="hover:text-accent-turquoise transition-colors">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button className="hover:text-accent-turquoise transition-colors">
            <span className="material-symbols-outlined">account_circle</span>
          </button>
        </header>

        {/* Context Sections */}
        <div className="p-8 space-y-12 overflow-y-auto">
          {/* Additional Context */}
          <section>
            <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-6">
              Additional Context
            </h3>
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                  Recent Lab Results
                </p>
                <p className="text-sm font-medium text-slate-700">
                  {patientContext ? 'Stable' : 'No patient selected'}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                  Upcoming Appointments
                </p>
                <p className="text-sm font-medium text-slate-700">
                  {patientContext ? 'None' : 'No patient selected'}
                </p>
              </div>
            </div>
          </section>

          {/* Approvals */}
          <section>
            <h3 className="text-xl font-light font-serif text-text-secondary opacity-80 mb-6">
              Approvals
            </h3>
            <div className="space-y-4">
              {pendingActions.length > 0 ? (
                pendingActions.map((action) => (
                  <div key={action.action_id} className="flex justify-between items-center group">
                    <p className="text-sm text-slate-600">{action.summary}</p>
                    <span
                      className={`text-[10px] font-semibold px-2 py-1 rounded ${
                        action.status === 'approved'
                          ? 'text-accent-turquoise bg-accent-turquoise/10'
                          : 'text-accent-mauve bg-accent-mauve/10'
                      }`}
                    >
                      {action.status.toUpperCase()}
                    </span>
                  </div>
                ))
              ) : (
                <>
                  <div className="flex justify-between items-center group">
                    <p className="text-sm text-slate-600">Prior Authorization</p>
                    <span className="text-[10px] font-semibold text-accent-mauve bg-accent-mauve/10 px-2 py-1 rounded">
                      PENDING
                    </span>
                  </div>
                  <div className="flex justify-between items-center group">
                    <p className="text-sm text-slate-600">Referral Request</p>
                    <span className="text-[10px] font-semibold text-accent-turquoise bg-accent-turquoise/10 px-2 py-1 rounded">
                      APPROVED
                    </span>
                  </div>
                </>
              )}
            </div>
          </section>
        </div>
      </aside>
    </div>
  )
}
