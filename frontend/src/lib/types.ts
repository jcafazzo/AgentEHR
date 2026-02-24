// Portal mode
export type PortalMode = 'clinician' | 'patient'

// Patient and clinical data types

export interface Patient {
  id: string;
  name: string;
  birthDate?: string;
  age?: number;
  gender?: string;
  mrn?: string;
}

export interface Condition {
  id: string;
  code: string;
  status?: string;
  onsetDate?: string;
  isActive?: boolean;
}

export interface Medication {
  id: string;
  medication: string;
  dosage?: string;
  status?: string;
}

export interface Allergy {
  id: string;
  substance: string;
  reaction?: string;
  criticality?: string;
  category?: string;
}

export interface Observation {
  id: string;
  code: string;
  value: string;
  date?: string;
  status?: string;
}

export interface Procedure {
  id: string;
  name: string;
  date?: string;
  status?: string;
}

export interface Immunization {
  id: string;
  vaccine: string;
  date?: string;
  status?: string;
}

export interface Encounter {
  id: string;
  type?: string;
  status?: string;
  date?: string;
}

export interface ClinicalNote {
  id: string;
  type?: string;
  description?: string;
  date?: string;
  status?: string;
}

export interface CareGap {
  type: string;
  description: string;
  priority: 'high' | 'routine' | 'low';
}

export interface IncompleteData {
  field: string;
  message: string;
  priority: 'high' | 'medium' | 'low';
}

export interface PatientSummary {
  patient: Patient;
  conditions: Condition[];
  medications: Medication[];
  allergies: Allergy[];
  labs: Observation[];
  vitals: Observation[];
  immunizations: Immunization[];
  procedures: Procedure[];
  encounters: Encounter[];
  clinicalNotes: ClinicalNote[];
  careGaps: CareGap[];
  incompleteData: IncompleteData[];
}

// Message and thread types

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: Date;
  toolCalls?: any[];
  suggestedActions?: ActionableItem[];
}

export interface PatientThread {
  patientId: string;
  patientName: string;
  messages: Message[];
  lastActivity: Date;
  unreadCount: number;
}

export interface ActionableItem {
  id: string;
  type: 'order' | 'referral' | 'update_record' | 'documentation';
  description: string;
  priority: 'high' | 'routine' | 'low';
  reason: string;
  status: 'suggested' | 'queued' | 'approved' | 'rejected';
  fhirResource?: any;
}

export interface PendingAction {
  action_id: string;
  action_type: string;
  patient_id: string;
  summary: string;
  status: string;
  warnings: any[];
  created_at: number;
}

// API response types

export interface ChatResponse {
  content: string;
  conversation_id: string;
  tool_calls: any[];
  tool_results: any[];
  warnings: any[];
  pending_actions: any[];
}

export interface PatientNarrative {
  narrative: string;
  generated_at: number;
  cached: boolean;
}

export interface PatientSearchResult {
  total: number;
  patients: Patient[];
}
