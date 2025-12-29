export type KPI = {
  sentUsers: number
  openRate: number
  ctr: number
  openRateDelta: number
  ctrDelta: number
}

export type Decision = {
  severity: "ok" | "info" | "warning"
  topics: string[]
  flags: Record<string, boolean>
}
