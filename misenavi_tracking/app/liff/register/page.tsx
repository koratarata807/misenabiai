import { Suspense } from "react";
import LiffRegisterClient from "./LiffRegisterClient";

export default function LiffRegisterPage() {
  return (
    <Suspense
      fallback={
        <main style={{ padding: 24, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto" }}>
          <h1 style={{ fontSize: 18, marginBottom: 8 }}>LINE 登録</h1>
          <p style={{ margin: 0 }}>読み込み中…</p>
        </main>
      }
    >
      <LiffRegisterClient />
    </Suspense>
  );
}
