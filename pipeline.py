# -*- coding: utf-8 -*-
"""
pipeline.py — 端到端主流程(下載 → 分析 → Excel)

這是整合後的單一入口。原本要分兩步:
    cd batch && python3 batch_download.py --stocks 00700 ...
    cd ..    && python3 run.py --pdf downloads/xxx.pdf
現在一個指令做完。

用法
----
# 下載並分析(最常用)
python3 pipeline.py --stocks 00700,00731 --from 20250101 --to 20251231

# 只分析本機已有的 PDF,不下載
python3 pipeline.py --pdf downloads/00700_TENCENT-R_20250408.pdf

# 分析整個資料夾裡的所有 PDF(旺季批次處理最常用)
python3 pipeline.py --pdf downloads

# 連子資料夾一起掃
python3 pipeline.py --pdf downloads --recursive

# 萬用字元(Windows 的 cmd 不會自己展開 *,由程式處理)
python3 pipeline.py --pdf "downloads/007*.pdf"

# 下載時顯示瀏覽器視窗(除錯用)
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --show-browser

# 加上 AI 語意層
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --ai
"""

# 必須最先 import —— 修正 Windows 輸出重新導向時的 cp950 編碼錯誤
import console  # noqa: F401

import os
import sys
import glob
import argparse
import logging

# ── 自動尋找模組位置 ────────────────────────────────────
# 不假設檔案一定放在某個叫 'batch' 的資料夾裡。
# 直接掃描本層與所有子資料夾,找到 hkexnews_selenium.py 就把它的
# 所在目錄加進 sys.path。這樣不論你把資料夾叫 batch、tools 還是
# 直接把檔案搬到外層,都能正常運作。
HERE = os.path.dirname(os.path.abspath(__file__))


def _add_module_paths():
    """
    找出 hkexnews_selenium.py 的位置並加進 sys.path。

    ⚠ 優先權很重要:如果外層和子資料夾各有一份(例如整理資料夾時
    忘了刪掉舊的),必須讓**外層優先**。否則你更新了外層的檔案,
    程式卻還在載入子資料夾裡的舊版,症狀是「明明改了卻沒生效」,
    而且完全沒有錯誤訊息 —— 非常難察覺。

    sys.path.insert(0, ...) 是後插入的優先,所以要反過來插。
    """
    root_hits = glob.glob(os.path.join(HERE, "hkexnews_selenium.py"))
    sub_hits = glob.glob(os.path.join(HERE, "*", "hkexnews_selenium.py"))
    found = root_hits + sub_hits

    # 反向插入:最後插入的優先權最高,所以外層要最後插
    for f in reversed(found):
        d = os.path.dirname(os.path.abspath(f))
        if d in sys.path:
            sys.path.remove(d)
        sys.path.insert(0, d)
    if HERE not in sys.path:
        sys.path.append(HERE)

    return found


_MODULE_LOCATIONS = _add_module_paths()

logger = logging.getLogger("pipeline")
logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")


def analyse(pdf_paths, out_dir, use_ai):
    """呼叫既有的分析引擎處理每一份 PDF。"""
    from run import process_one

    results, failures = [], []
    for i, p in enumerate(pdf_paths, 1):
        if not os.path.exists(p):
            logger.warning(f"[{i}/{len(pdf_paths)}] 找不到檔案,略過: {p}")
            failures.append((os.path.basename(p), "檔案不存在"))
            continue
        logger.info(f"[{i}/{len(pdf_paths)}] 分析 {os.path.basename(p)}")
        try:
            results.append(process_one(p, out_dir, use_ai))
        except Exception as e:
            import traceback
            logger.error(f"  分析失敗: {e}")
            traceback.print_exc()
            failures.append((os.path.basename(p), str(e)[:80]))
    return results, failures


