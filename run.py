# -*- coding: utf-8 -*-
"""
run.py — 主程式

用法範例
--------
# 1) 處理本機一份 PDF(最常用,面試 demo 建議用這個)
python run.py --pdf downloads/00700_annual_report_2024.pdf

# 2) 從 HKEXnews 依日期區間下載某公司年報再處理
python run.py --from 20250101 --to 20250630 --stock 00700 --type annual_report

# 3) 加上 AI 語意層(需先 export ANTHROPIC_API_KEY=...)
python run.py --pdf report.pdf --ai
"""

# 必須最先 import —— 修正 Windows 輸出重新導向時的 cp950 編碼錯誤
import console  # noqa: F401

import os
import sys
import glob
import argparse

from pdf_reader import read_pdf, page_summary
from scanner import scan_topics, scan_valuation_params, relevant_page_indices
from financials import extract_financials
from excel_out import build_workbook
import ai_layer


def expand_pdf_inputs(paths, recursive: bool = False, verbose: bool = True):
    """
    把使用者給的 --pdf 參數展開成實際的 PDF 檔案清單。

    支援三種寫法:
      1. 單一檔案   --pdf downloads/00700.pdf
      2. 資料夾     --pdf downloads          ← 掃描該資料夾所有 PDF
      3. 萬用字元   --pdf "downloads/007*.pdf"

    第 3 種在 Windows 特別有用:cmd 不會自己展開 *,
    要由程式處理,否則會變成「找不到檔案 downloads/007*.pdf」。

    結果會去重並排序,讓每次執行的處理順序固定。
    """
    out, seen = [], set()

    def add(p):
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isfile(ap) and ap.lower().endswith(".pdf"):
            seen.add(ap)
            out.append(p)

    for raw in paths or []:
        if os.path.isdir(raw):
            pattern = "**/*.pdf" if recursive else "*.pdf"
            found = sorted(glob.glob(os.path.join(raw, pattern), recursive=recursive))
            if verbose:
                scope = "(含子資料夾)" if recursive else ""
                print(f"[input] 資料夾 {raw}{scope} 找到 {len(found)} 份 PDF")
            for f in found:
                add(f)
        elif any(ch in raw for ch in "*?["):
            found = sorted(glob.glob(raw, recursive=recursive))
            if verbose:
                print(f"[input] 樣式 {raw} 符合 {len(found)} 份檔案")
            for f in found:
                add(f)
        else:
            if not os.path.exists(raw) and verbose:
                print(f"[input] 找不到: {raw}")
            add(raw)

    return out


def process_one(pdf_path: str, out_dir: str, use_ai: bool,
                engine: str = None) -> str:
    print("=" * 68)
    print(f"處理: {pdf_path}")
    print("=" * 68)

    # --- 功能A:逐頁萃取 ---------------------------------------------
    # extract_tables 預設關閉:分析邏輯並未使用表格資料,關掉可省時間
    pages = read_pdf(pdf_path, extract_tables=False, engine=engine)
    stats = page_summary(pages)

    # --- 功能B:規則層定位 -------------------------------------------
    topic_hits = scan_topics(pages)
    param_hits = scan_valuation_params(pages)
    print(f"[scanner] 主題段落 {len(topic_hits)} 筆;估值參數 {len(param_hits)} 筆")

    focus = relevant_page_indices(topic_hits, priority_only=True)
    if focus:
        ratio = len(focus) / max(len(pages), 1)
        print(f"[scanner] 高優先頁面 {len(focus)} 頁 / 全份 {len(pages)} 頁 "
              f"= 縮減至 {ratio:.1%}")

    # --- 功能D:財務報表 ---------------------------------------------
    fin = extract_financials(pages)

    # 會計恆等式交叉驗證 —— 直接印在終端機,不用開 Excel 就知道有沒有抓錯
    from financials import integrity_checks
    checks = integrity_checks(fin)
    if checks:
        failed = [c for c in checks if not c[1]]
        for name, ok, detail in checks:
            if not ok:
                print(f"[check] ✗ {name}: {detail}")
        if failed:
            print(f"[check] ⚠ {len(failed)}/{len(checks)} 項交叉驗證未通過,"
                  f"請對照來源頁人手確認")
        else:
            print(f"[check] ✓ {len(checks)} 項會計恆等式交叉驗證全部通過")

    # --- AI 語意層(選用) --------------------------------------------
    ai_findings = ai_layer.refine(pages, focus) if use_ai else []

    # --- 功能C:結構化輸出 -------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(out_dir, f"{base}_extract.xlsx")

    build_workbook(
        out_path=out_path,
        source_file=os.path.basename(pdf_path),
        pdf_stats=stats,
        param_hits=param_hits,
        fin_result=fin,
        topic_hits=topic_hits,
        ai_findings=ai_findings,
        ocr_pages=[p.index for p in pages if p.needs_ocr],
    )
    print(f"\n✓ 已輸出: {out_path}\n")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="HKEX 年報 / 招股書資料萃取工具")
    ap.add_argument("--pdf", action="append",
                    help="PDF 路徑、資料夾、或萬用字元樣式(可重複)。"
                         "指定資料夾會處理裡面所有 PDF")
    ap.add_argument("--recursive", action="store_true",
                    help="指定資料夾時,連子資料夾一起掃描")
    ap.add_argument("--from", dest="from_date", help="起始日 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", help="結束日 YYYYMMDD")
    ap.add_argument("--stock", help="股票代號,例如 00700")
    ap.add_argument("--type", default="annual_report",
                    choices=["annual_report", "interim_report",
                             "quarterly_report", "listing_document"])
    ap.add_argument("--max", type=int, default=5, help="最多下載幾份")
    ap.add_argument("--ai", action="store_true", help="啟用 AI 語意層")
    ap.add_argument("--out", default="output", help="輸出資料夾")
    ap.add_argument("--engine", choices=["pdfplumber", "pymupdf"],
                    help="PDF 讀取引擎。PyMuPDF 快很多,但請先用 "
                         "compare_engines.py 驗證結果一致")
    args = ap.parse_args()

    pdfs = expand_pdf_inputs(args.pdf, recursive=args.recursive)

    if args.from_date or args.to_date or args.stock:
        print("=" * 68)
        print("下載功能已移到 pipeline.py")
        print("=" * 68)
        print("原因:HKEXnews 沒有公開 API,舊的 hkexnews.py 已證實無效")
        print("     (它會「查到」空白結果卻不報錯)。改用瀏覽器自動化版本。")
        print()
        print("請改用:")
        codes = args.stock or "00700"
        print(f"    python3 pipeline.py --stocks {codes} "
              f"--from {args.from_date or 'YYYYMMDD'} --to {args.to_date or 'YYYYMMDD'}")
        print()
        print("run.py 專責分析本機 PDF:")
        print("    python3 run.py --pdf downloads/xxx.pdf")
        sys.exit(1)

    if not pdfs:
        ap.error("請用 --pdf 指定本機檔案或資料夾。"
                 "要從 HKEXnews 下載請改用 pipeline.py --stocks")

    for p in pdfs:
        if not os.path.exists(p):
            print(f"找不到檔案: {p}"); continue
        try:
            process_one(p, args.out, args.ai, args.engine)
        except Exception as e:
            import traceback
            print(f"處理失敗 {p}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
