// app/settings/[shopId]/ShopSettingsForm.tsx
"use client";

import { useState, FormEvent } from "react";

type Props = {
  shopId: string;
  initialValues: {
    name: string;
    coupon_url: string;
    coupon7_image: string;
    coupon30_image: string;
    coupon_after_7days: string;
    coupon_after_30days: string;
  };
};

export default function ShopSettingsForm({ shopId, initialValues }: Props) {
  const [form, setForm] = useState(initialValues);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleChange =
    (field: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
    };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch("/api/shop-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shop_id: shopId, ...form }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? "保存に失敗しました");
      }

      setMessage("保存しました。");
    } catch (err: any) {
      console.error(err);
      setMessage(err.message ?? "エラーが発生しました");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: 16 }}>
      <div>
        <label>
          店舗名
          <input
            type="text"
            value={form.name}
            onChange={handleChange("name")}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <div>
        <label>
          クーポンリンク（lin.ee）
          <input
            type="text"
            value={form.coupon_url}
            onChange={handleChange("coupon_url")}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <div>
        <label>
          7日クーポン画像URL
          <input
            type="text"
            value={form.coupon7_image}
            onChange={handleChange("coupon7_image")}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <div>
        <label>
          30日クーポン画像URL
          <input
            type="text"
            value={form.coupon30_image}
            onChange={handleChange("coupon30_image")}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <div>
        <label>
          7日クーポン文言
          <textarea
            value={form.coupon_after_7days}
            onChange={handleChange("coupon_after_7days")}
            rows={3}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <div>
        <label>
          30日クーポン文言
          <textarea
            value={form.coupon_after_30days}
            onChange={handleChange("coupon_after_30days")}
            rows={3}
            style={{ width: "100%", padding: 8 }}
          />
        </label>
      </div>

      <button type="submit" disabled={saving} style={{ padding: "8px 16px" }}>
        {saving ? "保存中..." : "保存"}
      </button>

      {message && <p>{message}</p>}
    </form>
  );
}
