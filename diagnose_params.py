# -*- coding: utf-8 -*-
"""
diagnose_params.py — 診斷「估值參數 0 筆」的原因

抓不到參數有兩種完全不同的原因,處理方式也完全不同:

  A) 文件裡根本沒有這個資訊
     → 例如公司沒有商譽、不做減值測試,或年報寫得很簡略。
       這不是程式的問題,結果是正確的。

  B) 文件裡有,但關鍵字或數字格式沒對上
     → 這是程式要修的。

這個工具會直接告訴你是哪一種:先查關鍵字在不在文件裡,
在的話就把原文附近的文字印出來,一眼就能看出數字是什麼格式。

用法:
    python3 diagnose_params.py downloads/00731_C_D_NEWIN_20250424.pdf
"""

# 必須最先 import —— 修正 Windows 輸出重新導向時的 cp950 編碼錯誤
import console  # noqa: F401

import sys
import re
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_reader import read_pdf
from scanner import scan_valuation_params, _clean, _match_percent
from config import VALUATION_PARAMS, PARAM_WINDOW


def main():
    if len(sys.argv) < 2:
        print("用法: python3 diagnose_params.py <PDF路徑> [--page N] [--engine 引擎]")
        print("  --page N        直接印出第 N 頁的原文(用來看數字實際長什麼樣)")
        print("  --engine 引擎    pdfplumber 或 pymupdf,用來比對兩個引擎的差異")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"找不到檔案: {path}")
        sys.exit(1)

    engine = None
    if "--engine" in sys.argv:
        i = sys.argv.index("--engine")
        try:
            engine = sys.argv[i + 1]
        except IndexError:
            print("--engine 後面要接 pdfplumber 或 pymupdf")
            sys.exit(1)

    print("讀取 PDF 中...")
    pages = read_pdf(path, extract_tables=False, verbose=False, engine=engine)
    print(f"共 {len(pages)} 頁\n")

    # --page N:直接印出某一頁的原文
    if "--page" in sys.argv:
        idx = sys.argv.index("--page")
        try:
            n = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("--page 後面要接頁碼數字")
            sys.exit(1)
        target = next((p for p in pages if p.index == n), None)
        if not target:
            print(f"沒有第 {n} 頁")
            sys.exit(1)
        print("=" * 68)
        print(f"{target.cite} 原文   (引擎: {engine or '預設'})")
        print("=" * 68)
        print(target.text)
        print("=" * 68)
        # 頁碼偵測是看頁首/頁尾各兩行,把它們單獨列出來方便判斷
        lines = [l.strip() for l in target.text.splitlines() if l.strip()]
        print("頁碼偵測的依據(頁首前2行 / 頁尾後2行):")
        print(f"  頁首: {lines[:2]}")
        print(f"  頁尾: {lines[-2:]}")
        print(f"  判定結果: 印刷頁 = {target.printed_no}")
        return

    hits = scan_valuation_params(pages)
    print("=" * 68)
    print(f"目前擷取結果: {len(hits)} 筆")
    print("=" * 68)
    for h in hits:
        print(f"  {h.parameter:22} {h.value_low:6.2f}%  {h.confidence:6} {h.page_cite}")
    print()

    # ── 逐一檢查每個參數的觸發詞 ────────────────────────
    print("=" * 68)
    print("逐項診斷")
    print("=" * 68)

    for param, cfg in VALUATION_PARAMS.items():
        found_pages = []
        samples = []

        for page in pages:
            if not page.text:
                continue
            flat = _clean(page.text)
            low = flat.lower()
            for trig in cfg["triggers"]:
                for m in re.finditer(re.escape(trig.lower()), low):
                    found_pages.append(page.index)
                    if len(samples) < 3:
                        start = max(0, m.start() - 60)
                        window = flat[m.end(): m.end() + PARAM_WINDOW]
                        matched = _match_percent(window)
                        samples.append({
                            "page": page.cite,
                            "trigger": trig,
                            "text": flat[start: m.end() + 120],
                            "matched": matched,
                        })
                    break

        got = [h for h in hits if h.parameter == param]

        if not found_pages:
            print(f"\n【{param} / {cfg['zh']}】")
            print(f"  ✗ 文件裡完全找不到關鍵字 → 這份年報應該沒有揭露這項資訊")
            print(f"    (已搜尋: {', '.join(cfg['triggers'][:4])}...)")
            continue

        if got:
            print(f"\n【{param} / {cfg['zh']}】")
            print(f"  ✓ 正常擷取 {len(got)} 筆,關鍵字出現在 {len(set(found_pages))} 頁")
            continue

        # 關鍵字有,但沒抓到數字 —— 這才是要修的情況
        print(f"\n【{param} / {cfg['zh']}】")
        print(f"  ⚠ 關鍵字出現在 {len(set(found_pages))} 頁,但抓不到數字")
        print(f"    出現頁碼: {sorted(set(found_pages))[:10]}")
        print(f"    原文範例:")
        for s in samples:
            print(f"      [{s['page']}] 命中詞 '{s['trigger']}'")
            print(f"        ...{s['text'][:170]}...")
            print(f"        → 數字比對結果: {s['matched']}")
        print(f"    ※ 請把上面的原文貼給 Claude,可據此調整數字擷取規則")

    # ── 中文版本檢查 ──────────────────────────────────
    print()
    print("=" * 68)
    print("語言檢查")
    print("=" * 68)
    all_text = " ".join(p.text for p in pages[:60])
    cjk = len(re.findall(r"[\u4e00-\u9fff]", all_text))
    latin = len(re.findall(r"[A-Za-z]", all_text))
    total = cjk + latin
    if total:
        print(f"  中文字元 {cjk:,} ({cjk/total:.0%})  /  英文字母 {latin:,} ({latin/total:.0%})")
        if cjk / total > 0.5:
            print("  → 這份主要是中文年報。請確認 config.py 的中文關鍵字是否足夠;")
            print("    港交所有中英文雙版本,英文版通常比較好處理。")
    print()


if __name__ == "__main__":
    main()
