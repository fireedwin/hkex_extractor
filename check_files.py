# -*- coding: utf-8 -*-
"""
check_files.py — 確認你跑的是最新版程式

會發生什麼問題:
    整理資料夾時,舊的 .py 可能同時留在外層和子資料夾裡。
    Python 只會載入其中一份,你更新了另一份卻毫無效果 ——
    而且不會報任何錯,只是行為跟預期不同。這種問題很難靠讀日誌發現。

這個工具會:
    1. 找出所有重複的 .py 檔,標示哪一份會被實際載入
    2. 檢查關鍵設定與新功能是否存在(例如引擎是否已切到 PyMuPDF)

用法: python3 check_files.py
"""

import console  # noqa: F401

import os
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))

# 檔名 → (要檢查的關鍵字, 說明)
FEATURE_CHECKS = {
    "pdf_reader.py": [
        ('DEFAULT_ENGINE = "pymupdf"', "預設引擎已切換到 PyMuPDF"),
        ("_words_to_lines", "PyMuPDF 表格行重建(修正財務科目歸零)"),
        ("_reconcile_page_numbers", "頁碼一致性校正"),
    ],
    "scanner.py": [
        ("_resolve_respectively", "並列句型解析(A 和 B 分別為 X 和 Y)"),
        ("_match_percent_backward", "往回搜尋百分比"),
        ("_PCT_UNIT_MARKER", "表格式百分比 (%) 13.2"),
    ],
    "hkexnews_selenium.py": [
        ("autocomplete 未回應,重試", "autocomplete 重試機制"),
        ("查得 0 筆", "查無結果自動重試"),
        ("查無年報,請人手確認", "查無結果明確回報"),
    ],
    "run.py": [("import console", "Windows 編碼修正")],
    "pipeline.py": [("import console", "Windows 編碼修正")],
    "console.py": [("reconfigure", "UTF-8 輸出設定")],
}


def main():
    print("=" * 66)
    print("1. 檢查重複檔案")
    print("=" * 66)

    dupes = 0
    for name in FEATURE_CHECKS:
        hits = (glob.glob(os.path.join(HERE, name))
                + glob.glob(os.path.join(HERE, "*", name)))
        if len(hits) > 1:
            dupes += 1
            print(f"  ⚠ {name} 有 {len(hits)} 份:")
            for h in hits:
                loc = "外層(優先)" if os.path.dirname(os.path.abspath(h)) == HERE else "子資料夾"
                print(f"      {os.path.abspath(h)}   [{loc}]")
            print(f"      → 建議只保留外層那份,刪掉其他的")
    if not dupes:
        print("  ✓ 沒有重複檔案")
    print()

    print("=" * 66)
    print("2. 檢查各檔案是否為最新版")
    print("=" * 66)

    missing = 0
    for name, checks in FEATURE_CHECKS.items():
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print(f"  ✗ {name} 不存在")
            missing += 1
            continue
        try:
            src = open(path, encoding="utf-8").read()
        except Exception as e:
            print(f"  ✗ {name} 讀取失敗: {e}")
            missing += 1
            continue

        bad = [(kw, desc) for kw, desc in checks if kw not in src]
        if not bad:
            print(f"  ✓ {name}")
        else:
            missing += len(bad)
            print(f"  ✗ {name} — 缺少 {len(bad)} 項功能:")
            for kw, desc in bad:
                print(f"      缺: {desc}")
    print()

    print("=" * 66)
    if missing == 0 and dupes == 0:
        print("全部檔案都是最新版,沒有重複副本。")
    else:
        print("請把標示 ✗ 的檔案換成 Claude 提供的最新版,")
        print("並刪掉子資料夾裡多餘的副本,然後重跑這個檢查。")
    print("=" * 66)


if __name__ == "__main__":
    main()
