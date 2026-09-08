/** Routes whose screens land in PR 2 / PR 3. Keeps the sidebar nav honest
 *  instead of 404-ing. */
export function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div className="mx-auto max-w-md pt-24 text-center">
      <h1 className="text-lg font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-slate-500">{note}</p>
    </div>
  )
}
