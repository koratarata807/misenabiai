// app/dashboard/[shopId]/page.tsx
import { headers } from "next/headers";
import DailyOpenChart from "./DailyOpenChart";

// ===== 型定義 =====
type DashboardSummary = {
  today_open_users: number;
  yesterday_open_users: number;
};

type DashboardDaily = {
  date: string;
  opened_users: number;
};

type DashboardResponse = {
  shop_id: string;
  summary: DashboardSummary;
  daily?: DashboardDaily[];
};

// セグメント系
type SegmentType = "HOT" | "WARM" | "COLD";

type SegmentUser = {
  shop_id: string;
  user_id: string;
  segment: SegmentType;
  open_count: number;
  days_since_last_open: number;
  last_opened_at: string | null;
};

type SegmentApiResponse = {
  shop_id: string;
  segment: SegmentType;
  users: SegmentUser[];
};

// キャンペーン分析系
type CampaignStat = {
  coupon_type: string;

  // 送信 / 開封まわり
  sent_users?: number | null;
  opened_users?: number | null;
  open_rate?: number | null;

  // 追加：来店まわり
  visits?: number | null;
  visit_rate?: number | null;

  // オプション（将来拡張も含めて全部オプショナルにしておく）
  avg_minutes_to_first_open?: number | null;
  avg_opens_per_open_user?: number | null;
};

type CampaignStatsResponse = {
  shop_id: string;
  campaigns: CampaignStat[];
};

// ===== 共通：ベースURL取得（Next.js 16 用） =====
async function getBaseUrl() {
  const h = await headers();

  const origin = h.get("origin");
  if (origin) return origin;

  const host = h.get("host") ?? "localhost:3000";
  return `http://${host}`;
}

// ===== API 呼び出し =====
async function getDashboardData(shopId: string): Promise<DashboardResponse> {
  const baseUrl = await getBaseUrl();

  const res = await fetch(`${baseUrl}/api/dashboard?shop_id=${shopId}`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error("Failed to fetch dashboard data");
  }

  return res.json();
}

async function getSegmentUsers(
  shopId: string,
  segment: SegmentType
): Promise<SegmentUser[]> {
  const baseUrl = await getBaseUrl();

  const res = await fetch(
    `${baseUrl}/api/user-segments?shop_id=${shopId}&segment=${segment}`,
    { cache: "no-store" }
  );

  if (!res.ok) {
    console.error("failed to fetch segment users:", segment);
    return [];
  }

  const json: SegmentApiResponse = await res.json();
  return json.users ?? [];
}

async function getCampaignStats(
  shopId: string
): Promise<CampaignStatsResponse | null> {
  const baseUrl = await getBaseUrl();

  const res = await fetch(`${baseUrl}/api/campaign-stats?shop_id=${shopId}`, {
    cache: "no-store",
  });

  if (!res.ok) {
    console.error("failed to fetch campaign stats");
    return null;
  }

  return res.json();
}

// ===== 表示用フォーマッタ =====
function formatRate(v: number | null | undefined) {
  if (v == null) return "-";
  return `${v.toFixed(1)}%`;
}

function formatNumber(v: number | null | undefined) {
  if (v == null) return "-";
  return v.toString();
}

function formatMinutes(v: number | null | undefined) {
  if (v == null) return "-";
  return `${v.toFixed(1)} 分`;
}

