# -*- coding: utf-8 -*-
"""
test_pagenos.py — 鎖住頁碼偵測的兩個真實 bug

Bug 1(C&D 年報 p.86):頁尾是 ['2', 'ANNUAL REPORT 2024 85'],
      那個「2」是 CO₂ 下標被 PDF 拆行,真正頁碼是 85。
      只取第一個候選會抓錯。

Bug 2:「ANNUAL REPORT 2024 85」這種格式,舊正則抓不到 85
      (因為 85 前面隔著空白的是數字 '4',不是非數字字元)。

用法: python3 test_pagenos.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_reader import _page_no_candidates, _reconcile_page_numbers, _make_page

ok = True


def check(name, cond, detail=""):
    global ok
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        ok = False


print("Bug 2:尾端頁碼格式")
for text, expect in [
    ("Some content\nANNUAL REPORT 2024 85", "85"),
    ("Some content\n85 Annual Report 2024", "85"),
    ("Some content\n   142   ", "142"),
]:
    c = _page_no_candidates(text)
    check(f"{text.splitlines()[-1].strip()!r} → {expect}", expect in c, f"候選={c}")

print()
print("Bug 1:CO₂ 下標干擾,靠偏移量一致性挑對的")
trap = ("Emission factor CO\n2\npublished: 0.5366 kgCO/kWh.\n2\n"
        "ANNUAL REPORT 2024 85")
cands = _page_no_candidates(trap)
check("候選同時含 '2' 與 '85'", "2" in cands and "85" in cands, f"候選={cands}")

pages = [_make_page(86, trap) if i == 86
         else _make_page(i, f"content\nANNUAL REPORT 2024 {i-1}")
         for i in range(1, 91)]
check("校正前誤抓下標", pages[85].printed_no == "2")
_reconcile_page_numbers(pages, verbose=False)
check("校正後修正為 85", pages[85].printed_no == "85",
      f"實際={pages[85].printed_no}")

print()
print("安全閘門:偏移量雜亂時不硬套")
messy = [_make_page(i, f"content\n{i*7}") for i in range(1, 11)]
before = [p.printed_no for p in messy]
_reconcile_page_numbers(messy, verbose=False)
check("偏移不集中 → 保留原判", [p.printed_no for p in messy] == before)

print()
print("全部通過" if ok else "有測試失敗")
sys.exit(0 if ok else 1)
