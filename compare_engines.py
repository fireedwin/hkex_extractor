# -*- coding: utf-8 -*-
"""
compare_engines.py — 驗證換引擎會不會改變結果

換 PDF 讀取引擎是動到整個工具的最底層。速度快 100 倍沒有意義,
除非擷取出來的數字完全一樣 —— 估值報告的數字錯了是要負責任的。

這個工具用同一份 PDF 分別跑兩個引擎,然後逐項比對:
    估值參數 / 財務科目 / 頁碼標註 / 掃描頁偵測
只要有任何一項對不上就會標紅,並印出差異細節。

用法:
    python3 compare_engines.py downloads/00700_TENCENT_20250408.pdf
    python3 compare_engines.py downloads/*.pdf          (可一次多份)
"""

# 必須最先 import —— 修正 Windows 輸出重新導向時的 cp950 編碼錯誤
import console  # noqa: F401

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_reader import read_pdf, engine_available
from scanner import scan_valuation_params, scan_topics
from financials import extract_financials


def run_engine(path, engine):
    t0 = time.time()
    pages = read_pdf(path, extract_tables=False, verbose=False, engine=engine)
    elapsed = time.time() - t0

    params = scan_valuation_params(pages)
    fin = extract_financials(pages, verbose=False)
    topics = scan_topics(pages)

    return {
        "seconds": elapsed,
        "page_count": len(pages),
        "cites": [p.cite for p in pages],
        "ocr_pages": sorted(p.index for p in pages if p.needs_ocr),
        # 用可比較的形式存起來,方便直接做集合運算
        "params": sorted(
            (p.parameter, p.value_low, p.value_high, p.page_index) for p in params),
        "fin": sorted(
            (i.statement, i.item, i.current_year, i.prior_year, i.page_index)
            for i in fin.items),
        "topics": sorted((t.topic, t.page_index) for t in topics),
    }


def diff_report(label, a, b, show=6):
    """比較兩個集合,回傳是否相同。"""
    sa, sb = set(a), set(b)
    if sa == sb:
        print(f"  ✓ {label:16} 完全相同 ({len(sa)} 筆)")
        return True

    only_a = sorted(sa - sb)
    only_b = sorted(sb - sa)
    print(f"  ✗ {label:16} 有差異  (pdfplumber {len(sa)} 筆 / PyMuPDF {len(sb)} 筆)")
    if only_a:
        print(f"      只有 pdfplumber 抓到 ({len(only_a)} 筆):")
        for x in only_a[:show]:
            print(f"        {x}")
        if len(only_a) > show:
            print(f"        ...還有 {len(only_a)-show} 筆")
    if only_b:
        print(f"      只有 PyMuPDF 抓到 ({len(only_b)} 筆):")
        for x in only_b[:show]:
            print(f"        {x}")
        if len(only_b) > show:
            print(f"        ...還有 {len(only_b)-show} 筆")
    return False


def compare_one(path):
    print("=" * 70)
    print(f"檔案: {os.path.basename(path)}")
    print("=" * 70)

    print("執行 pdfplumber ...")
    a = run_engine(path, "pdfplumber")
    print("執行 PyMuPDF ...")
    b = run_engine(path, "pymupdf")

    print()
    print(f"  頁數        pdfplumber {a['page_count']}  /  PyMuPDF {b['page_count']}")
    print(f"  耗時        pdfplumber {a['seconds']:.1f} 秒  /  "
          f"PyMuPDF {b['seconds']:.1f} 秒", end="")
    if b["seconds"] > 0:
        print(f"   → 快 {a['seconds']/b['seconds']:.0f} 倍")
    else:
        print()
    print()

    ok = True
    ok &= (a["page_count"] == b["page_count"])
    if a["page_count"] != b["page_count"]:
        print("  ✗ 頁數不同,後續比對意義不大")

    ok &= diff_report("估值參數", a["params"], b["params"])
    ok &= diff_report("財務科目", a["fin"], b["fin"])
    ok &= diff_report("主題段落", a["topics"], b["topics"])
    ok &= diff_report("掃描頁偵測", a["ocr_pages"], b["ocr_pages"])

    # 頁碼標註逐頁比對
    cite_diff = [(i + 1, x, y) for i, (x, y)
                 in enumerate(zip(a["cites"], b["cites"])) if x != y]
    if not cite_diff:
        print(f"  ✓ {'頁碼標註':16} 完全相同 ({len(a['cites'])} 頁)")
    else:
        ok = False
        print(f"  ✗ {'頁碼標註':16} 有 {len(cite_diff)} 頁不同")
        for pg, x, y in cite_diff[:6]:
            print(f"        第 {pg} 頁: pdfplumber「{x}」 / PyMuPDF「{y}」")

    print()
    if ok:
        print("  結論:兩個引擎結果完全一致 ✓  可以安心切換到 PyMuPDF")
    else:
        print("  結論:有差異 ✗  請把上面的差異細節貼給 Claude 判斷是否可接受")
    print()
    return ok


def main():
    if len(sys.argv) < 2:
        print("用法: python3 compare_engines.py <PDF路徑> [更多PDF...]")
        sys.exit(1)

    if not engine_available("pymupdf"):
        print("尚未安裝 PyMuPDF。請先執行:")
        print("    python3 -m pip install pymupdf")
        sys.exit(1)

    paths = [p for p in sys.argv[1:] if p.lower().endswith(".pdf")]
    if not paths:
        print("沒有指定任何 PDF 檔")
        sys.exit(1)

    results = []
    for p in paths:
        if not os.path.exists(p):
            print(f"找不到檔案,略過: {p}")
            continue
        results.append((os.path.basename(p), compare_one(p)))

    if len(results) > 1:
        print("=" * 70)
        print("總結")
        print("=" * 70)
        for name, ok in results:
            print(f"  {'✓ 一致' if ok else '✗ 有差異'}   {name}")
        print()

    if results and all(ok for _, ok in results):
        print("全部檔案驗證通過。")
        print("可以把 pdf_reader.py 裡的 DEFAULT_ENGINE 改成 \"pymupdf\"。")
    print()


if __name__ == "__main__":
    main()
