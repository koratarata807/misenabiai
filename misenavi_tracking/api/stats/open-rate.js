// /api/stats/open-rate.js

module.exports = async (req, res) => {
  try {
    // GET 以外は拒否
    if (req.method !== "GET") {
      res.setHeader("Allow", "GET");
      return res.status(405).json({ error: "Method Not Allowed" });
    }

    const { shop_id, type } = req.query;

    if (!shop_id || !type) {
      return res
        .status(400)
        .json({ error: "shop_id and type are required" });
    }

    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey =
      process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_KEY;

    // 環境変数チェック
    if (!supabaseUrl || !supabaseKey) {
      return res.status(500).json({
        error: "Supabase env vars missing",
        has_url: !!supabaseUrl,
        has_key: !!supabaseKey,
      });
    }

    const headers = {
      apikey: supabaseKey,
      Authorization: `Bearer ${supabaseKey}`,
      "Content-Type": "application/json",
    };

    // ========== 分母：送付人数 ==========
    const sendUrl =
      `${supabaseUrl}/rest/v1/coupon_send_logs` +
      `?shop_id=eq.${encodeURIComponent(shop_id)}` +
      `&coupon_type=eq.${encodeURIComponent(type)}` +
      `&select=user_id`;

    const sendResp = await fetch(sendUrl, { headers });

    if (!sendResp.ok) {
      const text = await sendResp.text();
      return res.status(500).json({
        error: "failed to fetch sent logs",
        status: sendResp.status,
        body: text,
      });
    }

    const sendRows = await sendResp.json();
    const sentUsers = sendRows.length;

    // ========== 分子：開封人数（ユニークユーザー） ==========
    const openUrl =
      `${supabaseUrl}/rest/v1/coupon_events` +
      `?shop_id=eq.${encodeURIComponent(shop_id)}` +
      `&coupon_type=eq.${encodeURIComponent(type)}` +
      `&event_type=eq.opened` +
      `&select=user_id`;

    const openResp = await fetch(openUrl, { headers });

    if (!openResp.ok) {
      const text = await openResp.text();
      return res.status(500).json({
        error: "failed to fetch open logs",
        status: openResp.status,
        body: text,
      });
    }

    const openRows = await openResp.json();
    const openedUsers = new Set(
      (openRows || []).map((row) => row.user_id)
    ).size;

    const openRate =
      sentUsers === 0 ? 0 : openedUsers / sentUsers;

    return res.status(200).json({
      shop_id,
      coupon_type: type,
      sent_users: sentUsers,
      opened_users: openedUsers,
      open_rate: openRate,
    });
  } catch (e) {
    return res.status(500).json({
      error: "unexpected error",
      details: String(e),
    });
  }
};

