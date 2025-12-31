// app/dashboard/[shopId]/AiInsightCard.tsx

type Severity = "ok" | "info" | "warning";

function SeverityBadge({ severity }: { severity: Severity }) {
  const label =
    severity === "warning" ? "要注意" : severity === "info" ? "要改善" : "良好";

  const cls =
    severity === "warning"
      ? "bg-red-100 text-red-800"
      : severity === "info"
      ? "bg-yellow-100 text-yellow-800"
      : "bg-green-100 text-green-800";

  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export default function AiInsightCard({ insight }: { insight: any }) {
  if (!insight) return null;

  return (
    <section className="border rounded-lg p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">AI分析コメント</h2>
        <SeverityBadge severity={insight.severity as Severity} />
      </div>

      <p className="mt-2 text-sm">{insight.summary}</p>

      {Array.isArray(insight.topics) && insight.topics.length > 0 && (
        <div className="mt-3">
          <div className="text-sm font-semibold">ポイント</div>
          <ul className="mt-1 list-disc pl-5 text-sm space-y-1">
            {insight.topics.map((t: string, i: number) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      {insight?.flags?.smallSample && (
        <div className="mt-3 text-xs text-gray-500">
          ※ 母数が少ないため、参考値として解釈してください
        </div>
      )}
    </section>
  );
}
