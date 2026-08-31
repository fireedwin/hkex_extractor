# -*- coding: utf-8 -*-
"""
test_error_report.py — 錯誤紀錄回歸測試

測試素材直接取自真實執行輸出(00700 查無結果、01007 通函分析),
不是自己編的字串 —— 這樣「訊息措辭改了但 ERROR_PATTERNS 沒跟著改」
這種失效才會被抓到。

    python3 test_error_report.py
"""
try:
    import console  # noqa: F401
except ImportError:
    pass

import os
import sys
import shutil
import tempfile
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from error_report import (ErrorReport, OutputCapture, scan_text,  # noqa: E402
                          stock_from_name, UNGENERATED)

PASS, FAIL = [], []


def ok(cond, label, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'✓' if cond else '✗'} {label}" + (f"  {detail}" if detail else ""))


# 真實輸出:01007 那份通函(顯示「成功」但實際 0 個科目)
REAL_01007 = """
====================================================================
處理: downloads\\01007_LONGHUI_INTL_MT_20260825.pdf
====================================================================
[pdf_reader] 開啟 downloads\\01007_LONGHUI_INTL_MT_20260825.pdf,共 125 頁 (引擎: PyMuPDF)
[pdf_reader] 頁碼一致性校正(主流偏移 2): 修正 0 頁,剔除可疑 4 頁
[pdf_reader] 完成。可能需要 OCR 的頁數: 0
[scanner] 主題段落 43 筆;估值參數 2 筆
[scanner] 高優先頁面 20 頁 / 全份 125 頁 = 縮減至 16.0%
[financials] 資產負債表 候選頁校正: [14, 96] → [14](依報表相鄰原則)
[financials] 綜合損益表: PDF p.53 (年度欄 未偵測)
[financials] 資產負債表: PDF p.14 (年度欄 2026 / 2025)
[financials] 找不到「現金流量表」的頁面
[financials] 共擷取 0 個財務科目
[financials]   綜合損益表 未擷取: Revenue, Cost of Sales, Gross Profit, Operating Profit, Finance Costs, Profit Before Tax, Income Tax, Profit for the Year, R&D Expenses, Depreciation, Amortisation
[financials]   資產負債表 未擷取: Total Assets, Total Current Assets, Cash and Equivalents, Inventories, Trade Receivables, Goodwill, Intangible Assets, Investment Properties, Property Plant and Equipment, Total Liabilities, Total Current Liabilities, Borrowings, Total Equity
[check] ✓ 1 項會計恆等式交叉驗證全部通過
✓ 已輸出: output\\01007_LONGHUI_INTL_MT_20260825_extract.xlsx
"""

# 一份「真的有問題」的輸出:交叉驗證未通過 + 掃描頁
REAL_FAILING = """
[pdf_reader] 完成。可能需要 OCR 的頁數: 37
[scanner] 主題段落 5 筆;估值參數 0 筆
[financials] 共擷取 12 個財務科目
[check] ⚠ 1/3 項交叉驗證未通過,請對照來源頁人手確認
"""

# 一份正常的年報輸出,不該產生任何紀錄
REAL_CLEAN = """
[pdf_reader] 完成。可能需要 OCR 的頁數: 0
[scanner] 主題段落 14 筆;估值參數 10 筆
[financials] 共擷取 28 個財務科目
[check] ✓ 5 項會計恆等式交叉驗證全部通過
✓ 已輸出: output\\sample_annual_report_extract.xlsx
"""


def test_scan_real_output():
    print("掃描真實輸出:01007 通函(畫面顯示成功,實際 0 個科目)")
    hits = scan_text(REAL_01007)
    whats = [w for w, _ in hits]
    sev_of = dict(hits)
    joined = " / ".join(whats)
    ok(any("沒有擷取到財務科目" in h for h in whats),
       "抓到「0 個財務科目」—— 這正是被 ✓ 掩蓋掉的問題")
    ok(sev_of.get("完全沒有擷取到財務科目(這份文件可能不是財務報表類文件)") == "high",
       "「0 個財務科目」歸類為嚴重")
    ok(any("現金流量表" in h for h in whats), "抓到找不到現金流量表")
    ok(sev_of.get("找不到報表頁:現金流量表") == "medium", "找不到報表頁歸類為一般")
    ok(any("年度欄" in h for h in whats), "抓到損益表年度欄未偵測")
    ok(any("11 個科目未擷取" in h for h in whats),
       "算出綜合損益表未擷取科目數", [h for h in whats if "未擷取" in h])
    ok(sev_of.get("綜合損益表 有 11 個科目未擷取") == "low",
       "「N 個科目未擷取」歸類為輕微")
    ok(any("13 個科目未擷取" in h for h in whats), "算出資產負債表未擷取科目數")
    print(f"    共 {len(hits)} 項: {joined[:100]}...")


