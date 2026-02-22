'use client'

import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { StatusPill, CollapsibleSection, ActionCard, CareGapCard } from '@/components'
import type {
  Patient,
  PatientSummary,
  PatientThread,
  Message,
  ActionableItem,
  PendingAction,
} from '@/lib/types'

// API functions
async function sendMessage(
  message: string,
  conversationId?: string,
  patientId?: string
): Promise<{
  content: string
  conversation_id: string
  pending_actions: any[]
  warnings: any[]
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

async function getPatientSummary(patientId: string): Promise<PatientSummary> {
  const response = await fetch(`/api/patients/${patientId}/summary`)
  if (!response.ok) throw new Error('Failed to get patient summary')
  return response.json()
}

async function fetchPendingActions(patientId?: string): Promise<{ actions: PendingAction[] }> {
  const url = patientId ? `/api/actions?patient_id=${patientId}` : '/api/actions'
  const response = await fetch(url)
  if (!response.ok) throw new Error('Failed to fetch actions')
  return response.json()
}

async function approveAction(actionId: string): Promise<void> {
  const response = await fetch(`/api/actions/${actionId}/approve`, { method: 'POST' })
  if (!response.ok) throw new Error('Failed to approve action')
}

async function rejectAction(actionId: string, reason?: string): Promise<void> {
  const response = await fetch(`/api/actions/${actionId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!response.ok) throw new Error('Failed to reject action')
}

export default function ChatPage() {
  // Thread state - one thread per patient
  const [threads, setThreads] = useState<Map<string, PatientThread>>(new Map())
  const [activePatientId, setActivePatientId] = useState<string | null>(null)
  const [conversationIds, setConversationIds] = useState<Map<string, string>>(new Map())

  // UI state
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [patientSummary, setPatientSummary] = useState<PatientSummary | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Patient[]>([])
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([])
  const [suggestedActions, setSuggestedActions] = useState<ActionableItem[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Get current thread messages
  const currentMessages = activePatientId
    ? threads.get(activePatientId)?.messages || []
    : []

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [currentMessages])

  // Fetch pending actions when patient changes
  useEffect(() => {
    if (activePatientId) {
      fetchPendingActions(activePatientId)
        .then(result => setPendingActions(result.actions || []))
        .catch(console.error)
    }
  }, [activePatientId])

  // Handle patient search
  const handlePatientSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      const result = await searchPatients(searchQuery)
      setSearchResults(result.patients)
    } catch (error) {
      console.error('Error searching patients:', error)
    }
  }

  // Handle patient selection - creates/switches thread
  const handleSelectPatient = async (patient: Patient) => {
    setActivePatientId(patient.id)

    // Create thread if doesn't exist
    if (!threads.has(patient.id)) {
      setThreads(prev => {
        const newThreads = new Map(prev)
        newThreads.set(patient.id, {
          patientId: patient.id,
          patientName: patient.name,
          messages: [],
          lastActivity: new Date(),
          unreadCount: 0,
        })
        return newThreads
      })
    }

    // Fetch patient summary
    try {
      const summary = await getPatientSummary(patient.id)
      setPatientSummary(summary)

      // Generate suggested actions from care gaps
      const suggestions: ActionableItem[] = (summary.careGaps || []).map((gap, i) => ({
        id: `suggestion-${i}`,
        type: gap.type === 'immunization' ? 'order' as const : 'referral' as const,
        description: gap.description,
        priority: gap.priority as 'high' | 'routine' | 'low',
        reason: `Identified from care gap analysis`,
        status: 'suggested' as const,
      }))
      setSuggestedActions(suggestions)
    } catch (error) {
      console.error('Error getting patient summary:', error)
    }
  }

  // Handle send message
  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    if (!activePatientId) {
      alert('Please select a patient first')
      return
    }

    const userMessage: Message = {
      role: 'user',
      content: input,
      timestamp: new Date(),
    }

    // Add to current thread
    setThreads(prev => {
      const newThreads = new Map(prev)
      const thread = newThreads.get(activePatientId)
      if (thread) {
        thread.messages = [...thread.messages, userMessage]
        thread.lastActivity = new Date()
      }
      return newThreads
    })

    setInput('')
    setIsLoading(true)

    try {
      const conversationId = conversationIds.get(activePatientId)
      const response = await sendMessage(input, conversationId, activePatientId)

      // Store conversation ID for this patient
      if (!conversationId) {
        setConversationIds(prev => {
          const newIds = new Map(prev)
          newIds.set(activePatientId, response.conversation_id)
          return newIds
        })
      }

      const assistantMessage: Message = {
        role: 'assistant',
        content: response.content,
        timestamp: new Date(),
      }

      // Add response to thread
      setThreads(prev => {
        const newThreads = new Map(prev)
        const thread = newThreads.get(activePatientId)
        if (thread) {
          thread.messages = [...thread.messages, assistantMessage]
          thread.lastActivity = new Date()
        }
        return newThreads
      })

      // Update pending actions
      if (response.pending_actions?.length > 0) {
        fetchPendingActions(activePatientId)
          .then(result => setPendingActions(result.actions || []))
          .catch(console.error)
      }
    } catch (error) {
      console.error('Error sending message:', error)
      const errorMessage: Message = {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        timestamp: new Date(),
      }
      setThreads(prev => {
        const newThreads = new Map(prev)
        const thread = newThreads.get(activePatientId)
        if (thread) {
          thread.messages = [...thread.messages, errorMessage]
        }
        return newThreads
      })
    } finally {
      setIsLoading(false)
    }
  }

  // Handle action approval
  const handleApproveAction = async (actionId: string) => {
    try {
      await approveAction(actionId)
      setPendingActions(prev => prev.filter(a => a.action_id !== actionId))
    } catch (error) {
      console.error('Error approving action:', error)
    }
  }

  // Handle action rejection
  const handleRejectAction = async (actionId: string) => {
    try {
      await rejectAction(actionId)
      setPendingActions(prev => prev.filter(a => a.action_id !== actionId))
    } catch (error) {
      console.error('Error rejecting action:', error)
    }
  }

  return (
    <div className="h-screen overflow-hidden flex">
      {/* Left Sidebar - Patient Threads */}
      <aside className="w-64 bg-bg-nav text-text-primary flex flex-col shrink-0 shadow-xl">
        <div className="p-6">
          {/* Logo */}
          <div className="mb-6 flex items-center gap-2">
            <div className="w-8 h-8 relative flex items-center justify-center">
              <svg className="w-full h-full text-text-primary opacity-90" viewBox="0 0 100 100">
                <circle cx="40" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
                <circle cx="60" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
              </svg>
            </div>
            <h1 className="text-lg font-medium text-white">AgentEHR</h1>
          </div>

          {/* Search */}
          <div className="mb-4">
            <input
              type="text"
              placeholder="Search patients..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handlePatientSearch()}
              className="w-full px-3 py-2 bg-white/10 rounded text-sm placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 text-white"
            />
          </div>

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="mb-4 border-b border-white/10 pb-4">
              <p className="text-xs text-slate-400 mb-2">Search Results</p>
              {searchResults.slice(0, 5).map((patient) => (
                <button
                  key={patient.id}
                  onClick={() => handleSelectPatient(patient)}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-white/10 rounded transition-colors text-slate-300 hover:text-white"
                >
                  {patient.name}
                </button>
              ))}
            </div>
          )}

          {/* Active Threads */}
          <div className="flex-1">
            <p className="text-xs text-slate-400 mb-2 uppercase tracking-wide">Patient Chats</p>
            {Array.from(threads.values())
              .sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime())
              .map(thread => (
                <button
                  key={thread.patientId}
                  onClick={() => handleSelectPatient({ id: thread.patientId, name: thread.patientName })}
                  className={`w-full text-left px-3 py-3 rounded transition-colors ${
                    activePatientId === thread.patientId
                      ? 'bg-white/10 border-l-2 border-cyan-500'
                      : 'hover:bg-white/5'
                  }`}
                >
                  <p className="text-sm font-medium text-white truncate">{thread.patientName}</p>
                  <p className="text-xs text-slate-400 truncate">
                    {thread.messages.length > 0
                      ? thread.messages[thread.messages.length - 1].content.slice(0, 40) + '...'
                      : 'No messages yet'}
                  </p>
                </button>
              ))}
            {threads.size === 0 && (
              <p className="text-sm text-slate-500 px-3">
                Search and select a patient to start a conversation
              </p>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col relative ethereal-bg min-w-0">
        <div className="flex-1 p-8 overflow-y-auto">
          {patientSummary ? (
            <>
              {/* Patient Header - Minimal */}
              <div className="mb-6">
                <h1 className="font-serif text-3xl text-slate-800">
                  {patientSummary.patient.name}
                </h1>
                <p className="text-slate-500 text-sm mt-1">
                  {patientSummary.patient.age}yo {patientSummary.patient.gender}
                  {' · '}DOB {patientSummary.patient.birthDate || 'Unknown'}
                  {patientSummary.patient.mrn && ` · MRN ${patientSummary.patient.mrn}`}
                </p>
              </div>

              {/* Quick Status Pills */}
              <div className="flex flex-wrap gap-2 mb-6">
                <StatusPill
                  label="Allergies"
                  count={patientSummary.allergies.length}
                  color={patientSummary.allergies.length === 0 ? 'amber' : 'red'}
                />
                <StatusPill
                  label="Medications"
                  count={patientSummary.medications.length}
                  color="blue"
                />
                <StatusPill
                  label="Conditions"
                  count={patientSummary.conditions.filter(c => c.isActive).length}
                  color="slate"
                />
                {patientSummary.careGaps.length > 0 && (
                  <StatusPill
                    label="Care Gaps"
                    count={patientSummary.careGaps.length}
                    color="orange"
                  />
                )}
              </div>

              {/* Incomplete Data Alert */}
              {patientSummary.incompleteData.length > 0 && (
                <div className="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-sm font-medium text-amber-800 mb-1">Incomplete Record</p>
                  {patientSummary.incompleteData.map((item, i) => (
                    <p key={i} className="text-sm text-amber-700">• {item.message}</p>
                  ))}
                </div>
              )}

              {/* Collapsible Sections */}
              <div className="max-w-2xl mb-8 bg-white/50 rounded-lg p-4">
                <CollapsibleSection title="Medications" defaultOpen={true}>
                  {patientSummary.medications.length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.medications.map((med, i) => (
                        <div key={i} className="flex items-center justify-between py-1">
                          <span className="text-slate-700">{med.medication}</span>
                          {med.dosage && (
                            <span className="text-slate-500 text-sm">{med.dosage}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No active medications</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Active Conditions">
                  {patientSummary.conditions.filter(c => c.isActive).length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.conditions
                        .filter(c => c.isActive)
                        .map((condition, i) => (
                          <div key={i} className="py-1 text-slate-700">{condition.code}</div>
                        ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No active conditions</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Allergies">
                  {patientSummary.allergies.length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.allergies.map((allergy, i) => (
                        <div key={i} className="flex items-center gap-2 py-1">
                          <span className="text-red-700 font-medium">{allergy.substance}</span>
                          {allergy.reaction && (
                            <span className="text-slate-500 text-sm">({allergy.reaction})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-amber-600">No allergies documented - confirm NKDA</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection
                  title="Recent Labs"
                  badge={`${patientSummary.labs.length} results`}
                >
                  {patientSummary.labs.length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.labs.slice(0, 10).map((lab, i) => (
                        <div key={i} className="flex items-center justify-between py-1">
                          <span className="text-slate-700">{lab.code}</span>
                          <span className="text-slate-600">{lab.value}</span>
                          {lab.date && (
                            <span className="text-slate-400 text-xs">{lab.date}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No recent lab results</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Vitals">
                  {patientSummary.vitals.length > 0 ? (
                    <div className="grid grid-cols-2 gap-2">
                      {patientSummary.vitals.slice(0, 6).map((vital, i) => (
                        <div key={i} className="p-2 bg-slate-50 rounded">
                          <p className="text-xs text-slate-500">{vital.code}</p>
                          <p className="text-sm font-medium text-slate-700">{vital.value}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No recent vitals</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Immunizations">
                  {patientSummary.immunizations.length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.immunizations.map((imm, i) => (
                        <div key={i} className="flex items-center justify-between py-1">
                          <span className="text-slate-700">{imm.vaccine}</span>
                          {imm.date && (
                            <span className="text-slate-400 text-sm">{imm.date}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No immunization records</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Procedures">
                  {patientSummary.procedures.length > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.procedures.map((proc, i) => (
                        <div key={i} className="flex items-center justify-between py-1">
                          <span className="text-slate-700">{proc.name}</span>
                          {proc.date && (
                            <span className="text-slate-400 text-sm">{proc.date}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No procedure history</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title="Clinical Notes">
                  {patientSummary.clinicalNotes.length > 0 ? (
                    <div className="space-y-2">
                      {patientSummary.clinicalNotes.map((note, i) => (
                        <div key={i} className="p-2 bg-slate-50 rounded">
                          <p className="text-sm font-medium text-slate-700">{note.type}</p>
                          {note.description && (
                            <p className="text-xs text-slate-500">{note.description}</p>
                          )}
                          {note.date && (
                            <p className="text-xs text-slate-400">{note.date}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No clinical notes</p>
                  )}
                </CollapsibleSection>
              </div>

              {/* Chat Messages */}
              {currentMessages.length > 0 && (
                <div className="max-w-2xl space-y-4 mb-4">
                  <h3 className="text-sm font-semibold text-slate-600 uppercase tracking-wide">
                    Conversation
                  </h3>
                  {currentMessages.map((message, i) => (
                    <div key={i}>
                      {message.role === 'user' ? (
                        <div className="flex justify-end">
                          <div className="max-w-[80%] px-4 py-2 bg-cyan-500 text-white rounded-2xl rounded-br-sm">
                            <p className="text-sm">{message.content}</p>
                          </div>
                        </div>
                      ) : (
                        <div className="bg-white/80 rounded-lg p-4">
                          <div className="prose prose-sm prose-slate max-w-none">
                            <ReactMarkdown>{message.content}</ReactMarkdown>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {isLoading && (
                    <div className="flex gap-1 p-4">
                      <span className="w-2 h-2 bg-cyan-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-cyan-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-cyan-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 mb-4 text-slate-300">
                <svg viewBox="0 0 100 100" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="40" cy="50" r="25" />
                  <circle cx="60" cy="50" r="25" />
                </svg>
              </div>
              <h2 className="text-2xl font-serif text-slate-700 mb-2">Welcome to AgentEHR</h2>
              <p className="text-slate-500">Search for a patient to get started</p>
            </div>
          )}
        </div>

        {/* Chat Input */}
        {activePatientId && (
          <div className="p-6 bg-gradient-to-t from-white to-transparent">
            <div className="max-w-2xl mx-auto">
              <div className="flex items-center gap-2 bg-white rounded-lg shadow-sm border border-slate-200 px-4 py-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  placeholder={`Ask about ${patientSummary?.patient.name.split(' ')[0] || 'this patient'}...`}
                  className="flex-1 bg-transparent focus:outline-none text-sm text-slate-700 placeholder:text-slate-400"
                />
                <button
                  onClick={handleSend}
                  disabled={isLoading || !input.trim()}
                  className="p-2 text-cyan-500 hover:text-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Right Panel - Actions & Context */}
      <aside className="w-72 bg-white/70 backdrop-blur-sm border-l border-slate-200 flex flex-col shrink-0 overflow-y-auto">
        <div className="p-6">
          {/* Suggested Actions */}
          <section className="mb-8">
            <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
              Suggested Actions
            </h3>
            {suggestedActions.length > 0 ? (
              <div className="space-y-2">
                {suggestedActions.map(action => (
                  <ActionCard
                    key={action.id}
                    action={action}
                    onQueue={() => {
                      // Queue action logic
                      setSuggestedActions(prev => prev.filter(a => a.id !== action.id))
                    }}
                    onReject={() => {
                      setSuggestedActions(prev => prev.filter(a => a.id !== action.id))
                    }}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-400">No suggestions yet</p>
            )}
          </section>

          {/* Pending Approvals */}
          <section className="mb-8">
            <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
              Pending Approvals ({pendingActions.length})
            </h3>
            {pendingActions.length > 0 ? (
              <div className="space-y-2">
                {pendingActions.map(action => (
                  <div
                    key={action.action_id}
                    className="p-3 bg-white rounded-lg border border-slate-200 shadow-sm"
                  >
                    <p className="text-sm font-medium text-slate-700">{action.summary}</p>
                    <p className="text-xs text-slate-500 mb-2">{action.action_type}</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleApproveAction(action.action_id)}
                        className="text-xs bg-green-500 hover:bg-green-600 text-white px-2 py-1 rounded"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleRejectAction(action.action_id)}
                        className="text-xs text-slate-500 hover:text-red-500"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-400">No pending approvals</p>
            )}
          </section>

          {/* Care Gaps */}
          {patientSummary && patientSummary.careGaps.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
                Care Gaps
              </h3>
              <div className="space-y-2">
                {patientSummary.careGaps.map((gap, i) => (
                  <CareGapCard key={i} gap={gap} />
                ))}
              </div>
            </section>
          )}
        </div>
      </aside>
    </div>
  )
}
