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

# 下載其他文件類型(預設 annual_report;可用選項見 config.DOC_TYPES)
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --type interim_report
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --type major_transaction

# 加上 AI 語意層
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --ai

# 增量處理(預設開啟):已分析過且邏輯沒變的檔案會自動跳過
python3 pipeline.py --pdf downloads          # 第二次跑幾乎是零成本

# 強制重跑全部(不理會帳本紀錄,但跑完仍會更新帳本)
python3 pipeline.py --pdf downloads --force

# 完全停用增量(不讀也不寫帳本)
python3 pipeline.py --pdf downloads --no-incremental
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


def analyse(pdf_paths, out_dir, use_ai, ledger=None, reporter=None):
    """
    呼叫既有的分析引擎處理每一份 PDF。

    ledger 不是 None 時,每分析成功一份就立刻寫入帳本 —— 不等整批跑完。
    跑到第 150 份才當掉時,前面 149 份的成果要保得住;重跑只補剩下的。

    reporter 不是 None 時,會攔截每一份的分析輸出並比對 config.ERROR_PATTERNS,
    把「交叉驗證未通過」「0 個科目」這類問題記進錯誤紀錄。這些訊息目前
    是 financials.py 等模組直接印出來的,process_one() 沒有結構化回傳,
    所以只能從輸出文字取得(見 error_report.py 檔頭說明)。
    """
    from run import process_one

    results, failures = [], []
    for i, p in enumerate(pdf_paths, 1):
        if not os.path.exists(p):
            logger.warning(f"[{i}/{len(pdf_paths)}] 找不到檔案,略過: {p}")
            failures.append((os.path.basename(p), "檔案不存在"))
            if reporter is not None:
                reporter.add(f"找不到檔案:{p}", stock=None, severity="high")
            continue
        logger.info(f"[{i}/{len(pdf_paths)}] 分析 {os.path.basename(p)}")

        stock = None
        if reporter is not None:
            from error_report import stock_from_name
            stock = stock_from_name(p)

        try:
            if reporter is not None:
                from error_report import OutputCapture
                with OutputCapture() as cap:
                    out = process_one(p, out_dir, use_ai)
                # 分析「成功」不代表結果沒問題 —— 掃描過程輸出,
                # 把畫面上看起來像綠燈、實際有問題的狀況挑出來
                hits = reporter.scan_and_add(cap.text(), filename=out, stock=stock)
                if hits:
                    logger.warning(f"  ⚠ 這份有 {len(hits)} 項需要注意,已記入錯誤紀錄")
            else:
                out = process_one(p, out_dir, use_ai)

            results.append(out)
            if ledger is not None:
                # 只有分析成功才記錄。失敗的不寫進帳本,下次一定會重跑。
                try:
                    ledger.record(p, out, use_ai=use_ai)
                except Exception as e:
                    logger.warning(f"  帳本寫入失敗(不影響分析結果): {e}")
        except Exception as e:
            import traceback
            logger.error(f"  分析失敗: {e}")
            traceback.print_exc()
            failures.append((os.path.basename(p), str(e)[:80]))
            if reporter is not None:
                reporter.add(f"分析失敗({os.path.basename(p)}):{str(e)[:80]}",
                             filename=None, stock=stock, severity="high")
    return results, failures


def _save_report(reporter):
    """
    寫出錯誤紀錄並告訴使用者位置。沒有問題就不建檔,也不印任何東西 ——
    每次都印「0 筆問題」只會讓真的有問題那次被忽略。
    """
    if reporter is None or len(reporter) == 0:
        return
    path = reporter.save()
    logger.warning("")
    logger.warning("=" * 60)
    logger.warning(f"有 {len(reporter)} 項需要注意")
    logger.warning("=" * 60)
    if path:
        logger.warning(f"詳細清單已寫入: {path}")
    else:
        # 寫檔失敗也不能讓問題消失,直接印在畫面上
        logger.warning("(紀錄檔寫入失敗,以下直接列出)")
        for e in reporter.entries:
            logger.warning(f"  {e['file']} | {e['stock']} | {e['what']}")