def test_scan_failing_checks():
    print("\n掃描真實輸出:交叉驗證未通過")
    hits = scan_text(REAL_FAILING)
    whats = [w for w, _ in hits]
    sev_of = dict(hits)
    ok(any("1/3" in h for h in whats), "抓到 1/3 項交叉驗證未通過", whats)
    ok(sev_of.get("會計恆等式交叉驗證 1/3 項未通過,請對照來源頁人手確認") == "high",
       "交叉驗證未通過歸類為嚴重")
    ok(any("37 頁" in h for h in whats), "抓到 37 頁疑似掃描頁")
    ok(sev_of.get("有 37 頁疑似掃描頁,需另接 OCR 才能處理") == "low",
       "疑似掃描頁歸類為輕微")
    ok(any("估值參數" in h for h in whats), "抓到估值參數 0 筆")


def test_clean_output_produces_nothing():
    print("\n正常年報輸出不該被誤報")
    hits = scan_text(REAL_CLEAN)
    ok(hits == [], "乾淨的輸出掃不出任何問題(否則每次都報警等於沒報警)", hits)


def test_stock_from_name():
    print("\n從檔名取股票代號")
    cases = [
        ("01007_LONGHUI_INTL_MT_20260825.pdf", "01007"),
        ("downloads/00700_TENCENT_20250408.pdf", "00700"),
        ("08096_TASTY_CONCEPTS_20260731.pdf", "08096"),
        ("sample_annual_report.pdf", ""),
        ("", ""),
    ]
    for name, want in cases:
        got = stock_from_name(name)
        ok(got == want, f"{name or '(空)'} → {want or '(留白)'}", got)


def test_file_written_and_format():
    print("\n紀錄檔內容與格式:嚴重度分級")
    work = tempfile.mkdtemp(prefix="errtest_")
    d = os.path.join(work, "error message")     # 資料夾名稱含空白,刻意測試
    t = datetime(2026, 8, 31, 16, 40, 3)
    rep = ErrorReport(out_dir=d, run_time=t, root=work)

    # 直接用真實紀錄檔裡的三個案例:嚴重(01709 交叉驗證未過)、
    # 一般(01705 找不到報表頁)、輕微(08021 只有科目未擷取/OCR頁)
    rep.scan_and_add(
        "[check] ⚠ 1/3 項交叉驗證未通過,請對照來源頁人手確認",
        filename="01709_DL_HOLDINGS_GP_20260730_extract.xlsx", stock="01709")
    rep.scan_and_add(
        '[financials] 找不到「綜合損益表」的頁面',
        filename="01705_B_S_INTL_HLDG_20260730_extract.xlsx", stock="01705")
    rep.scan_and_add(
        "[financials] 綜合損益表 未擷取: Revenue, Cost of Sales, Gross Profit, Operating Profit\n"
        "[financials] 資產負債表 未擷取: A, B, C, D, E\n"
        "[financials] 現金流量表 未擷取: F\n"
        "[pdf_reader] 完成。可能需要 OCR 的頁數: 5",
        filename="08021_WLS_HOLDINGS_20260828_extract.xlsx", stock="08021")
    rep.add("查無「major_transaction」類型文件 "
           "(可能原因:該區間內未刊發此類文件 / 代號有誤 / 網站暫時異常)",
           stock="00700", severity="medium")

    path = rep.save()
    ok(path is not None and os.path.exists(path), "檔案已產生", path)
    body = open(path, encoding="utf-8").read()

    ok("嚴重" in body and "一般" in body and "輕微" in body,
       "三個嚴重度區塊標題都在")
    idx_high = body.index("嚴重")
    idx_med = body.index("一般")
    idx_low = body.index("輕微")
    ok(idx_high < idx_med < idx_low, "順序是嚴重 → 一般 → 輕微")

    ok(body.index("01709") < idx_med, "01709(交叉驗證未過)在嚴重區塊裡")
    ok(idx_med < body.index("01705") < idx_low, "01705(找不到報表頁)在一般區塊裡")
    ok(idx_low < body.index("08021"), "08021(僅科目未擷取/OCR)在輕微區塊裡")

    ok(UNGENERATED not in body or "00700" in body, "沒有產生檔案的那筆有記到")
    ok("2026-08-31 16:40:03" in body, "每列都帶執行當刻時間")
    summary_line = body.splitlines()[2]
    ok("high:" in summary_line and "medium:" in summary_line and "low:" in summary_line,
       "頂部摘要列出各嚴重度筆數", summary_line)
    print("\n    ---- 檔案內容(節錄) ----")
    for line in body.splitlines()[:14]:
        print("    " + line)
    print("    ...")
    print("    ------------------------")
    shutil.rmtree(work, ignore_errors=True)


