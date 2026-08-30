# -*- coding: utf-8 -*-
"""
check_pagenos.py — 檢查印刷頁碼偵測的可靠度

原理:年報的「PDF 頁序」與「印刷頁碼」之間通常有一個固定偏移量。
例如封面加目錄共 1 頁不編號,那麼 PDF p.51 就是印刷頁 50,偏移 = 1。

如果某一頁算出來的偏移量跟其他頁差很多,那八成是誤判 ——
把頁面上剛好出現的某個數字當成頁碼了。

這個工具把全份文件的偏移量統計出來,異常值一目了然。

用法:
    python3 check_pagenos.py downloads/00731_C_D_NEWIN_20250424.pdf
    python3 check_pagenos.py <PDF> --engine pymupdf
"""

# 必須最先 import —— 修正 Windows 輸出重新導向時的 cp950 編碼錯誤
import console  # noqa: F401

import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_reader import read_pdf, engine_available


def analyse(path, engine):
    pages = read_pdf(path, extract_tables=False, verbose=False, engine=engine)

    offsets = {}
    for p in pages:
        if p.printed_no is None:
            continue
        try:
            offsets[p.index] = p.index - int(p.printed_no)
        except ValueError:
            continue

    counter = Counter(offsets.values())
    print(f"--- 引擎: {engine} ---")
    print(f"  總頁數 {len(pages)},其中 {len(offsets)} 頁偵測到印刷頁碼")
    if not counter:
        print("  沒有偵測到任何印刷頁碼")
        return pages, offsets, None

    print("  偏移量分布(偏移 = PDF頁序 − 印刷頁碼):")
    for off, cnt in counter.most_common(6):
        bar = "█" * min(40, cnt)
        print(f"    偏移 {off:>5}  出現 {cnt:>4} 頁  {bar}")

    main_off = counter.most_common(1)[0][0]
    outliers = sorted(i for i, o in offsets.items() if o != main_off)
    if outliers:
        print(f"  ⚠ 偏離主流偏移({main_off})的頁面共 {len(outliers)} 頁:")
        for i in outliers[:15]:
            p = next(x for x in pages if x.index == i)
            print(f"      PDF p.{i} → 印刷頁 {p.printed_no}  (偏移 {offsets[i]})")
        if len(outliers) > 15:
            print(f"      ...還有 {len(outliers)-15} 頁")
    else:
        print(f"  ✓ 所有偵測到的頁碼偏移量一致({main_off}),沒有可疑值")
    print()
    return pages, offsets, main_off


def main():
    if len(sys.argv) < 2:
        print("用法: python3 check_pagenos.py <PDF路徑> [--engine 引擎]")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"找不到檔案: {path}")
        sys.exit(1)

    engines = ["pdfplumber"]
    if "--engine" in sys.argv:
        i = sys.argv.index("--engine")
        engines = [sys.argv[i + 1]]
    elif engine_available("pymupdf"):
        engines = ["pdfplumber", "pymupdf"]

    print("=" * 68)
    print(f"檔案: {os.path.basename(path)}")
    print("=" * 68)

    results = {}
    for eng in engines:
        results[eng] = analyse(path, eng)

    # 兩引擎都跑過的話,列出差異並判斷誰比較可信
    if len(results) == 2:
        a_pages, a_off, a_main = results["pdfplumber"]
        b_pages, b_off, b_main = results["pymupdf"]
        diffs = sorted(set(a_off) ^ set(b_off))
        if not diffs:
            print("兩引擎偵測到的頁碼完全相同。")
            return
        print("=" * 68)
        print("兩引擎有差異的頁面 — 依偏移量判斷哪一邊比較可信")
        print("=" * 68)
        for i in diffs:
            in_a = i in a_off
            off = a_off.get(i, b_off.get(i))
            who = "pdfplumber" if in_a else "PyMuPDF"
            main = a_main if in_a else b_main
            verdict = ("看起來合理" if off == main
                       else f"⚠ 偏移 {off} 與主流 {main} 不符,可能是誤判")
            pg = next(x for x in (a_pages if in_a else b_pages) if x.index == i)
            print(f"  PDF p.{i}: 只有 {who} 偵測到印刷頁 {pg.printed_no} — {verdict}")
        print()
        print("提示:標示「可能是誤判」的那一邊,不抓到反而是正確的。")
    print()


if __name__ == "__main__":
    main()
