
# restaurant_ai_pro (v0.1.0)

飲食店向け **AI×自動化** の実務用プロ雛形。  
追加ライブラリ不要（`pandas, matplotlib` 推奨）で、**週報PDF・SNS投稿CSV・口コミ返信CSV**を即生成します。  
OpenAIキーがあれば `restaurant_ai/llm.py` 経由で要約強化も可能（未設定でも動作）。

## 構成
```
restaurant_ai_pro/
  restaurant_ai/            # ライブラリ（分析・レポート生成）
    __init__.py
    analytics.py
    config.py
    io_utils.py
    llm.py
    reporting.py
  bin/                      # 実行スクリプト
    weekly_report.py
    sns_calendar.py
    review_reply.py
  data/                     # サンプルCSV
    sales.csv
    menu.csv
    reviews.csv
  OUTPUT/                   # 出力先（生成物）
  README.md
```

## インストール
- Python 3.10+
- `pip install pandas matplotlib`

（任意）OpenAIを使う場合：  
`export OPENAI_API_KEY="sk-..."`

## 使い方
### 1) 週報PDF生成
```
python bin/weekly_report.py --csv data/sales.csv --outdir OUTPUT
```
- `OUTPUT/weekly_report.pdf` と `OUTPUT/hourly_sales.png` が出力されます。

### 2) SNS投稿文CSV
```
python bin/sns_calendar.py --csv data/menu.csv --days 7 --outfile OUTPUT/posts.csv
```

### 3) 口コミ返信ドラフトCSV
```
python bin/review_reply.py --csv data/reviews.csv --outfile OUTPUT/reply_drafts.csv
```

## 運用Tips
- 週次自動化：cron 例）`0 8 * * MON /usr/bin/python /path/bin/weekly_report.py --csv ...`
- LINE連携・メール配信は `bin/` スクリプトにWebhook/SMTP処理を追加して拡張可能。

## 権利
- 著作権は開発者に帰属する想定。顧客には利用許諾を付与。
- 本雛形は改変・再販可（自己責任）。
