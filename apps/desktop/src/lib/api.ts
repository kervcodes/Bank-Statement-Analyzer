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

// The fixed v1 category taxonomy (mirrors app/models/taxonomy.py -- the
// backend is the source of truth and rejects anything outside this list).
export const CATEGORIES = [
  'Income',
  'Transfers',
  'Credit Card Payments',
  'Housing',
  'Utilities',
  'Groceries',
  'Dining',
  'Transportation',
  'Fuel',
  'Shopping',
  'Entertainment',
  'Subscriptions',
  'Healthcare',
  'Insurance',
  'Education',
  'Travel',
  'Personal Care',
  'Fees & Interest',
  'Cash & ATM',
  'Taxes',
  'Debt Payments',
  'Uncategorized',
] as const

export interface TransactionSource {
  statement_id: string
  bank: string
  account_type: string
  account_identifier_masked: string
  period_start: string
  period_end: string
  source_page: number
  parser_version: string
}

export interface TransactionDetail {
  id: string
  transaction_date: string
  posted_date: string
  amount_cents: number
  direction: 'CREDIT' | 'DEBIT'
  category: string
  category_source: string
  predicted_category: string | null
  user_category: string | null
  merchant_normalized: string | null
  description_normalized: string
  description_raw: string
  dedup_status: string
  source: TransactionSource
}

export interface TransactionCategoryResponse {
  id: string
  merchant_normalized: string | null
  category: string
  category_source: string
  predicted_category: string | null
  user_category: string | null
}

export interface TransactionListItem {
  id: string
  transaction_date: string
  merchant: string
  description_normalized: string
  amount_cents: number
  direction: 'CREDIT' | 'DEBIT'
  category: string
  category_source: string
  bank: string
  account_identifier_masked: string
  dedup_status: string
}

export interface TransactionListResponse {
  items: TransactionListItem[]
  page: number
  page_size: number
  total: number
}

export type TransactionSort =
  | 'date_desc'
  | 'date_asc'
  | 'amount_desc'
  | 'amount_asc'

export interface ListTransactionsParams {
  category?: string
  merchant?: string
  accountId?: string
  batchId?: string
  dateFrom?: string
  dateTo?: string
  includeDuplicates?: boolean
  spendingOnly?: boolean
  sort?: TransactionSort
  page?: number
  pageSize?: number
}

export interface ReviewTransaction {
  id: string
  statement_id: string
  account_identifier_masked: string
  bank: string
  transaction_date: string
  description_normalized: string
  amount_cents: number
  direction: 'CREDIT' | 'DEBIT'
}

export interface PossibleDuplicate {
  transaction: ReviewTransaction
  matches: ReviewTransaction
}

export interface DuplicatesResponse {
  possible_duplicates: PossibleDuplicate[]
}

export type DuplicateAction = 'keep_both' | 'confirm'

export interface DuplicateActionResponse {
  id: string
  dedup_status: string
}

export interface UncategorizedGroup {
  merchant: string
  transaction_count: number
  total_cents: number
  suggested_category: string | null
  sample_description: string
}

export interface UncategorizedResponse {
  groups: UncategorizedGroup[]
}

export interface RuleWriteResponse {
  merchant: string
  category: string | null
  transactions_recategorized: number
}

export interface PeriodCashFlow {
  period: string // "YYYY-MM"
  credits_cents: number
  debits_cents: number
  net_cents: number
  spending_cents: number
  transfers_cents: number
}

export interface CategoryTotal {
  category: string
  total_cents: number
  transaction_count: number
}

export interface MerchantTotal {
  merchant: string
  total_cents: number
  transaction_count: number
}

export interface RecurringCharge {
  merchant: string
  cadence: 'weekly' | 'biweekly' | 'monthly' | 'annual'
  typical_amount_cents: number
  occurrences: number
  first_seen: string
  last_seen: string
}

export interface Trends {
  current_period: string | null
  previous_period: string | null
  spending_delta_cents: number
  spending_delta_ratio: string | null
  net_delta_cents: number
  net_delta_ratio: string | null
}

export interface ExcludedStatementSummary {
  statement_id: string
  bank: string
  account_identifier_masked: string
  period_start: string
  period_end: string
  reason: string
}

export interface CoverageSummary {
  statements_included: number
  statements_excluded: number
  transaction_count: number
  ledger_start: string | null
  ledger_end: string | null
  excluded: ExcludedStatementSummary[]
}

export interface Analytics {
  start: string | null
  end: string | null
  cash_flow: PeriodCashFlow[]
  spending_by_category: CategoryTotal[]
  merchant_totals: MerchantTotal[]
  recurring_charges: RecurringCharge[]
  trends: Trends
  coverage: CoverageSummary
}

export interface ExplanationResponse {
  provider: string | null
  model: string | null
  text: string | null
}

// --- calls ---------------------------------------------------------------

function qs(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

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

  getTransaction: (id: string) =>
    request<TransactionDetail>(`/transactions/${id}`),

  listTransactions: (params: ListTransactionsParams = {}) =>
    request<TransactionListResponse>(
      `/transactions${qs({
        category: params.category,
        merchant: params.merchant,
        account_id: params.accountId,
        batch_id: params.batchId,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        include_duplicates: params.includeDuplicates,
        spending_only: params.spendingOnly,
        sort: params.sort,
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),

  setTransactionCategory: (id: string, category: string) =>
    request<TransactionCategoryResponse>(`/transactions/${id}/category`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category }),
    }),

  getPossibleDuplicates: () =>
    request<DuplicatesResponse>('/review/duplicates'),

  resolveDuplicate: (id: string, action: DuplicateAction) =>
    request<DuplicateActionResponse>(`/review/duplicates/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    }),

  getUncategorized: () => request<UncategorizedResponse>('/review/categorizations'),

  upsertCategoryRule: (merchant: string, category: string) =>
    request<RuleWriteResponse>('/category-rules', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ merchant, category }),
    }),

  getAnalytics: (start?: string, end?: string) =>
    request<Analytics>(`/analytics${qs({ start, end })}`),

  getAnalyticsExplanation: (start?: string, end?: string) =>
    request<ExplanationResponse>(`/analytics/explanation${qs({ start, end })}`),
}

export const BATCH_TERMINAL = new Set([
  'COMPLETED',
  'COMPLETED_WITH_WARNINGS',
  'FAILED',
])
