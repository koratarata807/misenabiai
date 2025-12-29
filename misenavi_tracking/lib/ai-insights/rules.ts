import { KPI, Decision } from "./types"

export function decideInsightV1(kpi: KPI): Decision {
  const topics: string[] = []
  const flags: Record<string, boolean> = {}
  let severity: Decision["severity"] = "ok"

  if (kpi.sentUsers < 30) {
    severity = "info"
    topics.push("送信人数が少ないため、傾向判断は参考値です")
    flags.smallSample = true
  }

  if (kpi.openRate < 0.25) {
    severity = "warning"
    topics.push("開封率が低く、文言や画像の訴求が弱い可能性があります")
    flags.lowOpenRate = true
  }

  if (kpi.openRateDelta < -0.03) {
    severity = "warning"
    topics.push("開封率が前週比で悪化しています")
    flags.openRateDown = true
  }

  if (kpi.ctr < 0.05) {
    if (severity === "ok") severity = "info"
    topics.push("クリック率が低く、導線改善の余地があります")
    flags.lowCTR = true
  }

  if (topics.length === 0) {
    topics.push("配信パフォーマンスは概ね良好です")
  }

  return { severity, topics, flags }
}
