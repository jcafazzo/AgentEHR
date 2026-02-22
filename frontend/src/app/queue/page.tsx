'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import {
  Pill,
  FlaskConical,
  Calendar,
  FileText,
  AlertTriangle,
  Check,
  X,
  ChevronLeft,
  Search,
  Filter,
} from 'lucide-react'

// Types
interface PendingAction {
  action_id: string
  action_type: string
  patient_id: string
  summary: string
  status: string
  created_at: string
  warnings: Warning[]
  resource: Record<string, unknown>
  metadata: Record<string, unknown>
}

interface Warning {
  severity: string
  code: string
  message: string
}

// API functions
async function fetchActions(): Promise<{ actions: PendingAction[]; count: number }> {
  const response = await fetch('/api/actions')
  if (!response.ok) throw new Error('Failed to fetch actions')
  return response.json()
}

async function approveAction(actionId: string): Promise<void> {
  const response = await fetch(`/api/actions/${actionId}/approve`, {
    method: 'POST',
  })
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

// Get icon for action type
function getActionIcon(actionType: string) {
  switch (actionType) {
    case 'MedicationRequest':
      return { icon: Pill, bgColor: 'bg-primary', label: 'Medication' }
    case 'ServiceRequest':
      return { icon: FlaskConical, bgColor: 'bg-secondary', label: 'Lab/Imaging' }
    case 'Appointment':
      return { icon: Calendar, bgColor: 'bg-purple-500', label: 'Appointment' }
    case 'DocumentReference':
    case 'Communication':
      return { icon: FileText, bgColor: 'bg-neutral-500', label: 'Document' }
    default:
      return { icon: FileText, bgColor: 'bg-neutral-400', label: actionType }
  }
}

// Get severity color
function getSeverityColor(severity: string) {
  switch (severity) {
    case 'severe':
    case 'error':
      return 'bg-error-light text-error border-error'
    case 'warning':
      return 'bg-warning-light text-warning border-warning'
    case 'info':
    default:
      return 'bg-success-light text-success border-success'
  }
}

// Action Card component
function ActionCard({
  action,
  onApprove,
  onReject,
}: {
  action: PendingAction
  onApprove: () => void
  onReject: () => void
}) {
  const [isProcessing, setIsProcessing] = useState(false)
  const { icon: Icon, bgColor, label } = getActionIcon(action.action_type)

  const handleApprove = async () => {
    setIsProcessing(true)
    try {
      await onApprove()
    } finally {
      setIsProcessing(false)
    }
  }

  const handleReject = async () => {
    setIsProcessing(true)
    try {
      await onReject()
    } finally {
      setIsProcessing(false)
    }
  }

  const timeAgo = new Date(action.created_at).toLocaleString()

  return (
    <div className="bg-white rounded-lg shadow-md p-5 border-l-4 border-primary">
      <div className="flex items-start gap-4">
        {/* Icon */}
        <div className={`w-12 h-12 ${bgColor} rounded-full flex items-center justify-center flex-shrink-0`}>
          <Icon className="w-6 h-6 text-white" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold text-neutral-800">{action.summary}</h3>
              <p className="text-sm text-neutral-500 mt-1">
                Patient ID: {action.patient_id.slice(0, 8)}...
              </p>
            </div>
            <span className="text-xs text-neutral-400 whitespace-nowrap">{timeAgo}</span>
          </div>

          {/* Warnings */}
          {action.warnings && action.warnings.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {action.warnings.map((warning, i) => (
                <span
                  key={i}
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium border ${getSeverityColor(
                    warning.severity
                  )}`}
                >
                  <AlertTriangle className="w-3 h-3" />
                  {warning.message}
                </span>
              ))}
            </div>
          )}

          {/* Action type label */}
          <span className="inline-block mt-2 px-2 py-0.5 bg-neutral-100 rounded text-xs text-neutral-500">
            {label}
          </span>
        </div>

        {/* Buttons */}
        <div className="flex flex-col gap-2 flex-shrink-0">
          <button
            onClick={handleApprove}
            disabled={isProcessing}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
            Approve
          </button>
          <button
            onClick={handleReject}
            disabled={isProcessing}
            className="flex items-center gap-2 px-4 py-2 border border-neutral-300 text-neutral-600 hover:bg-neutral-100 rounded-lg transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
            Reject
          </button>
        </div>
      </div>
    </div>
  )
}

// Main page component
export default function QueuePage() {
  const [actions, setActions] = useState<PendingAction[]>([])
  const [activeTab, setActiveTab] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  // Fetch actions on mount
  useEffect(() => {
    loadActions()
  }, [])

  const loadActions = async () => {
    setIsLoading(true)
    try {
      const data = await fetchActions()
      setActions(data.actions || [])
    } catch (error) {
      console.error('Error fetching actions:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleApprove = async (actionId: string) => {
    try {
      await approveAction(actionId)
      await loadActions()
    } catch (error) {
      console.error('Error approving action:', error)
    }
  }

  const handleReject = async (actionId: string) => {
    try {
      await rejectAction(actionId)
      await loadActions()
    } catch (error) {
      console.error('Error rejecting action:', error)
    }
  }

  const pendingActions = actions.filter((a) => a.status === 'pending')

  return (
    <div className="min-h-screen bg-neutral-100">
      {/* Header */}
      <header className="bg-white border-b border-neutral-200">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/" className="text-neutral-400 hover:text-neutral-600">
                <ChevronLeft className="w-5 h-5" />
              </Link>
              <div>
                <h1 className="text-xl font-bold text-primary">AgentEHR</h1>
                <p className="text-sm text-neutral-500">Approval Queue</p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="bg-white border-b border-neutral-200">
        <div className="max-w-6xl mx-auto px-6">
          <nav className="flex gap-8">
            <button
              onClick={() => setActiveTab('pending')}
              className={`py-4 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'pending'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700'
              }`}
            >
              Pending
              <span className="ml-2 px-2 py-0.5 bg-primary text-white text-xs rounded-full">
                {pendingActions.length}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('approved')}
              className={`py-4 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'approved'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700'
              }`}
            >
              Approved
            </button>
            <button
              onClick={() => setActiveTab('rejected')}
              className={`py-4 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'rejected'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700'
              }`}
            >
              Rejected
            </button>
          </nav>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white border-b border-neutral-200 py-4">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex items-center gap-4">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
              <input
                type="text"
                placeholder="Search actions..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
            <button className="flex items-center gap-2 px-4 py-2 border border-neutral-200 rounded-lg hover:bg-neutral-50">
              <Filter className="w-4 h-4" />
              Filter
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : pendingActions.length === 0 ? (
          <div className="text-center py-12 text-neutral-400">
            <Check className="w-16 h-16 mx-auto mb-4 text-success" />
            <h3 className="text-lg font-medium text-neutral-600">All caught up!</h3>
            <p className="mt-2">No pending actions require your attention.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {pendingActions.map((action) => (
              <ActionCard
                key={action.action_id}
                action={action}
                onApprove={() => handleApprove(action.action_id)}
                onReject={() => handleReject(action.action_id)}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
