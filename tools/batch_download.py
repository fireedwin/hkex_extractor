# -*- coding: utf-8 -*-
"""
batch_download.py — 批次下載 CLI

用法
----
# 情境A:特定公司清單
python batch_download.py --stocks 00700,09999,00001 --from 20250101 --to 20251231

# 情境B:整個市場(不建議面試現場示範,見 hkexnews_selenium.py 內的警告)
python batch_download.py --whole-market --from 20250301 --to 20250430

# 第一次跑,先用非無頭模式肉眼確認每一步有沒有卡住
python batch_download.py --stocks 00700 --from 20250101 --to 20251231 --show-browser
"""

import argparse
import logging

from hkexnews_selenium import BatchDownloader

logger = logging.getLogger("batch_download")


def main():
    ap = argparse.ArgumentParser(description="HKEXnews 批次下載工具")
    ap.add_argument("--stocks", help="股票代號清單,逗號分隔,例如 00700,09999")
    ap.add_argument("--whole-market", action="store_true", help="不限公司,查整個市場")
    ap.add_argument("--from", dest="from_date", required=True, help="起始日 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", required=True, help="結束日 YYYYMMDD")
    ap.add_argument("--out", default="downloads", help="下載存放資料夾")
    ap.add_argument("--show-browser", action="store_true",
                    help="關閉無頭模式,顯示實際瀏覽器視窗(第一次校正選擇器時用)")
    ap.add_argument("--delay", type=float, default=2.0, help="每次查詢間隔秒數(禮貌性延遲)")
    args = ap.parse_args()

    if not args.stocks and not args.whole_market:
        ap.error("請用 --stocks 指定公司清單,或用 --whole-market 查整個市場")

    downloader = BatchDownloader(out_dir=args.out,
                                 headless=not args.show_browser,
                                 polite_delay=args.delay)

    if args.stocks:
        codes = [c.strip() for c in args.stocks.split(",") if c.strip()]
        logger.info(f"情境A:{len(codes)} 間公司 — {codes}")
        filings = downloader.run_for_companies(codes, args.from_date, args.to_date)
    else:
        logger.info("情境B:整個市場")
        filings = downloader.run_for_whole_market(args.from_date, args.to_date)

    logger.info(f"共查得 {len(filings)} 筆(去重前)")
    paths = downloader.download(filings)
    logger.info(f"完成下載 {len(paths)} 份文件,存放於 {args.out}/")
    for p in paths:
        print(" -", p)


if __name__ == "__main__":
    main()
