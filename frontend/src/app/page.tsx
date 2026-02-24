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
  PortalMode,
} from '@/lib/types'

// API functions
async function sendMessage(
  message: string,
  conversationId?: string,
  patientId?: string,
  mode: PortalMode = 'clinician'
): Promise<{
  content: string
  conversation_id: string
  pending_actions: any[]
  warnings: any[]
}> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 120_000)

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: conversationId, patient_id: patientId, mode }),
      signal: controller.signal,
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || 'Failed to send message')
    }
    return response.json()
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Request timed out — please try again.')
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}

async function searchPatients(query: string): Promise<{ patients: Patient[] }> {
  const response = await fetch(`/api/patients/search?q=${encodeURIComponent(query)}`)
  if (!response.ok) throw new Error('Failed to search patients')
  const data = await response.json()
  return { patients: data.patients || [] }
}

async function getPatientSummary(patientId: string): Promise<PatientSummary> {
  const response = await fetch(`/api/patients/${patientId}/summary`)
  if (!response.ok) throw new Error('Failed to get patient summary')
  const data = await response.json()
  return {
    patient: data.patient || { id: patientId, name: 'Unknown' },
    conditions: data.conditions || [],
    medications: data.medications || [],
    allergies: data.allergies || [],
    labs: data.labs || [],
    vitals: data.vitals || [],
    immunizations: data.immunizations || [],
    procedures: data.procedures || [],
    encounters: data.encounters || [],
    clinicalNotes: data.clinicalNotes || [],
    careGaps: data.careGaps || [],
    incompleteData: data.incompleteData || [],
  }
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

async function getPatientNarrative(
  patientId: string,
  mode: PortalMode = 'clinician'
): Promise<{ narrative: string; generated_at: number; cached: boolean }> {
  const response = await fetch(`/api/patients/${patientId}/narrative?mode=${mode}`)
  if (!response.ok) throw new Error('Failed to get narrative')
  return response.json()
}

export default function ChatPage() {
  // Portal mode
  const [portalMode, setPortalMode] = useState<PortalMode>('clinician')
  const isPatientMode = portalMode === 'patient'

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
  const [narrative, setNarrative] = useState<string | null>(null)
  const [narrativeLoading, setNarrativeLoading] = useState(false)
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

  // Re-generate narrative when mode changes (with existing patient)
  useEffect(() => {
    if (activePatientId) {
      setNarrativeLoading(true)
      getPatientNarrative(activePatientId, portalMode)
        .then(result => setNarrative(result.narrative))
        .catch(console.error)
        .finally(() => setNarrativeLoading(false))
    }
  }, [portalMode, activePatientId])

  // Handle mode switch
  const handleModeSwitch = (newMode: PortalMode) => {
    setPortalMode(newMode)
    // Reset conversation when switching modes (new system prompt)
    setConversationIds(new Map())
    // Clear messages for fresh start with new persona
    if (activePatientId) {
      setThreads(prev => {
        const newThreads = new Map(prev)
        const existing = newThreads.get(activePatientId)
        if (existing) {
          newThreads.set(activePatientId, { ...existing, messages: [] })
        }
        return newThreads
      })
    }
  }

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

      // Generate suggested actions from care gaps (clinician mode only)
      if (!isPatientMode) {
        const suggestions: ActionableItem[] = (summary?.careGaps || []).map((gap, i) => ({
          id: `suggestion-${i}`,
          type: gap.type === 'immunization' ? 'order' as const : 'referral' as const,
          description: gap.description,
          priority: gap.priority as 'high' | 'routine' | 'low',
          reason: `Identified from care gap analysis`,
          status: 'suggested' as const,
        }))
        setSuggestedActions(suggestions)
      } else {
        setSuggestedActions([])
      }

      // Fetch narrative (non-blocking)
      setNarrativeLoading(true)
      getPatientNarrative(patient.id, portalMode)
        .then(result => setNarrative(result.narrative))
        .catch(console.error)
        .finally(() => setNarrativeLoading(false))
    } catch (error) {
      console.error('Error getting patient summary:', error)
    }
  }

  // Handle send message
  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    if (!activePatientId) {
      alert(isPatientMode ? 'Please select your record first' : 'Please select a patient first')
      return
    }

    const userMessage: Message = {
      role: 'user',
      content: input,
      timestamp: new Date(),
    }

    setThreads(prev => {
      const newThreads = new Map(prev)
      const existing = newThreads.get(activePatientId)
      if (existing) {
        newThreads.set(activePatientId, {
          ...existing,
          messages: [...existing.messages, userMessage],
          lastActivity: new Date(),
        })
      }
      return newThreads
    })

    setInput('')
    setIsLoading(true)

    try {
      const conversationId = conversationIds.get(activePatientId)
      const response = await sendMessage(input, conversationId, activePatientId, portalMode)

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

      setThreads(prev => {
        const newThreads = new Map(prev)
        const existing = newThreads.get(activePatientId)
        if (existing) {
          newThreads.set(activePatientId, {
            ...existing,
            messages: [...existing.messages, assistantMessage],
            lastActivity: new Date(),
          })
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
        const existing = newThreads.get(activePatientId)
        if (existing) {
          newThreads.set(activePatientId, {
            ...existing,
            messages: [...existing.messages, errorMessage],
          })
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

      if (activePatientId) {
        getPatientNarrative(activePatientId, portalMode)
          .then(result => setNarrative(result.narrative))
          .catch(console.error)
      }
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

  // Send a quick pre-built message (for patient portal quick actions)
  const sendQuickMessage = async (text: string) => {
    if (!activePatientId || isLoading) return
    setInput(text)
    // Directly invoke the send logic with the text
    const userMessage: Message = { role: 'user', content: text, timestamp: new Date() }
    setThreads(prev => {
      const newThreads = new Map(prev)
      const existing = newThreads.get(activePatientId)
      if (existing) {
        newThreads.set(activePatientId, {
          ...existing,
          messages: [...existing.messages, userMessage],
          lastActivity: new Date(),
        })
      }
      return newThreads
    })
    setInput('')
    setIsLoading(true)
    try {
      const conversationId = conversationIds.get(activePatientId)
      const response = await sendMessage(text, conversationId, activePatientId, portalMode)
      if (!conversationId) {
        setConversationIds(prev => { const n = new Map(prev); n.set(activePatientId, response.conversation_id); return n })
      }
      const assistantMessage: Message = { role: 'assistant', content: response.content, timestamp: new Date() }
      setThreads(prev => {
        const newThreads = new Map(prev)
        const existing = newThreads.get(activePatientId)
        if (existing) {
          newThreads.set(activePatientId, { ...existing, messages: [...existing.messages, assistantMessage], lastActivity: new Date() })
        }
        return newThreads
      })
    } catch (error) {
      console.error('Quick message error:', error)
    } finally {
      setIsLoading(false)
    }
  }

  // Patient-friendly first name
  const patientFirstName = patientSummary?.patient.name?.split(',')[0]?.split(' ')[0] || 'there'

  // Section title helper
  const sectionTitle = (clinician: string, patient: string) =>
    isPatientMode ? patient : clinician

  return (
    <div className="h-screen overflow-hidden flex">
      {/* Left Sidebar */}
      <aside className={`w-64 flex flex-col shrink-0 shadow-xl ${
        isPatientMode ? 'bg-emerald-900' : 'bg-bg-nav'
      } text-text-primary`}>
        <div className="p-6 flex flex-col h-full">
          {/* Logo + Mode Toggle */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 relative flex items-center justify-center">
                <svg className="w-full h-full text-text-primary opacity-90" viewBox="0 0 100 100">
                  <circle cx="40" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
                  <circle cx="60" cy="50" fill="none" r="25" stroke="currentColor" strokeWidth="2" />
                </svg>
              </div>
              <h1 className="text-lg font-medium text-white">
                {isPatientMode ? 'My Health' : 'AgentEHR'}
              </h1>
            </div>

            {/* Mode Toggle */}
            <div className="flex bg-white/10 rounded-lg p-0.5">
              <button
                onClick={() => handleModeSwitch('clinician')}
                className={`flex-1 text-xs py-1.5 rounded-md transition-all ${
                  !isPatientMode
                    ? 'bg-white/20 text-white font-medium'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Clinician
              </button>
              <button
                onClick={() => handleModeSwitch('patient')}
                className={`flex-1 text-xs py-1.5 rounded-md transition-all ${
                  isPatientMode
                    ? 'bg-white/20 text-white font-medium'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Patient
              </button>
            </div>
          </div>

          {isPatientMode ? (
            /* Patient Mode Sidebar */
            <>
              {patientSummary ? (
                <div className="mb-6">
                  <p className="text-emerald-200 text-sm mb-1">Welcome,</p>
                  <p className="text-white font-medium text-lg">{patientFirstName}</p>
                </div>
              ) : (
                <div className="mb-4">
                  <p className="text-emerald-200 text-xs mb-2">Select your record</p>
                  <input
                    type="text"
                    placeholder="Search by name..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handlePatientSearch()}
                    className="w-full px-3 py-2 bg-white/10 rounded text-sm placeholder:text-emerald-300/50 focus:outline-none focus:ring-1 focus:ring-emerald-400 text-white"
                  />
                  {searchResults.length > 0 && (
                    <div className="mt-2">
                      {searchResults.slice(0, 5).map((patient) => (
                        <button
                          key={patient.id}
                          onClick={() => handleSelectPatient(patient)}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-white/10 rounded transition-colors text-emerald-100 hover:text-white"
                        >
                          {patient.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Patient Navigation */}
              <nav className="space-y-1 flex-1">
                {[
                  { label: 'Health Summary', icon: '♥', section: 'top' },
                  { label: 'My Medications', icon: '💊', section: 'section-medications' },
                  { label: 'My Conditions', icon: '📋', section: 'section-conditions' },
                  { label: 'My Test Results', icon: '🔬', section: 'section-labs' },
                  { label: 'My Vaccinations', icon: '💉', section: 'section-immunizations' },
                  { label: 'My Visit Notes', icon: '📝', section: 'section-notes' },
                ].map(item => (
                  <button
                    key={item.section}
                    onClick={() => {
                      const el = document.getElementById(item.section)
                      el?.scrollIntoView({ behavior: 'smooth' })
                    }}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-white/10 rounded transition-colors text-emerald-100 hover:text-white flex items-center gap-2"
                  >
                    <span className="text-xs">{item.icon}</span>
                    {item.label}
                  </button>
                ))}
              </nav>
            </>
          ) : (
            /* Clinician Mode Sidebar */
            <>
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
            </>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col relative ethereal-bg min-w-0">
        {/* Sticky Patient Header */}
        {patientSummary && (
          <div id="top" className={`px-8 pt-6 pb-4 backdrop-blur-sm border-b shrink-0 ${
            isPatientMode
              ? 'bg-emerald-50/80 border-emerald-200'
              : 'bg-white/80 border-slate-200'
          }`}>
            <h1 className={`font-serif text-3xl ${isPatientMode ? 'text-emerald-900' : 'text-slate-800'}`}>
              {isPatientMode
                ? `Welcome, ${patientFirstName}`
                : patientSummary.patient.name
              }
            </h1>
            <p className="text-slate-500 text-sm mt-1">
              {patientSummary.patient.age}yo {patientSummary.patient.gender}
              {' · '}DOB {patientSummary.patient.birthDate || 'Unknown'}
              {!isPatientMode && patientSummary.patient.mrn && ` · MRN ${patientSummary.patient.mrn}`}
            </p>
            {/* Brief narrative summary */}
            {narrativeLoading ? (
              <p className="text-sm text-slate-400 italic mt-2">
                {isPatientMode ? 'Loading your health summary...' : 'Generating summary...'}
              </p>
            ) : narrative ? (
              <p className="text-sm text-slate-500 mt-2 leading-relaxed line-clamp-3">{narrative}</p>
            ) : null}
          </div>
        )}

        <div className="flex-1 p-8 overflow-y-auto">
          {patientSummary ? (
            <>
              {/* Quick Status Pills */}
              <div className="flex flex-wrap gap-2 mb-6">
                <StatusPill
                  label={isPatientMode ? 'Allergies' : 'Allergies'}
                  count={patientSummary.allergies?.length ?? 0}
                  color={(patientSummary.allergies?.length ?? 0) === 0 ? 'amber' : 'red'}
                />
                <StatusPill
                  label={isPatientMode ? 'Medications' : 'Medications'}
                  count={patientSummary.medications?.length ?? 0}
                  color="blue"
                />
                <StatusPill
                  label={isPatientMode ? 'Conditions' : 'Conditions'}
                  count={patientSummary.conditions?.filter(c => c.isActive).length ?? 0}
                  color="slate"
                />
                {!isPatientMode && (patientSummary.careGaps?.length ?? 0) > 0 && (
                  <StatusPill
                    label="Care Gaps"
                    count={patientSummary.careGaps.length}
                    color="orange"
                  />
                )}
              </div>

              {/* Incomplete Data Alert — clinician only */}
              {!isPatientMode && (patientSummary.incompleteData?.length ?? 0) > 0 && (
                <div className="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-sm font-medium text-amber-800 mb-1">Incomplete Record</p>
                  {patientSummary.incompleteData?.map((item, i) => (
                    <p key={i} className="text-sm text-amber-700">• {item.message}</p>
                  ))}
                </div>
              )}

              {/* Collapsible Sections */}
              <div className="max-w-2xl mb-8 bg-white/50 rounded-lg p-4">
                <CollapsibleSection title={sectionTitle('Medications', 'My Medications')} id="section-medications" defaultOpen={true}>
                  {(patientSummary.medications?.length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.medications?.map((med, i) => (
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

                <CollapsibleSection title={sectionTitle('Active Conditions', 'My Health Conditions')} id="section-conditions">
                  {(patientSummary.conditions?.filter(c => c.isActive).length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.conditions
                        ?.filter(c => c.isActive)
                        .map((condition, i) => (
                          <div key={i} className="py-1 text-slate-700">{condition.code}</div>
                        ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No active conditions</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title={sectionTitle('Allergies', 'My Allergies')} id="section-allergies">
                  {(patientSummary.allergies?.length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.allergies?.map((allergy, i) => (
                        <div key={i} className="flex items-center gap-2 py-1">
                          <span className="text-red-700 font-medium">{allergy.substance}</span>
                          {allergy.reaction && (
                            <span className="text-slate-500 text-sm">({allergy.reaction})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className={isPatientMode ? 'text-slate-500' : 'text-amber-600'}>
                      {isPatientMode ? 'No allergies on file' : 'No allergies documented - confirm NKDA'}
                    </p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection
                  title={sectionTitle('Recent Labs', 'My Test Results')}
                  id="section-labs"
                  badge={`${patientSummary.labs?.length ?? 0} results`}
                >
                  {(patientSummary.labs?.length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.labs?.slice(0, 10).map((lab, i) => (
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
                    <p className="text-slate-500">No recent {isPatientMode ? 'test results' : 'lab results'}</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title={sectionTitle('Vitals', 'My Vitals')} id="section-vitals">
                  {(patientSummary.vitals?.length ?? 0) > 0 ? (
                    <div className="grid grid-cols-2 gap-2">
                      {patientSummary.vitals?.slice(0, 6).map((vital, i) => (
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

                <CollapsibleSection title={sectionTitle('Immunizations', 'My Vaccinations')} id="section-immunizations">
                  {(patientSummary.immunizations?.length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.immunizations?.map((imm, i) => (
                        <div key={i} className="flex items-center justify-between py-1">
                          <span className="text-slate-700">{imm.vaccine}</span>
                          {imm.date && (
                            <span className="text-slate-400 text-sm">{imm.date}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-500">No {isPatientMode ? 'vaccination' : 'immunization'} records</p>
                  )}
                </CollapsibleSection>

                <CollapsibleSection title={sectionTitle('Procedures', 'My Procedures')} id="section-procedures">
                  {(patientSummary.procedures?.length ?? 0) > 0 ? (
                    <div className="space-y-1">
                      {patientSummary.procedures?.map((proc, i) => (
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

                <CollapsibleSection title={sectionTitle('Clinical Notes', 'My Visit Notes')} id="section-notes">
                  {(patientSummary.clinicalNotes?.length ?? 0) > 0 ? (
                    <div className="space-y-2">
                      {patientSummary.clinicalNotes?.map((note, i) => (
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
                    <p className="text-slate-500">No {isPatientMode ? 'visit notes' : 'clinical notes'}</p>
                  )}
                </CollapsibleSection>
              </div>

              {/* Chat Messages */}
              {currentMessages.length > 0 && (
                <div className="max-w-2xl space-y-4 mb-4">
                  <h3 className="text-sm font-semibold text-slate-600 uppercase tracking-wide">
                    {isPatientMode ? 'Chat with Health Assistant' : 'Conversation'}
                  </h3>
                  {currentMessages.map((message, i) => (
                    <div key={i}>
                      {message.role === 'user' ? (
                        <div className="flex justify-end">
                          <div className={`max-w-[80%] px-4 py-2 rounded-2xl rounded-br-sm ${
                            isPatientMode ? 'bg-emerald-500 text-white' : 'bg-cyan-500 text-white'
                          }`}>
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
                      <span className={`w-2 h-2 rounded-full animate-bounce ${isPatientMode ? 'bg-emerald-500' : 'bg-cyan-500'}`} style={{ animationDelay: '0ms' }} />
                      <span className={`w-2 h-2 rounded-full animate-bounce ${isPatientMode ? 'bg-emerald-500' : 'bg-cyan-500'}`} style={{ animationDelay: '150ms' }} />
                      <span className={`w-2 h-2 rounded-full animate-bounce ${isPatientMode ? 'bg-emerald-500' : 'bg-cyan-500'}`} style={{ animationDelay: '300ms' }} />
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
              <h2 className="text-2xl font-serif text-slate-700 mb-2">
                {isPatientMode ? 'Welcome to Your Health Portal' : 'Welcome to AgentEHR'}
              </h2>
              <p className="text-slate-500">
                {isPatientMode
                  ? 'Search for your name to load your health record'
                  : 'Search for a patient to get started'
                }
              </p>
            </div>
          )}
        </div>

        {/* Chat Input */}
        {activePatientId && (
          <div className="p-6 bg-gradient-to-t from-white to-transparent">
            <div className="max-w-2xl mx-auto">
              <div className={`flex items-center gap-2 rounded-lg shadow-sm border px-4 py-2 ${
                isPatientMode
                  ? 'bg-white border-emerald-200'
                  : 'bg-white border-slate-200'
              }`}>
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  placeholder={
                    isPatientMode
                      ? 'Ask about your health, medications, test results...'
                      : `Ask about ${patientSummary?.patient.name.split(' ')[0] || 'this patient'}...`
                  }
                  className="flex-1 bg-transparent focus:outline-none text-sm text-slate-700 placeholder:text-slate-400"
                />
                <button
                  onClick={handleSend}
                  disabled={isLoading || !input.trim()}
                  className={`p-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                    isPatientMode
                      ? 'text-emerald-500 hover:text-emerald-600'
                      : 'text-cyan-500 hover:text-cyan-600'
                  }`}
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

      {/* Right Panel */}
      <aside className="w-72 bg-white/70 backdrop-blur-sm border-l border-slate-200 flex flex-col shrink-0 overflow-y-auto">
        <div className="p-6">
          {isPatientMode ? (
            /* Patient Mode Right Panel */
            <>
              {/* My Requests */}
              <section className="mb-8">
                <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
                  My Requests
                </h3>
                {pendingActions.length > 0 ? (
                  <div className="space-y-2">
                    {pendingActions.map(action => (
                      <div
                        key={action.action_id}
                        className="p-3 bg-white rounded-lg border border-emerald-200 shadow-sm"
                      >
                        <p className="text-sm font-medium text-slate-700">{action.summary}</p>
                        <p className="text-xs text-emerald-600 mt-1">
                          {action.status === 'pending' ? 'Awaiting review' : action.status}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No pending requests</p>
                )}
              </section>

              {/* Upcoming */}
              <section className="mb-8">
                <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
                  Upcoming
                </h3>
                {patientSummary?.encounters && patientSummary.encounters.length > 0 ? (
                  <div className="space-y-2">
                    {patientSummary.encounters.slice(0, 3).map((enc, i) => (
                      <div key={i} className="p-3 bg-white rounded-lg border border-slate-200 shadow-sm">
                        <p className="text-sm font-medium text-slate-700">{enc.type || 'Visit'}</p>
                        {enc.date && <p className="text-xs text-slate-500">{enc.date}</p>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No upcoming items</p>
                )}
              </section>

              {/* Quick Actions */}
              <section>
                <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
                  Quick Actions
                </h3>
                <div className="space-y-2">
                  <button
                    onClick={() => sendQuickMessage('I need to schedule an appointment')}
                    className="w-full text-left p-3 bg-white rounded-lg border border-slate-200 shadow-sm hover:border-emerald-300 transition-colors"
                  >
                    <p className="text-sm font-medium text-slate-700">Schedule Appointment</p>
                    <p className="text-xs text-slate-500">Request a new appointment</p>
                  </button>
                  <button
                    onClick={() => sendQuickMessage('I need a prescription refill')}
                    className="w-full text-left p-3 bg-white rounded-lg border border-slate-200 shadow-sm hover:border-emerald-300 transition-colors"
                  >
                    <p className="text-sm font-medium text-slate-700">Request Refill</p>
                    <p className="text-xs text-slate-500">Request a medication refill</p>
                  </button>
                  <button
                    onClick={() => sendQuickMessage('Help me prepare questions for my next doctor visit')}
                    className="w-full text-left p-3 bg-white rounded-lg border border-slate-200 shadow-sm hover:border-emerald-300 transition-colors"
                  >
                    <p className="text-sm font-medium text-slate-700">Prepare for Visit</p>
                    <p className="text-xs text-slate-500">Get help preparing questions</p>
                  </button>
                </div>
              </section>
            </>
          ) : (
            /* Clinician Mode Right Panel */
            <>
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
              {patientSummary && (patientSummary.careGaps?.length ?? 0) > 0 && (
                <section>
                  <h3 className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wide">
                    Care Gaps
                  </h3>
                  <div className="space-y-2">
                    {patientSummary.careGaps?.map((gap, i) => (
                      <CareGapCard key={i} gap={gap} />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  )
}
