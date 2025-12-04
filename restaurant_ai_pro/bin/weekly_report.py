
#!/usr/bin/env python
import argparse, os, pandas as pd
from restaurant_ai.io_utils import read_csv, ensure_dir
from restaurant_ai.analytics import summarize_sales, simple_insights
from restaurant_ai.reporting import build_pdf, plot_hourly

def main():
    ap = argparse.ArgumentParser(description="週報PDFとPNGを生成")
    ap.add_argument("--csv", required=True, help="sales.csv")
    ap.add_argument("--outdir", default="./OUTPUT")
    args = ap.parse_args()

    ensure_dir(args.outdir)
    df = read_csv(args.csv)
    ws = summarize_sales(df)

    # PDF
    pdf_path = os.path.join(args.outdir, "weekly_report.pdf")
    build_pdf(ws, df, pdf_path)

    # PNG
    png_path = os.path.join(args.outdir, "hourly_sales.png")
    plot_hourly(df, png_path)

    # Insights (stdout)
    print("\n".join(simple_insights(ws)))
    print(f"\n[OK] 週報PDF: {pdf_path}")
    print(f"[OK] 図PNG:   {png_path}")

if __name__ == "__main__":
    main()
