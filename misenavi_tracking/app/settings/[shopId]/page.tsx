// app/settings/[shopId]/page.tsx
import { supabaseServer } from "@/lib/supabaseServer";
import ShopSettingsForm from "./ShopSettingsForm";

type Props = {
  // Next.js 16 では params は Promise
  params: Promise<{ shopId: string }>;
};

export default async function ShopSettingsPage(props: Props) {
  const { shopId } = await props.params;

  const { data: shop, error } = await supabaseServer
    .from("shops")
    .select(
      `
      id,
      name,
      coupon_url,
      coupon7_image,
      coupon30_image,
      coupon_after_7days,
      coupon_after_30days
      `
    )
    .eq("id", shopId)
    .single();

  if (error || !shop) {
    console.error(error);
    return (
      <main style={{ padding: 24 }}>
        <h1>店舗設定ページ</h1>
        <p>店舗情報が取得できませんでした。</p>
      </main>
    );
  }

  return (
    <main style={{ padding: 24, maxWidth: 720, margin: "0 auto" }}>
      <h1>店舗設定ページ</h1>
      <p style={{ marginBottom: 24 }}>shopId: {shopId}</p>

      {/* ★ クライアント側フォームに値を渡す */}
      <ShopSettingsForm
        shopId={shop.id}
        initialValues={{
          name: shop.name ?? "",
          coupon_url: shop.coupon_url ?? "",
          coupon7_image: shop.coupon7_image ?? "",
          coupon30_image: shop.coupon30_image ?? "",
          coupon_after_7days: shop.coupon_after_7days ?? "",
          coupon_after_30days: shop.coupon_after_30days ?? "",
        }}
      />
    </main>
  );
}
