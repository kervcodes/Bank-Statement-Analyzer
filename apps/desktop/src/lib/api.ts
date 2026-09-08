/**
 * Typed wrappers over the FastAPI backend. One base URL, one error shape.
 * Server state lives in TanStack Query; nothing here holds state.
 */

export const API_BASE =
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8420'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch (cause) {
    throw new ApiError(0, `Could not reach the backend (${String(cause)})`)
  }
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => (b as { detail?: string }).detail)
      .catch(() => undefined)
    throw new ApiError(res.status, detail ?? `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

// --- shapes (mirror the Pydantic response models) --------------------------

export type IntakeFileStatus =
  | 'ACCEPTED'
  | 'UPLOAD_FAILED'
  | 'VALIDATION_FAILED'

export interface IntakeFileResult {
  filename: string
  status: IntakeFileStatus
  failure_reason: string | null
}

export interface BatchIntakeResponse {
  batch_id: string
  status: string
  selected: number
  uploaded: number
  upload_failed: number
  validation_failed: number
  files: IntakeFileResult[]
}

export interface BatchListItem {
  id: string
  created_at: string
  status: string
  selected: number
  uploaded: number
  upload_failed: number
  validation_failed: number
  processed: number
  processing_failed: number
  statement_count: number
  period_start: string | null
  period_end: string | null
}

export interface BatchListResponse {
  items: BatchListItem[]
  page: number
  page_size: number
  total: number
}

export interface JobStatus {
  id: string
  status: string
  attempt_count: number
  failure_reason: string | null
  extraction_method: string | null
}

export interface StatementSummary {
  id: string
  bank: string
  account_type: string
  account_identifier_masked: string
  extraction_status: string
  validation_result: string | null
  dedup_status: string
}

export interface BatchStatusResponse {
  batch_id: string
  status: string
  selected: number
  uploaded: number
  upload_failed: number
  validation_failed: number
  processed: number
  processing_failed: number
  possible_duplicate_count: number
  uncategorized_count: number
  jobs: JobStatus[]
  statements: StatementSummary[]
}

// --- calls ---------------------------------------------------------------

export const api = {
  listBatches: (page = 1, pageSize = 20) =>
    request<BatchListResponse>(
      `/batches?page=${page}&page_size=${pageSize}`,
    ),

  getBatch: (id: string) =>
    request<BatchStatusResponse>(`/batches/${id}`),

  createBatch: (files: File[]) => {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    return request<BatchIntakeResponse>('/batches', {
      method: 'POST',
      body: form,
    })
  },
}

export const BATCH_TERMINAL = new Set([
  'COMPLETED',
  'COMPLETED_WITH_WARNINGS',
  'FAILED',
])
