# -*- coding: utf-8 -*-
"""
test_review_fixes.py — 覆核發現事項回歸測試

鎖住 2026-09-01 工作底稿覆核所修正的問題。每一項都是實際踩到的,
測試素材直接取自騰訊 2024 年報的原文排版 —— 不是自己編的字串。

    python3 test_review_fixes.py
"""
try:
    import console  # noqa: F401
except ImportError:
    pass

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanner  # noqa: E402

PASS, FAIL = [], []


def ok(cond, label, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'✓' if cond else '✗'} {label}" + (f"  {detail}" if detail else ""))


def test_range_separators():
    """
    P0-1:區間分隔符漏了 `~`,導致所有區間被截成單點值。
    騰訊 21 筆參數全部 Low = High,波幅 32%~82% 被記成 32% ——
    拿去做選擇權評價會嚴重低估。
    """
    print("P0-1 區間分隔符(漏一個符號,整個區間變單點)")
    cases = [
        ("2.55% ~ 3.52%", (2.55, 3.52)),
        ("32% ~ 82%", (32.0, 82.0)),
        ("0.04% ~ 6.64%", (0.04, 6.64)),
        ("38% ～ 39%", (38.0, 39.0)),      # 全形波浪號
        ("10.5% to 12.0%", (10.5, 12.0)),
        ("10.5% - 12.0%", (10.5, 12.0)),
        ("10.5% – 12.0%", (10.5, 12.0)),
        ("13.2%", (13.2, 13.2)),           # 單點必須維持 Low = High
    ]
    for txt, want in cases:
        got = scanner._match_percent(txt)
        pair = (got[0], got[1]) if got else (None, None)
        ok(pair == want, f"{txt} → {want[0]} ~ {want[1]}", f"實得 {pair}")


def test_change_column_rejected():
    """
    P1-5:MD&A 分部表格的年增率欄被當成毛利率。
    原文攤平後是「VAS 181,657 161,919 12% 57% 54%」,
    12% 是 change 欄。選擇剔除而非改抓第二個 —— 欄序在不同排版下
    不保證一致,猜錯就是把錯的數字寫進參數庫。
    """
    print("\nP1-5 年增率欄誤判為毛利率")
    reject = [
        " (RMB in millions, unless specified) VAS 181,657 161,919 12% 57% 54% Marketing",
        " (RMB in millions) VAS 44,157 37,090 19% 56% 54% Marketing Ser",
    ]
    for win in reject:
        raw = scanner._PCT_RE.search(win).group(0)
        ok(scanner._looks_like_change_column(win, raw),
           f"剔除 change 欄 {raw}")

    keep = [(" was 57% 54% compared with", "57%"),
            (" of 53% for the year", "53%"),
            (" rate 181,657 161,919 12% only", "12%")]
    for win, raw in keep:
        ok(not scanner._looks_like_change_column(win, raw),
           f"不誤殺正常數值 {raw}")


def test_backward_range_tail_rejected():
    """
    P0-2 的一部分:附註裡的觸發詞往回抓,撿到上年度比較欄的區間上限。
    「Expected volatility (Note) 38% ~ 39% 36% ~ 37% Note: The expected
    volatility, measured as...」→ 37% 被記成一筆獨立的當年度參數,
    同一頁同時出現 38~39 與 37,無法分辨年度。
    """
    print("\nP0-2 往回抓撿到上年度比較欄的區間上限")
    blocked = "Expected volatility (Note) 38% ~ 39% 36% ~ 37% Note: The "
    ok(scanner._match_percent_backward(blocked) is None,
       "區間上限不得被當成獨立點估計")

    for before, want in [
        ("...growth rate of 1.9%. This rate does not exceed the ", 1.9),
        ("discount rate was 13.2% applied to ", 13.2),
    ]:
        got = scanner._match_percent_backward(before)
        ok(got is not None and got[0] == want,
           f"正常往回抓仍有效 → {want}", got[0] if got else None)


def test_value_nature():
    """
    P1-7:「不超過 22%」被記成 Low = High = 22,讀來像單一確定假設。
    上限與採用值對估值師是兩件事。
    """
    print("\nP1-7 數值性質(上限 / 下限 / 區間 / 點估計)")
    cases = [
        ("a pre-tax discount rate of not more than ", "22%", False, "上限"),
        ("terminal growth rate of generally not more than ", "5%", False, "上限"),
        ("dividend yield of not less than ", "1.5%", False, "下限"),
        ("the discount rate applied was ", "13.2%", False, "點估計"),
        ("risk-free rate of ", "2.55% ~ 3.52%", True, "區間"),
        ("折現率不超過 ", "22%", False, "上限"),
    ]
    for before, win, rng, want in cases:
        got = scanner._value_nature(before, win, rng)
        ok(got == want, f"{before.strip()[-24:]!r} → {want}", got)


def test_identity_display_self_consistent():
    """
    P2-11:稅項存成負數時,顯示成「241,485 + 45,018 = 196,467」,
    字面不成立。工作底稿是給人讀的,算式必須自己對得起來。
    """
    print("\nP2-11 恆等式顯示式自洽")
    import financials
    from financials import FinResult, FinItem

    def mk(pbt, tax, pfy):
        res = FinResult()
        for name, val in (("Profit Before Tax", pbt),
                          ("Income Tax", tax),
                          ("Profit for the Year", pfy)):
            res.items.append(FinItem("Income Statement", name, val, None,
                                     1, "p.1", ""))
        return res

    # 稅項存負數(費用)
    line = [d for n, o, d in financials.integrity_checks(mk(241485, -45018, 196467))
            if "稅項" in n][0]
    ok("241,485 − 45,018 = 196,467" in line, "費用存負數時顯示減號", line)

    # 稅項存正數(費用寫成正數的年報)
    line2 = [d for n, o, d in financials.integrity_checks(mk(241485, 45018, 196467))
             if "稅項" in n][0]
    ok("−" in line2 and "196,467" in line2, "費用存正數時同樣顯示減號", line2)

    # 稅務抵免:結果比稅前大,應顯示加號
    line3 = [d for n, o, d in financials.integrity_checks(mk(1000, 255, 1255))
             if "稅項" in n][0]
    ok("1,000 + 255 = 1,255" in line3, "稅務抵免顯示加號", line3)


def test_review_queue_wording():
    """
    P0-4:待覆核清單原本寫「可能原因:該公司未單獨揭露此科目」。
    實測那四項在年報裡全都有揭露(R&D 70,686 在附註 7(b) 等)。
    錯誤的原因說明比漏抓更糟 —— 覆核者會據此不再翻原文。
    """
    print("\nP0-4 待覆核清單不得推測公司有無揭露")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "excel_out.py"), encoding="utf-8").read()
    ok("該公司未單獨揭露此科目" not in src,
       "已移除「公司未揭露」的推測性說法")
    ok("未定位,需人手確認" in src, "改為不推測的中性描述")
    ok("勿逕行認定未揭露" in src, "明確提醒不可據此認定未揭露")


def main():
    test_range_separators()
    test_change_column_rejected()
    test_backward_range_tail_rejected()
    test_value_nature()
    test_identity_display_self_consistent()
    test_review_queue_wording()

    print(f"\n{'=' * 56}")
    print(f"通過 {len(PASS)} 項,失敗 {len(FAIL)} 項")
    if FAIL:
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("全部通過")


if __name__ == "__main__":
    main()
