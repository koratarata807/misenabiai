"use client";

import liff from "@line/liff";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

type Status =
  | { phase: "init"; message: string }
  | { phase: "working"; message: string }
  | { phase: "done"; message: string }
  | { phase: "error"; message: string };

export default function LiffRegisterPage() {
  const params = useSearchParams();
  const shopId = useMemo(() => params.get("shop") ?? "", [params]);

  const [status, setStatus] = useState<Status>({
    phase: "init",
    message: "初期化中…",
  });

  useEffect(() => {
    const run = async () => {
      try {
        setStatus({ phase: "working", message: "LIFF を初期化しています…" });

        const liffId = process.env.NEXT_PUBLIC_LIFF_ID;
        if (!liffId) {
          throw new Error("NEXT_PUBLIC_LIFF_ID が未設定です（Vercel env を確認）");
        }

        if (!shopId) {
          throw new Error("URL パラメータ shop がありません（例: ?shop=shopA）");
        }

        await liff.init({ liffId });

        // ログインしていない場合はLINEログインへ
        if (!liff.isLoggedIn()) {
          setStatus({ phase: "working", message: "ログイン中…" });
          liff.login(); // リダイレクトされるのでここで return
          return;
        }

        setStatus({ phase: "working", message: "プロフィール取得中…" });
        const profile = await liff.getProfile();

        setStatus({ phase: "working", message: "登録しています…" });
        const res = await fetch("/api/line/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            shop_id: shopId,
            user_id: profile.userId,
            display_name: profile.displayName,
          }),
        });

        const text = await res.text();
        if (!res.ok) {
          throw new Error(`登録APIが失敗しました: status=${res.status} body=${text}`);
        }

        setStatus({ phase: "done", message: "登録が完了しました。画面を閉じます…" });

        // 少しだけ見せてから閉じる（体験が良い）
        setTimeout(() => {
          try {
            liff.closeWindow();
          } catch {
            // closeWindow が効かない環境用フォールバック
            window.location.href = "/"; 
          }
        }, 800);
      } catch (e: any) {
        setStatus({
          phase: "error",
          message: e?.message ?? "不明なエラーが発生しました",
        });
      }
    };

    run();
  }, [shopId]);

  return (
    <main style={{ padding: 24, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto" }}>
      <h1 style={{ fontSize: 18, marginBottom: 8 }}>LINE 登録</h1>
      <p style={{ marginBottom: 12 }}>店舗: <b>{shopId || "(未指定)"}</b></p>

      <div
        style={{
          border: "1px solid #ddd",
          borderRadius: 12,
          padding: 16,
          maxWidth: 520,
        }}
      >
        <p style={{ margin: 0 }}>{status.message}</p>

        {status.phase === "error" && (
          <div style={{ marginTop: 12 }}>
            <p style={{ margin: 0 }}>
              URL例：<code>?shop=shopA</code> を付けて開いてください。
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
