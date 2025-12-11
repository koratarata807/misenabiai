// app/dashboard/_components/SegmentUsersCard.tsx
"use client";

import { useEffect, useState } from "react";

type SegmentType = "HOT" | "WARM" | "COLD";

type SegmentRow = {
  shop_id: string;
  user_id: string;
  segment: SegmentType;
  open_count: number;
  days_since_last_open: number;
  last_opened_at: string | null;
};

export function SegmentUsersCard({ shopId }: { shopId: string }) {
  const [segment, setSegment] = useState<SegmentType>("HOT");
  const [users, setUsers] = useState<SegmentRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          `/api/user-segments?shop_id=${encodeURIComponent(
            shopId
          )}&segment=${segment}`,
          { cache: "no-store" }
        );

        const json = await res.json();
        if (!res.ok) {
          throw new Error(json.error ?? "Failed to load");
        }
        setUsers(json.users ?? []);
      } catch (e: any) {
        setError(e.message ?? "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [shopId, segment]);

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">ユーザーセグメント</h2>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={segment}
          onChange={(e) => setSegment(e.target.value as SegmentType)}
        >
          <option value="HOT">HOT（超アクティブ）</option>
          <option value="WARM">WARM（そこそこ反応あり）</option>
          <option value="COLD">COLD（休眠気味）</option>
        </select>
      </div>

      {loading && <p className="text-sm text-gray-500">読み込み中...</p>}
      {error && <p className="text-sm text-red-500">Error: {error}</p>}

      {!loading && !error && users.length === 0 && (
        <p className="text-sm text-gray-500">該当ユーザーはいません。</p>
      )}

      {!loading && !error && users.length > 0 && (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b">
              <th className="text-left py-1">user_id</th>
              <th className="text-right py-1">開封回数</th>
              <th className="text-right py-1">最終開封からの日数</th>
              <th className="text-right py-1">最終開封日時</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id} className="border-b last:border-0">
                <td className="py-1 pr-2">{u.user_id}</td>
                <td className="py-1 text-right">{u.open_count}</td>
                <td className="py-1 text-right">
                  {u.days_since_last_open ?? "-"}
                </td>
                <td className="py-1 text-right">
                  {u.last_opened_at
                    ? new Date(u.last_opened_at).toLocaleString("ja-JP")
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
