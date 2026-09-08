import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UploadCloud, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { StatusBadge } from '../components/ui/StatusBadge'
import { api, ApiError, type IntakeFileResult } from '../lib/api'
import { formatBytes, intakeStatusMeta } from '../lib/format'

const MAX_BYTES = 25 * 1024 * 1024 // matches the backend intake limit

interface Picked {
  file: File
  /** client-side pre-check, before upload (design-notes §3.2) */
  precheck: { ok: boolean; reason?: string }
}

function precheck(file: File): Picked['precheck'] {
  if (!file.name.toLowerCase().endsWith('.pdf'))
    return { ok: false, reason: 'not a PDF' }
  if (file.size > MAX_BYTES) return { ok: false, reason: 'over 25 MB' }
  return { ok: true }
}

export function ImportRoute() {
  const [picked, setPicked] = useState<Picked[]>([])
  const [results, setResults] = useState<IntakeFileResult[] | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const ready = picked.filter((p) => p.precheck.ok)

  const add = (files: FileList | null) => {
    if (!files) return
    setResults(null)
    const next = Array.from(files).map((file) => ({
      file,
      precheck: precheck(file),
    }))
    setPicked((prev) => [
      ...prev,
      ...next.filter(
        (n) => !prev.some((p) => p.file.name === n.file.name),
      ),
    ])
  }

  const upload = useMutation({
    mutationFn: () => api.createBatch(ready.map((p) => p.file)),
    onSuccess: (res) => {
      setResults(res.files)
      qc.invalidateQueries({ queryKey: ['batches'] })
      const accepted = res.files.filter((f) => f.status === 'ACCEPTED').length
      if (accepted > 0) {
        toast.success(
          `${accepted} statement${accepted > 1 ? 's' : ''} queued for processing`,
        )
        navigate(`/history?batch=${res.batch_id}`)
      } else {
        toast.error('No files could be accepted')
      }
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Upload failed'),
  })

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-lg font-semibold">Import statements</h1>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          add(e.dataTransfer.files)
        }}
        className={`flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed p-10 text-sm transition-colors ${
          dragging
            ? 'border-sky-500 bg-sky-50 dark:bg-sky-950'
            : 'border-slate-300 dark:border-slate-700'
        }`}
      >
        <UploadCloud className="h-7 w-7 text-slate-400" aria-hidden />
        Drop PDF statements here, or browse
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => add(e.target.files)}
        />
      </button>

      {picked.length > 0 && (
        <Card className="divide-y divide-slate-100 p-0 dark:divide-slate-800">
          {picked.map(({ file, precheck: pc }) => {
            const result = results?.find((r) => r.filename === file.name)
            return (
              <div
                key={file.name}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                <span className="flex-1 truncate">{file.name}</span>
                <span className="tabular text-xs text-slate-500">
                  {formatBytes(file.size)}
                </span>
                {result ? (
                  <StatusBadge meta={intakeStatusMeta(result.status)} />
                ) : pc.ok ? (
                  <span className="text-xs text-emerald-600">ready</span>
                ) : (
                  <span className="text-xs text-rose-600">{pc.reason}</span>
                )}
                {result?.failure_reason && (
                  <span className="text-xs text-slate-500">
                    {result.failure_reason}
                  </span>
                )}
                {!results && (
                  <button
                    aria-label={`remove ${file.name}`}
                    onClick={() =>
                      setPicked((prev) =>
                        prev.filter((p) => p.file.name !== file.name),
                      )
                    }
                    className="text-slate-400 hover:text-slate-600"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            )
          })}
        </Card>
      )}

      {picked.length > 0 && !results && (
        <div className="flex items-center justify-between text-sm text-slate-500">
          <span>
            {picked.length} selected, {ready.length} ready
          </span>
          <Button
            disabled={ready.length === 0 || upload.isPending}
            onClick={() => upload.mutate()}
          >
            {upload.isPending
              ? 'Starting…'
              : `Start analysis (${ready.length})`}
          </Button>
        </div>
      )}
    </div>
  )
}
