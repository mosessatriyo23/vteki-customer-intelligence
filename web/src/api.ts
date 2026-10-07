export type ApiUser = { id: number; email: string; roles: string[] }
export type ApiCustomer = {
  id: number
  customer_code: string
  full_name: string
  email: string
  segment: string
  ltv: number
  churn_risk: string
  next_best_action: string | null
  created_at: string
}
export type ApiCampaign = {
  id: number
  name: string
  target_segment: string
  channel: string
  ab_test_ratio: number
  status: string
  message_draft: string | null
  approved_by: number | null
  approved_at: string | null
  created_by: number | null
  created_at: string
}
export type ApiReview = {
  id: number
  subject_reference: string
  candidate_references: string[]
  confidence: number
  flagged_reason: string
  status: string
  decision: string | null
  reviewer_id: number | null
  review_note: string | null
  created_at: string
  reviewed_at: string | null
}
export type ApiDecision = {
  id: number
  customer_id: number
  customer_code: string
  customer_name: string
  recommended_action: string
  rationale: Record<string, unknown>
  status: string
  selected_action: string | null
  overridden_by: number | null
  override_reason: string | null
  created_at: string
}

const API_ROOT = '/api'
const TOKEN_KEY = 'vteki.access-token'

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function storeToken(token: string | null): void {
  if (token) window.localStorage.setItem(TOKEN_KEY, token)
  else window.localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, token?: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  headers.set('X-Correlation-ID', globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try {
    response = await fetch(`${API_ROOT}${path}`, { ...init, headers })
  } catch {
    throw new ApiError('API tidak dapat dijangkau. Pastikan layanan API sedang berjalan.', 0)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : Array.isArray(body?.detail)
        ? body.detail.map((item) => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)).join('; ')
        : `Permintaan gagal (${response.status})`
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  login: (email: string, password: string) => request<{ access_token: string; token_type: string; expires_in: number }>('/auth/login', null, { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: (token: string) => request<ApiUser>('/auth/me', token),
  customers: (token: string, query = '') => request<ApiCustomer[]>(`/customers?limit=200${query ? `&q=${encodeURIComponent(query)}` : ''}`, token),
  customerProvenance: (token: string, id: number) => request<Record<string, unknown>>(`/customers/${id}/provenance`, token),
  seedCustomers: (token: string) => request<{ message: string }>('/customers/seed', token, { method: 'POST' }),
  campaigns: (token: string) => request<ApiCampaign[]>('/campaigns', token),
  createCampaign: (token: string, payload: { name: string; target_segment: string; channel: string; message_draft: string }) => request<ApiCampaign>('/campaigns', token, { method: 'POST', body: JSON.stringify(payload) }),
  submitCampaign: (token: string, id: number) => request<ApiCampaign>(`/campaigns/${id}/request-approval`, token, { method: 'POST' }),
  approveCampaign: (token: string, id: number) => request<ApiCampaign>(`/campaigns/${id}/approve`, token, { method: 'POST' }),
  rejectCampaign: (token: string, id: number, reviewComment: string) => request<{ status: string }>(`/governance/campaigns/${id}/approval`, token, { method: 'POST', body: JSON.stringify({ approved: false, review_comment: reviewComment }) }),
  launchCampaign: (token: string, id: number) => request<{ status: string; batch_job_id: number }>(`/campaigns/${id}/launch`, token, { method: 'POST' }),
  reviews: (token: string) => request<ApiReview[]>('/governance/identity-reviews?status_filter=', token),
  resolveReview: (token: string, id: number, approved: boolean, note: string) => request<ApiReview>(`/governance/identity-reviews/${id}/resolve`, token, { method: 'POST', body: JSON.stringify({ decision: approved ? 'approved' : 'rejected', review_note: note }) }),
  decisions: (token: string) => request<ApiDecision[]>('/governance/nba-decisions', token),
  createReview: (token: string, payload: { subject_reference: string; candidate_references: string[]; confidence: number; reason: string }) => request<{ id: number; status: string }>('/identity-reviews', token, { method: 'POST', body: JSON.stringify(payload) }),
  createDecision: (token: string, payload: { customer_id: number; recommended_action: string; rationale: Record<string, unknown> }) => request<{ id: number; status: string }>('/decisions/next-best-actions', token, { method: 'POST', body: JSON.stringify(payload) }),
  overrideDecision: (token: string, id: number, selectedAction: string, reason: string) => request<Record<string, unknown>>(`/governance/nba-decisions/${id}/override`, token, { method: 'POST', body: JSON.stringify({ selected_action: selectedAction, override_reason: reason }) }),
  monitoring: (token: string) => request<{ drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }>('/monitoring/dashboard', token),
  reconstruct: (token: string, correlationId: string) => request<Record<string, unknown>>(`/governance/reconstruct/${encodeURIComponent(correlationId)}`, token),
}
