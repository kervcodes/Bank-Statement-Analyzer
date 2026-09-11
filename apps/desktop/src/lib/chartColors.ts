/** Chart series colors. Deliberately a different hue family from the status
 *  palette (format.ts's gray/blue/green/amber/red) so a series is never
 *  mistaken for a status signal (dataviz skill: status colors are reserved).
 *  Fixed order, never cycled or reassigned when a filter changes what's on
 *  screen. */
export const CASH_FLOW_COLORS = {
  credits: '#0d9488', // teal-600 -- money in
  debits: '#ea580c', // orange-600 -- money out
  net: '#4338ca', // indigo-700 -- the summary line
  transfers: '#94a3b8', // slate-400 -- recedes: not spending, not income
} as const

// Fixed-order categorical set for the spending-by-category donut/bars.
// Capped at 6: past that, adjacent hues blur and a table reads better
// (dataviz anti-patterns: donut/pie stays <= 6 segments).
export const CATEGORY_COLORS = [
  '#4338ca', // indigo-700
  '#ea580c', // orange-600
  '#0d9488', // teal-600
  '#c026d3', // fuchsia-600
  '#65a30d', // lime-600
  '#0e7490', // cyan-700
] as const

export const OTHER_CATEGORY_COLOR = '#94a3b8' // slate-400
export const MAX_DONUT_SLICES = CATEGORY_COLORS.length