// ===== ページ本体 =====
// 注意：Next.js 16 では params は Promise
export default async function DashboardPage(props: {
  params: Promise<{ shopId: string }>;
}) {
  const { shopId } = await props.params;

  const [dashboard, hotUsers, warmUsers, coldUsers, campaignStats] =
    await Promise.all([
      getDashboardData(shopId),
      getSegmentUsers(shopId, "HOT"),
      getSegmentUsers(shopId, "WARM"),
      getSegmentUsers(shopId, "COLD"),
      getCampaignStats(shopId),
    ]);

  const titleShop = dashboard.shop_id ?? shopId;
  const daily = dashboard.daily ?? [];
  const campaigns = campaignStats?.campaigns ?? [];

  return (
    <main className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">
        クーポンダッシュボード（{titleShop}）
      </h1>

      {/* 1. サマリーカード */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500">今日の開封ユーザー数</div>
          <div className="text-3xl font-semibold">
            {dashboard.summary.today_open_users}
          </div>
        </div>

        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500">昨日の開封ユーザー数</div>
          <div className="text-3xl font-semibold">
            {dashboard.summary.yesterday_open_users}
          </div>
        </div>
      </section>

      {/* 2. HOT / WARM / COLD ユーザー一覧 */}
      <section className="space-y-4">
        {/* HOT */}
        <div className="border rounded-lg p-4">
          <h2 className="text-lg font-semibold mb-2">HOTユーザー一覧</h2>
          {hotUsers.length === 0 ? (
            <div className="text-sm text-gray-500">該当ユーザーはいません。</div>
          ) : (
            <ul className="space-y-1 text-sm">
              {hotUsers.map((u) => (
                <li
                  key={u.user_id}
                  className="flex items-center justify-between border-b py-1 last:border-b-0"
                >
                  <div>
                    <div className="font-mono text-xs">{u.user_id}</div>
                    <div className="text-[11px] text-gray-500">
                      最終開封から {u.days_since_last_open} 日
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold">{u.open_count} 回開封</div>
                    {u.last_opened_at && (
                      <div className="text-[11px] text-gray-500">
                        最終：
                        {new Date(u.last_opened_at).toLocaleString("ja-JP")}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* WARM */}
        <div className="border rounded-lg p-4">
          <h2 className="text-lg font-semibold mb-2">WARMユーザー一覧</h2>
          {warmUsers.length === 0 ? (
            <div className="text-sm text-gray-500">該当ユーザーはいません。</div>
          ) : (
            <ul className="space-y-1 text-sm">
              {warmUsers.map((u) => (
                <li
                  key={u.user_id}
                  className="flex items-center justify-between border-b py-1 last:border-b-0"
                >
                  <div>
                    <div className="font-mono text-xs">{u.user_id}</div>
                    <div className="text-[11px] text-gray-500">
                      最終開封から {u.days_since_last_open} 日
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold">{u.open_count} 回開封</div>
                    {u.last_opened_at && (
                      <div className="text-[11px] text-gray-500">
                        最終：
                        {new Date(u.last_opened_at).toLocaleString("ja-JP")}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* COLD */}
        <div className="border rounded-lg p-4">
          <h2 className="text-lg font-semibold mb-2">COLDユーザー一覧</h2>
          {coldUsers.length === 0 ? (
            <div className="text-sm text-gray-500">該当ユーザーはいません。</div>
          ) : (
            <ul className="space-y-1 text-sm">
              {coldUsers.map((u) => (
                <li
                  key={u.user_id}
                  className="flex items-center justify-between border-b py-1 last:border-b-0"
                >
                  <div>
                    <div className="font-mono text-xs">{u.user_id}</div>
                    <div className="text-[11px] text-gray-500">
                      最終開封から {u.days_since_last_open} 日
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold">{u.open_count} 回開封</div>
                    {u.last_opened_at && (
                      <div className="text-[11px] text-gray-500">
                        最終：
                        {new Date(u.last_opened_at).toLocaleString("ja-JP")}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* 3. クーポンタイプ別パフォーマンス（キャンペーン分析 + CV） */}
      <section className="border rounded-lg p-4">
        <h2 className="text-lg font-semibold mb-4">
          クーポンタイプ別パフォーマンス
        </h2>

        {campaigns.length === 0 ? (
          <div className="text-sm text-gray-500">データがありません。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b text-xs text-gray-500">
                  <th className="text-left py-1 px-2">クーポン種別</th>
                  <th className="text-right py-1 px-2">送信人数</th>
                  <th className="text-right py-1 px-2">開封人数</th>
                  <th className="text-right py-1 px-2">開封率</th>
                  <th className="text-right py-1 px-2">来店件数</th>
                  <th className="text-right py-1 px-2">来店率</th>
                  <th className="text-right py-1 px-2">初回開封まで平均</th>
                  <th className="text-right py-1 px-2">
                    平均リピート開封回数
                  </th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr key={c.coupon_type} className="border-b last:border-b-0">
                    <td className="py-1 px-2 font-mono">{c.coupon_type}</td>
                    <td className="py-1 px-2 text-right">
                      {formatNumber(c.sent_users)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatNumber(c.opened_users)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatRate(c.open_rate)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatNumber(c.visits)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatRate(c.visit_rate)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatMinutes(c.avg_minutes_to_first_open)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      {formatNumber(c.avg_opens_per_open_user)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 4. 過去7日分の推移（折れ線グラフ＋一覧） */}
      <section className="border rounded-lg p-4">
        <h2 className="text-lg font-semibold mb-4">
          過去7日間の開封ユーザー数
        </h2>

        {daily.length === 0 ? (
          <div className="text-sm text-gray-500">データがありません。</div>
        ) : (
          <div className="space-y-4">
            {/* 折れ線グラフ */}
            <DailyOpenChart data={daily} />

            {/* 数値の一覧 */}
            <div className="space-y-2">
              {daily.map((row) => (
                <div
                  key={row.date}
                  className="flex items-center justify-between text-sm md:text-base"
                >
                  <span>{row.date}</span>
                  <span className="font-semibold">{row.opened_users}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