def main():
    # --type 的選項來自 config.DOC_TYPES(領域知識層),不是寫死在這裡 ——
    # 以後在 config.py 加一種通函類型,--type 的選單會自動跟著多一項。
    try:
        import config as _C
        _doc_type_choices = list(_C.DOC_TYPES.keys())
        _default_doc_type = getattr(_C, "DEFAULT_DOC_TYPE", "annual_report")
    except Exception:
        # config.py 理論上一定跟 pipeline.py 放在一起,這裡只是防呆:
        # 就算真的匯入失敗,也讓 --type annual_report 這個最基本的情境還能跑,
        # 不要因為選單建不出來就讓整支程式無法啟動。
        _doc_type_choices = None
        _default_doc_type = "annual_report"

    ap = argparse.ArgumentParser(
        description="HKEX 年報下載 + 估值資料萃取(端到端)")
    ap.add_argument("--stocks", help="股票代號清單,逗號分隔,例如 00700,00731")
    ap.add_argument("--all-market", action="store_true",
                    help="不限公司,查整個市場(區間會自動切成 30 天一段;"
                         "資料量大且對網站負擔重,不建議面試現場示範)")
    ap.add_argument("--from", dest="from_date", help="起始日 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", help="結束日 YYYYMMDD")
    ap.add_argument("--type", dest="doc_type", default=_default_doc_type,
                    choices=_doc_type_choices,
                    help="要下載的文件類型(見 config.DOC_TYPES),預設年報。"
                         "選單展開已用 check_menu.py 驗證過全部七種,"
                         "但除 annual_report 外的搜尋結果內容還沒實機驗證,"
                         "第一次用建議加 --show-browser 肉眼確認結果")
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
    ap.add_argument("--force", action="store_true",
                    help="忽略帳本紀錄,強制重新分析全部文件(跑完仍會更新帳本)")
    ap.add_argument("--no-incremental", action="store_true",
                    help="完全停用增量處理:不讀也不寫帳本")
    ap.add_argument("--reset-ledger", action="store_true",
                    help="清空帳本後結束(下次執行等同第一次跑)")
    ap.add_argument("--error-dir", default=None,
                    help="錯誤紀錄資料夾(預設見 config.ERROR_DIR)")
    ap.add_argument("--no-error-report", action="store_true",
                    help="不產生錯誤紀錄檔")
    args = ap.parse_args()

    # ── 錯誤紀錄 ───────────────────────────────────────
    # 執行時間在這裡就固定下來,整份紀錄共用同一個時間戳 ——
    # 使用者要對照的是「哪一次執行出的問題」,不是每列各自的秒數。
    reporter = None
    if not args.no_error_report:
        try:
            from error_report import ErrorReport
            reporter = ErrorReport(out_dir=args.error_dir, root=HERE)
        except Exception as e:
            logger.warning(f"錯誤紀錄無法啟用({e}),本次不產生紀錄檔")

    # ── 增量處理帳本 ───────────────────────────────────
    ledger = None
    if not args.no_incremental:
        try:
            from incremental import Ledger
            ledger = Ledger(out_dir=args.out, root=HERE)
        except Exception as e:
            logger.warning(f"增量處理無法啟用({e}),本次全部重新分析")
            ledger = None

    if args.reset_ledger:
        if ledger is None:
            ap.error("--reset-ledger 不能與 --no-incremental 併用")
        n = ledger.clear()
        logger.info(f"帳本已清空,移除 {n} 筆紀錄")
        return

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
            logger.info(f"階段一:下載 — {len(codes)} 間公司 {codes}"
                        f"(類型: {args.doc_type})")
        else:
            logger.info(f"階段一:下載 — 全市場 {args.from_date} ~ {args.to_date}"
                        f"(類型: {args.doc_type})")
            logger.warning("全市場模式資料量大,且會對 HKEXnews 送出大量查詢。")
            logger.warning("查詢區間會自動切成 30 天一段(不指定股票時的網站上限)。")
        if args.doc_type != "annual_report":
            logger.info(f"⚠ 「{args.doc_type}」選單展開已驗證過,"
                        f"但搜尋結果內容還沒實機驗證,"
                        f"如果是第一次用,建議先加 --show-browser 肉眼確認結果正確")
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
                             polite_delay=args.delay,
                             reporter=reporter)
        if codes:
            filings = dl.run_for_companies(codes, args.from_date, args.to_date,
                                           doc_type=args.doc_type)
        else:
            filings = dl.run_for_whole_market(args.from_date, args.to_date,
                                              doc_type=args.doc_type)
        logger.info(f"查得 {len(filings)} 筆")
        pdfs += dl.download(filings)

    if not pdfs:
        # 查無結果也要留紀錄:這正是使用者事後想知道「那天到底查了什麼、
        # 為什麼沒東西」的情境。先寫檔再結束。
        _save_report(reporter)
        ap.error("沒有可分析的 PDF。請用 --stocks / --all-market 下載,"
                 "或用 --pdf 指定本機檔案或資料夾")

    # ── 階段二:分析 ────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"階段二:分析 — {len(pdfs)} 份文件")
    logger.info("=" * 60)

    # 增量篩選:已分析過、分析邏輯沒變、輸出檔還在的直接跳過
    skipped = []
    if ledger is not None:
        logger.info(f"分析邏輯版本 {ledger.logic_version}"
                    f"(納入 {len(ledger.logic_files)} 個模組)")
        if args.force:
            logger.info("--force:忽略帳本,全部重新分析")
        else:
            todo, skipped = ledger.split(pdfs, use_ai=args.ai)
            ms = ledger.stats["hash_seconds"] * 1000
            logger.info(f"指紋比對 {len(pdfs)} 份,耗時 {ms:.0f} ms")
            if skipped:
                logger.info(f"跳過 {len(skipped)} 份(已分析過且結果仍有效)")
                for p, reason, _ in skipped:
                    logger.info(f"  ○ {os.path.basename(p)} — {reason}")
            # 邏輯改過而必須重跑時要講清楚原因,否則使用者會以為增量壞了
            relog = [p for p in todo
                     if ledger.reasons.get(p) == "分析邏輯已更新"]
            if relog:
                logger.info(f"分析邏輯已更新,{len(relog)} 份既有結果視為過期,"
                            f"重新分析以免給出舊版擷取結果")
                # 指出到底是哪個檔案變了 —— 不然使用者只會看到「全部重跑」
                # 卻不知道是自己改的 config.py,還是某個不該影響萃取的
                # 模組被誤算進邏輯版本。
                ch = ledger.logic_changes()
                bits = []
                if ch.get("modified"):
                    bits.append(f"已修改: {', '.join(ch['modified'])}")
                if ch.get("added"):
                    bits.append(f"新增: {', '.join(ch['added'])}")
                if ch.get("removed"):
                    bits.append(f"移除: {', '.join(ch['removed'])}")
                if bits:
                    logger.info(f"  變動的模組 — {' / '.join(bits)}")
                else:
                    logger.info("  (帳本沒有舊的模組快照可比對,"
                                "下次執行起就能指出是哪個檔案變動)")
            pdfs = todo

    if not pdfs:
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"全部 {len(skipped)} 份都是最新結果,不需重新分析")
        logger.info("=" * 60)
        for _, _, outs in skipped:
            for o in outs:
                print(" -", o)
        _save_report(reporter)
        return

    outputs, failures = analyse(pdfs, args.out, args.ai, ledger=ledger,
                                reporter=reporter)

    # ── 總結 ───────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    if skipped:
        logger.info(f"完成:本次分析 {len(outputs)} / {len(pdfs)} 份成功,"
                    f"另有 {len(skipped)} 份沿用既有結果")
    else:
        logger.info(f"完成:{len(outputs)} / {len(pdfs)} 份成功")
    logger.info("=" * 60)
    for o in outputs:
        print(" -", o)
    # 使用者要的是「檔案在哪」,所以跳過的那幾份也要把 Excel 路徑印出來,
    # 不能因為這次沒跑就從清單消失。
    for _, _, outs in skipped:
        for o in outs:
            print(" -", o, "(沿用)")

    # 批次處理幾十份時,失敗訊息會被大量正常輸出淹沒,
    # 所以最後單獨再列一次 —— 使用者需要知道哪幾份要重跑。
    if failures:
        logger.warning("")
        logger.warning(f"以下 {len(failures)} 份分析失敗,需要人手處理:")
        for name, reason in failures:
            logger.warning(f"  ✗ {name} — {reason}")

    _save_report(reporter)


if __name__ == "__main__":
    main()