def test_no_problems_no_file():
    print("\n沒有問題就不該建檔")
    work = tempfile.mkdtemp(prefix="errtest_")
    d = os.path.join(work, "error message")
    rep = ErrorReport(out_dir=d, root=work)
    rep.scan_and_add(REAL_CLEAN, filename="output/x.xlsx", stock="00001")
    path = rep.save()
    ok(path is None, "save() 回傳 None")
    ok(not os.path.exists(d), "連資料夾都不會建立(避免堆滿空檔沒人看)")
    shutil.rmtree(work, ignore_errors=True)


def test_output_capture():
    print("\n輸出攔截:print 與 logging 都要收得到")
    log = logging.getLogger("financials")
    with OutputCapture() as cap:
        print("✓ 已輸出: output/x.xlsx")
        log.info("共擷取 0 個財務科目")
        log.warning("找不到「現金流量表」的頁面")
    text = cap.text()
    ok("已輸出" in text, "收到 print() 的輸出")
    ok("共擷取 0 個財務科目" in text, "收到 logging 的輸出")
    hits = scan_text(text)
    ok(len(hits) >= 2, "攔截到的文字可以直接拿來掃描", hits)


def test_capture_restores_stdout():
    print("\n攔截結束後必須還原 stdout 與 logger 等級")
    before = sys.stdout
    with OutputCapture():
        pass
    ok(sys.stdout is before, "正常結束後還原 stdout")

    before = sys.stdout
    try:
        with OutputCapture():
            raise RuntimeError("模擬分析中途丟例外")
    except RuntimeError:
        pass
    ok(sys.stdout is before, "丟例外時也要還原(否則後續輸出會全部消失)")

    root = logging.getLogger()
    lvl = root.level
    with OutputCapture():
        pass
    ok(root.level == lvl, "root logger 等級還原", f"{lvl} → {root.level}")
    ok(not any(getattr(h, "stream", None).__class__.__name__ == "StringIO"
               for h in root.handlers if hasattr(h, "stream")),
       "攔截用的 handler 已移除,不會累積")


def test_missing_tiers_are_omitted():
    print("\n只有輕微問題時,「嚴重」「一般」標題不該出現(不留空區塊)")
    work = tempfile.mkdtemp(prefix="errtest_")
    d = os.path.join(work, "error message")
    rep = ErrorReport(out_dir=d, root=work)
    rep.add("有 3 頁疑似掃描頁,需另接 OCR 才能處理",
           filename="x_extract.xlsx", stock="00001", severity="low")
    path = rep.save()
    body = open(path, encoding="utf-8").read()
    ok("輕微" in body, "輕微區塊有出現")
    ok("嚴重" not in body, "沒有嚴重問題時,「嚴重」標題不出現")
    ok("一般" not in body, "沒有一般問題時,「一般」標題不出現")
    shutil.rmtree(work, ignore_errors=True)


def test_default_severity_is_medium():
    print("\n沒指定嚴重度時預設「一般」(不自動歸為輕微而被忽略)")
    work = tempfile.mkdtemp(prefix="errtest_")
    rep = ErrorReport(out_dir=os.path.join(work, "error message"), root=work)
    rep.add("某個沒特別分類的狀況", filename="x.xlsx", stock="00001")
    ok(rep.entries[0]["severity"] == "medium", "預設值是 medium",
       rep.entries[0]["severity"])
    shutil.rmtree(work, ignore_errors=True)


def main():
    test_scan_real_output()
    test_scan_failing_checks()
    test_clean_output_produces_nothing()
    test_stock_from_name()
    test_file_written_and_format()
    test_missing_tiers_are_omitted()
    test_default_severity_is_medium()
    test_no_problems_no_file()
    test_output_capture()
    test_capture_restores_stdout()

    print(f"\n{'='*56}")
    print(f"通過 {len(PASS)} 項,失敗 {len(FAIL)} 項")
    if FAIL:
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("全部通過")


if __name__ == "__main__":
    main()
