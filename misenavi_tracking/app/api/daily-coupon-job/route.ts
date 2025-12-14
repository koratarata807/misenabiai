// app/api/daily-coupon-job/route.ts
import { NextResponse } from "next/server";

export async function GET() {
  const ranAt = new Date().toISOString();

  const url = process.env.PY_JOB_URL!;
  const key = process.env.JOB_KEY!;

  if (!url || !key) {
    return NextResponse.json(
      { ok: false, error: "missing PY_JOB_URL or JOB_KEY" },
      { status: 500 }
    );
  }

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "x-job-key": key,
    },
  });

  const text = await res.text();

  return NextResponse.json({
    ok: res.ok,
    ran_at: ranAt,
    status: res.status,
    body: text,
  });
}
