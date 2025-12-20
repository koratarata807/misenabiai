"use client";

import liff from "@line/liff";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

type CouponPayload = {
  title: string;          // 例: "ドリンク1杯無料"
  expires_text: string;   // 例: "本日限り"
  note?: string;          // 例: "会計前にこの画面を提示してください"
  image_url?: string;     // 画像運用するなら
  coupon_code?: string;   // 文字コード運用するなら（任意）
};

type ApiResponse =
  | { ok: true; status: "granted" | "already_granted"; coupon: CouponPayload }
  | { ok: false; error: string };

type Status =
  | { phase: "loading"; message: string }
  | { phase: "success"; message: string; coupon: CouponPayload; status: "granted" | "already_granted" }
  | { phase: "error"; message: string };

function withTimeout<T>(promise: Promise<T>, ms: number, label = "timeout"): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`${label}: ${ms}ms`)), ms);
    promise
      .then((v) => {
        clearTimeout(t);
        resolve(v);
      })
      .catch((e) => {
        clearTimeout(t);
        reject(e);
      });
  });
}

export default function LiffRegisterClient() {
  const params = useSearchParams();
  const shopId = useMemo(() => params.get("shop") ?? "", [params]);

  const [status, setStatus] = useState<Status>({
    phase: "loading",
    message: "初期化中…",
  });

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        const TIMEOUT_MS = 10_000;

        // ここから先、必ず success か error に落とす（止まりゼロ）
        setStatus({ phase: "loading", message: "LIFF を初期化しています…" });

        const liffId = process.env.NEXT_PUBLIC_LIFF_ID;
        if (!liffId) throw new Error("NEXT_PUBLIC_LIFF_ID が未設定です（Vercel env を確認）");
        if (!shopId) throw new Error("URL パラメータ shop がありません（例: ?shop=shopA）");

        await withTimeout(liff.init({ liffId }), TIMEOUT_MS, "LIFF init timeout");

        // ログインしていない場合はLINEログインへ（戻ってきたら再実行される）
        if (!liff.isLoggedIn()) {
          if (cancelled) return;
          setStatus({ phase: "loading", message: "ログイン画面へ遷移します…" });

          // shop付きURLを維持してログイン
          const redirectUri = window.location.href;
          liff.login({ redirectUri });
          return;
        }

        if (cancelled) return;
        setStatus({ phase: "loading", message: "プロフィール取得中…" });
        const profile = await withTimeout(liff.getProfile(), TIMEOUT_MS, "getProfile timeout");

        if (cancelled) return;
        setStatus({ phase: "loading", message: "登録しています…" });

        const res = await withTimeout(
          fetch("/api/line/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              shop_id: shopId,
              user_id: profile.userId,
              display_name: profile.displayName,
            }),
          }),
          TIMEOUT_MS,
          "register API timeout"
        );

        const data = (await res.json()) as ApiResponse;

        if (!res.ok || !data.ok) {
          const msg =
            (data && "error" in data && data.error) ||
            `登録APIが失敗しました: status=${res.status}`;
          throw new Error(msg);
        }

        if (cancelled) return;

        // ✅ 方式A：登録完了→クーポン表示に100%収束
        setStatus({
          phase: "success",
          message: data.status === "granted" ? "登録が完了しました。" : "登録済みです。",
          coupon: data.coupon,
          status: data.status,
        });
      } catch (e: any) {
        if (cancelled) return;
        setStatus({
          phase: "error",
          message: e?.message ?? "不明なエラーが発生しました",
        });
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [shopId]);

  return (
    <main style={{ padding: 24, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto" }}>
      <h1 style={{ fontSize: 18, marginBottom: 8 }}>LINE 登録</h1>
      <p style={{ marginBottom: 12 }}>
        店舗: <b>{shopId || "(未指定)"}</b>
      </p>

      <div
        style={{
          border: "1px solid #ddd",
          borderRadius: 12,
          padding: 16,
          maxWidth: 520,
        }}
      >
        {status.phase === "loading" && (
          <>
            <p style={{ margin: 0 }}>{status.message}</p>
            <p style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
              ※ 10秒以上かかる場合は回線状況をご確認ください
            </p>
          </>
        )}

        {status.phase === "error" && (
          <>
            <p style={{ margin: 0, color: "#b00020" }}>{status.message}</p>
            <div style={{ marginTop: 12 }}>
              <p style={{ margin: 0 }}>
                URL例：<code>?shop=shopA</code> を付けて開いてください。
              </p>
              <button
                onClick={() => window.location.reload()}
                style={{
                  marginTop: 12,
                  padding: "10px 14px",
                  borderRadius: 10,
                  border: "1px solid #ddd",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                再試行
              </button>
            </div>
          </>
        )}

        {status.phase === "success" && (
          <>
            <p style={{ margin: 0, fontWeight: 700 }}>{status.message}</p>
            <p style={{ marginTop: 8, color: "#666" }}>
              {status.status === "granted" ? "初回クーポンを発行しました。" : "初回クーポンは発行済みです。"}
            </p>

                <p style={{ marginTop: 10, fontSize: 14, fontWeight: 700 }}>
                    スタッフの方へ：この画面をそのままご提示ください
                </p>
                <p style={{ marginTop: 4, fontSize: 12, color: "#666" }}>
                    ※スクリーンショット提示でも問題ありません
                    </p>



            <div
              style={{
                marginTop: 12,
                border: "1px solid #ddd",
                borderRadius: 12,
                padding: 14,
              }}
            >
              <p style={{ margin: 0, fontSize: 18, fontWeight: 800 }}>
                {status.coupon.title}
              </p>
              <p style={{ marginTop: 6, marginBottom: 0, color: "#444" }}>
                期限：<b>{status.coupon.expires_text}</b>
              </p>

              {status.coupon.image_url && (
                <img
                  src={status.coupon.image_url}
                  alt="coupon"
                  style={{ width: "100%", marginTop: 12, borderRadius: 12 }}
                />
              )}

              {status.coupon.coupon_code && (
                <p style={{ marginTop: 12, marginBottom: 0 }}>
                  クーポンコード：<b>{status.coupon.coupon_code}</b>
                </p>
              )}

              <p style={{ marginTop: 12, marginBottom: 0, fontSize: 13, color: "#666" }}>
                {status.coupon.note ?? "会計前にこの画面をスタッフへ提示してください。"}
              </p>
            </div>

            <p style={{ marginTop: 12, marginBottom: 0, fontSize: 12, color: "#666" }}>
              ※ この画面をそのまま提示してください（スクショでも可）
            </p>
          </>
        )}
      </div>
    </main>
  );
}