def main():
    ap = argparse.ArgumentParser(
        description="HKEX 年報下載 + 估值資料萃取(端到端)")
    ap.add_argument("--stocks", help="股票代號清單,逗號分隔,例如 00700,00731")
    ap.add_argument("--all-market", action="store_true",
                    help="不限公司,查整個市場(區間會自動切成 30 天一段;"
                         "資料量大且對網站負擔重,不建議面試現場示範)")
    ap.add_argument("--from", dest="from_date", help="起始日 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", help="結束日 YYYYMMDD")
    ap.add_argument("--pdf", action="append",
                    help="本機 PDF 路徑、資料夾、或萬用字元樣式(可重複)。"
                         "指定資料夾會處理裡面所有 PDF;有指定就不會下載")
    ap.add_argument("--recursive", action="store_true",
                    help="指定資料夾時,連子資料夾一起掃描")
    ap.add_argument("--ai", action="store_true", help="啟用 AI 語意層")
    ap.add_argument("--show-browser", action="store_true",
                    help="下載時顯示瀏覽器視窗")
    ap.add_argument("--downloads", default="downloads", help="PDF 存放資料夾")
    ap.add_argument("--out", default="output", help="Excel 輸出資料夾")
    ap.add_argument("--delay", type=float, default=2.0, help="查詢間隔秒數")
    args = ap.parse_args()

    from run import expand_pdf_inputs
    pdfs = expand_pdf_inputs(args.pdf, recursive=args.recursive)

    # ── 階段一:下載 ────────────────────────────────────
    if args.stocks and args.all_market:
        ap.error("--stocks 與 --all-market 不能同時使用")

    if args.stocks or args.all_market:
        if not (args.from_date and args.to_date):
            ap.error("下載時必須同時指定 --from 與 --to")

        try:
            from hkexnews_selenium import BatchDownloader
        except ImportError:
            logger.error("=" * 60)
            logger.error("找不到 hkexnews_selenium.py")
            logger.error("=" * 60)
            logger.error(f"已搜尋位置: {HERE} 及其所有子資料夾")
            if _MODULE_LOCATIONS:
                logger.error(f"有找到檔案但無法匯入: {_MODULE_LOCATIONS}")
                logger.error("→ 可能是該檔案本身有語法錯誤,或缺少 selenium 套件")
                logger.error("→ 試試: python3 -m pip install selenium")
            else:
                logger.error("→ 完全找不到這個檔案。請確認它在以下任一位置:")
                logger.error(f"   {os.path.join(HERE, 'hkexnews_selenium.py')}")
                logger.error(f"   {os.path.join(HERE, '<任何子資料夾>', 'hkexnews_selenium.py')}")
            sys.exit(1)

        codes = ([c.strip() for c in args.stocks.split(",") if c.strip()]
                 if args.stocks else [])
        logger.info("=" * 60)
        if codes:
            logger.info(f"階段一:下載 — {len(codes)} 間公司 {codes}")
        else:
            logger.info(f"階段一:下載 — 全市場 {args.from_date} ~ {args.to_date}")
            logger.warning("全市場模式資料量大,且會對 HKEXnews 送出大量查詢。")
            logger.warning("查詢區間會自動切成 30 天一段(不指定股票時的網站上限)。")
        logger.info("=" * 60)

        # 明確印出實際載入的檔案 —— 這樣「改了沒生效」一眼就能看出來
        import hkexnews_selenium as _hs
        logger.info(f"使用模組: {os.path.abspath(_hs.__file__)}")
        if len(_MODULE_LOCATIONS) > 1:
            logger.warning(f"⚠ 偵測到 {len(_MODULE_LOCATIONS)} 份 "
                           f"hkexnews_selenium.py,建議刪掉多餘的以免混淆:")
            for f in _MODULE_LOCATIONS:
                mark = "← 使用中" if os.path.abspath(f) == os.path.abspath(_hs.__file__) else ""
                logger.warning(f"    {os.path.abspath(f)} {mark}")

        dl = BatchDownloader(out_dir=args.downloads,
                             headless=not args.show_browser,
                             polite_delay=args.delay)
        if codes:
            filings = dl.run_for_companies(codes, args.from_date, args.to_date)
        else:
            filings = dl.run_for_whole_market(args.from_date, args.to_date)
        logger.info(f"查得 {len(filings)} 筆")
        pdfs += dl.download(filings)

    if not pdfs:
        ap.error("沒有可分析的 PDF。請用 --stocks / --all-market 下載,"
                 "或用 --pdf 指定本機檔案或資料夾")

    # ── 階段二:分析 ────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"階段二:分析 — {len(pdfs)} 份文件")
    logger.info("=" * 60)

    outputs, failures = analyse(pdfs, args.out, args.ai)

    # ── 總結 ───────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"完成:{len(outputs)} / {len(pdfs)} 份成功")
    logger.info("=" * 60)
    for o in outputs:
        print(" -", o)

    # 批次處理幾十份時,失敗訊息會被大量正常輸出淹沒,
    # 所以最後單獨再列一次 —— 使用者需要知道哪幾份要重跑。
    if failures:
        logger.warning("")
        logger.warning(f"以下 {len(failures)} 份分析失敗,需要人手處理:")
        for name, reason in failures:
            logger.warning(f"  ✗ {name} — {reason}")


if __name__ == "__main__":
    main()
