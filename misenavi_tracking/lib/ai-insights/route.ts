import { decideInsightV1 } from "@/lib/ai-insights/rules"

const decision = decideInsightV1({
  sentUsers,
  openRate,
  ctr,
  openRateDelta,
  ctrDelta,
})
