export type DentalKnowledgeReviewStatus = 'draft' | 'in_review' | 'approved' | 'rejected'

export interface DentalKnowledgeReviewRecord {
  id: string
  clinic_id: string
  entry_key: string
  version: number
  topic: string
  locale: string
  title: string
  content: string
  source_name: string
  source_reference: string
  review_status: DentalKnowledgeReviewStatus
  active: boolean
  clinically_reviewed: boolean
  approved_for_patient_education: boolean
  submitted_by?: string | null
  submitted_at?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
  decision_note?: string | null
  retired_at?: string | null
  created_at: string
  updated_at: string
}

interface ApiEnvelope<T> { data: T }

export function useDentalKnowledgeReview() {
  const api = useApi()
  const base = '/api/v1/patient_agent/knowledge'

  async function list(reviewStatus?: DentalKnowledgeReviewStatus): Promise<ApiEnvelope<DentalKnowledgeReviewRecord[]>> {
    const qs = reviewStatus ? `?review_status=${encodeURIComponent(reviewStatus)}` : ''
    return await api.get<ApiEnvelope<DentalKnowledgeReviewRecord[]>>(`${base}${qs}`)
  }

  async function get(id: string): Promise<ApiEnvelope<DentalKnowledgeReviewRecord>> {
    return await api.get<ApiEnvelope<DentalKnowledgeReviewRecord>>(`${base}/${id}`)
  }

  async function submit(id: string): Promise<ApiEnvelope<DentalKnowledgeReviewRecord>> {
    return await api.post<ApiEnvelope<DentalKnowledgeReviewRecord>>(`${base}/${id}/submit`, {})
  }

  async function approve(id: string, decisionNote?: string): Promise<ApiEnvelope<DentalKnowledgeReviewRecord>> {
    return await api.post<ApiEnvelope<DentalKnowledgeReviewRecord>>(`${base}/${id}/approve`, {
      decision_note: decisionNote?.trim() || null
    })
  }

  async function reject(id: string, decisionNote: string): Promise<ApiEnvelope<DentalKnowledgeReviewRecord>> {
    return await api.post<ApiEnvelope<DentalKnowledgeReviewRecord>>(`${base}/${id}/reject`, {
      decision_note: decisionNote.trim()
    })
  }

  return { list, get, submit, approve, reject }
}
