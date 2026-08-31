# -*- coding: utf-8 -*-
"""
test_financials.py — 鎖住財務科目誤判的 bug

實測騰訊年報時發現:用「整行包含 revenue」比對,會把
    Cost of revenues 7 (311,011) (315,906)
判成 Revenue。抓到的是成本、而且是負數。

這是最危險的一類錯誤:數字看起來完全正常,不會報錯,
但意義完全相反 —— 除非人工翻回原文,否則不可能發現。

用法: python3 test_financials.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from financials import _match_line_item, _numbers_in_line, extract_financials
from pdf_reader import Page
from config import FIN_STATEMENTS

IS = FIN_STATEMENTS["Income Statement"]["line_items"]
BS = FIN_STATEMENTS["Balance Sheet"]["line_items"]
CF = FIN_STATEMENTS["Cash Flow"]["line_items"]

ok = True


def check(items, line, expect, note=""):
    global ok
    r = _match_line_item(line, items)
    got = r[0] if r else None
    pas = got == expect
    if not pas:
        ok = False
    print(f"  {'✓' if pas else '✗'} {line[:46]:46} → {got}"
          + (f"  (應為 {expect})" if not pas else "")
          + (f"   {note}" if note else ""))


print("騰訊年報實際踩到的誤判")
check(IS, "Cost of revenues 7 (311,011) (315,906)", "Cost of Sales",
      "← 曾被誤判為 Revenue")
check(BS, "Other intangible assets 20 97 132", None,
      "← 細項不應被當成總額")

print()
print("正常情況仍要抓得到")
check(IS, "Revenues 5 660,257 609,015", "Revenue")
check(IS, "Revenue from contracts with customers 5 1,284,500 1,142,800", "Revenue")
check(IS, "Gross profit 494,533 413,695", "Gross Profit")
check(IS, "Profit for the year 52,123 23,695", "Profit for the Year")
check(BS, "Total assets 1,780,995 1,577,246", "Total Assets")
check(BS, "Total current liabilities 432,832 367,998", "Total Current Liabilities")
check(BS, "Intangible assets 15 142,880 131,400", "Intangible Assets")
check(CF, "Net cash generated from operating activities 168,420 121,880",
      "Operating Cash Flow")

print()
print("數字解析:附註編號要剔除、括號視為負數")
n = _numbers_in_line("Cost of sales 7 (789,967) (729,105)")
check_ok = n == [-789967.0, -729105.0]
if not check_ok:
    ok = False
print(f"  {'✓' if check_ok else '✗'} 附註 7 已剔除,括號轉負數 → {n}")

print()
print("騰訊式排版:科目名那行沒金額,總額在細項後獨立成行")
from financials import extract_financials
from pdf_reader import Page
tencent = """CONSOLIDATED STATEMENT OF PROFIT OR LOSS
Note 2024 2023
Revenues 5
VAS 319,268 298,375
Online Advertising 121,161 101,482
Others 7,747 5,961
660,257 609,015
Cost of revenues 7 (311,011) (315,906)
Gross profit 349,246 293,109
Profit before income tax 241,485 163,528"""
fin = extract_financials([Page(124,'123',tencent,len(tencent),False,[])], verbose=False)
d = {i.item: i.current_year for i in fin.items}
for k, v in [("Revenue", 660257.0), ("Cost of Sales", -311011.0),
             ("Gross Profit", 349246.0), ("Profit Before Tax", 241485.0)]:
    p = d.get(k) == v
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {k} = {d.get(k)}" + ("" if p else f"  (應為 {v})"))

print()
print("未擷取科目要被記錄下來,不能靜靜消失")
has = bool(getattr(fin, "missing", None))
if not has:
    ok = False
print(f"  {'✓' if has else '✗'} missing 欄位有記錄未擷取的科目")

print()
print("同頁多行符合同一科目時,要取最精確的別名")
cf = """Consolidated Statement of Cash Flows
Cash flows from operating activities
Cash generated from operations 43(a) 304,705 256,691
Interest received 15,588 13,014
Income tax paid (61,772) (47,743)
Net cash flows generated from operating activities 258,521 221,962
Cash flows from investing activities
Purchase of/prepayments for property, plant and equipment,
construction in progress and investment properties (62,927) (21,008)
Net cash flows used in investing activities (122,187) (125,161)"""
fin2 = extract_financials([Page(133,'132',cf,len(cf),False,[])], verbose=False)
d2 = {i.item: i.current_year for i in fin2.items}
for k, v, note in [
    ("Operating Cash Flow", 258521.0, "← 不可抓成 304,705(未扣利息稅項)"),
    ("Capital Expenditure", -62927.0, "← 換行標籤,金額在下一行"),
    ("Investing Cash Flow", -122187.0, ""),
]:
    p = d2.get(k) == v
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {k} = {d2.get(k)}"
          + ("" if p else f"  (應為 {v})") + f"   {note}")

print()
print("報表頁判定:標題在頁首才算,附註頁提到不算")
from financials import _find_statement_pages
pgs = [
    Page(133, '132', "Consolidated Statement of Cash Flows\nNet cash 1 2 3", 40, False, []),
    Page(256, '255', "Notes to the Consolidated Financial Statements\n"
                     "see consolidated statement of cash flows 9 9 9 9 9 9 9 9 9", 90, False, []),
]
r = _find_statement_pages(pgs, ["consolidated statement of cash flows"])
p = r and r[0] == 133
if not p:
    ok = False
print(f"  {'✓' if p else '✗'} 選中 p.{r[0] if r else None}(應為 133,而非數字較多的附註頁 256)")

print()
print("中英對照年報(佔港股年報一半以上)")
bi = """綜合損益表 CONSOLIDATED STATEMENT OF PROFIT OR LOSS
二零二六年 二零二五年 2026 2025
收益 Revenue 6 98,555 79,128
銷售成本 Cost of sales (31,980) (26,969)
毛利 Gross profit 66,575 52,159
除稅前溢利╱（虧損） Profit/(loss) before tax 94,630 (3,074)
所得稅開支 Income tax expense 12 – (3,772)"""
f3 = extract_financials([Page(79,'77',bi,len(bi),False,[])], verbose=False)
d3 = {i.item: (i.current_year, i.prior_year) for i in f3.items}
for k, v, note in [
    ("Revenue", (98555.0, 79128.0), "← 中文標籤在前,英文在後"),
    ("Gross Profit", (66575.0, 52159.0), ""),
    ("Profit Before Tax", (94630.0, -3074.0), "← Profit/(loss) 寫法"),
    ("Income Tax", (0.0, -3772.0), "← 破折號 = 0,不可讓上年數字左移"),
]:
    p = d3.get(k) == v
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {k} = {d3.get(k)}"
          + ("" if p else f"  (應為 {v})") + f"   {note}")

print()
print("附註編號 vs 真實小額數值")
for line, expect, note in [
    ("TOTAL EQUITY 95 59,753", [95.0, 59753.0], "← 95 是真實權益,不是附註編號"),
    ("Property, plant and equipment 17 56 2,341", [56.0, 2341.0], "← 剔除附註 17,保留 56"),
    ("Revenue 7 38,943 59,930", [38943.0, 59930.0], "← 剔除附註 7"),
    ("Deferred tax liabilities 31 – 131", [0.0, 131.0], "← 破折號補位"),
]:
    got = _numbers_in_line(line)
    p = got == expect
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {line[:44]:44} → {got}   {note}")

print()
print("延伸科目不可誤配")
for line, items, expect, note in [
    ("TOTAL ASSETS LESS CURRENT LIABILITIES 15,383 80,209", BS, None,
     "← 總資產減流動負債 ≠ 總資產"),
    ("總資產減流動負債 Total assets less current liabilities 472,884 377,497", BS, None,
     "← 中文版同理"),
    ("Total assets 1,780,995 1,577,246", BS, "Total Assets", ""),
]:
    r = _match_line_item(line, items)
    got = r[0] if r else None
    p = got == expect
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {line[:44]:44} → {got}   {note}")

print()
print("虧損公司:自動生成的 profit/loss 對稱別名")
loss_stmt = """CONSOLIDATED STATEMENT OF PROFIT OR LOSS
Cost of sales (29,708) (46,292)
Gross profit 9,235 13,638
OPERATING LOSS (67,126) (41,967)
LOSS BEFORE TAX 10 (67,378) (42,294)
LOSS FOR THE YEAR (67,821) (42,497)"""
f4 = extract_financials([Page(84,'83',loss_stmt,len(loss_stmt),False,[])], verbose=False)
d4 = {i.item: i.current_year for i in f4.items}
for k, v, note in [
    ("Operating Profit", -67126.0, "← 原文寫 OPERATING LOSS"),
    ("Profit Before Tax", -67378.0, "← 原文寫 LOSS BEFORE TAX"),
    ("Profit for the Year", -67821.0, "← 原文寫 LOSS FOR THE YEAR"),
]:
    p = d4.get(k) == v
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {k} = {d4.get(k)}"
          + ("" if p else f"  (應為 {v})") + f"   {note}")

print()
print("自動生成不應產生重複或污染原本的別名")
from config import FIN_STATEMENTS as _FS
op_aliases = [a.lower() for a in _FS["Income Statement"]["line_items"]["Operating Profit"]]
p = ("operating loss" in op_aliases and len(op_aliases) == len(set(op_aliases)))
if not p:
    ok = False
print(f"  {'✓' if p else '✗'} Operating Profit 別名含 'operating loss' 且無重複: {op_aliases}")

print()
print("別名擴充:港股常見的措辭變體(TASTY CONCEPTS 08096 實例)")
for line, items, expect, note in [
    ("Cost of inventories (9,055) (8,798)", IS, "Cost of Sales", "← 餐飲/零售業寫法"),
    ("Property and equipment 15 5,621 12,758", BS, "Property Plant and Equipment", "← 不含廠房"),
    ("Bank balances and cash 20 8,892 6,804", BS, "Cash and Equivalents", "← 港股小型股偏好"),
    ("Other borrowing 24 1,920 –", BS, "Borrowings", ""),
    ("Net assets 6,272 14,003", BS, "Total Equity", "← 恆等式上等同總權益"),
    ("Payment for purchase of property and equipment (400) (3,080)", CF,
     "Capital Expenditure", "← CAPEX 的冗長句型"),
    ("Loss before taxation 10 (7,758) (6,156)", IS, "Profit Before Tax", "← 虧損年度"),
]:
    r = _match_line_item(line, items)
    got = r[0] if r else None
    p = got == expect
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {line[:46]:48} → {got}"
          + ("" if p else f"  (應為 {expect})") + f"   {note}")

print()
print("★ 這些相似字眼「絕對不可」互相誤配(為何不採用模糊比對)")
for line, items, forbidden, note in [
    ("Total assets less current liabilities 8,392 14,279", BS, "Total Assets",
     "模糊比對相似度 100%,但意義完全不同"),
    ("Trade and other payables 21 5,170 5,697", BS, "Trade Receivables",
     "應付 vs 應收 —— 資產負債顛倒"),
]:
    r = _match_line_item(line, items)
    got = r[0] if r else None
    p = got != forbidden
    if not p:
        ok = False
    print(f"  {'✓' if p else '✗'} {line[:46]:48} → {got}   ({note})")

print()
print("全部通過" if ok else "有測試失敗")
sys.exit(0 if ok else 1)
