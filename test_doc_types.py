# -*- coding: utf-8 -*-
"""
test_doc_types.py — 文件類型擴充的回歸測試

分兩塊:

1. 純資料/檔名邏輯 —— 可以完整、真實地驗證(不需要瀏覽器)。
2. 選單展開邏輯(set_document_type)—— 用假 DOM 驗證「路徑長度不同時
   程式該怎麼走」的控制流程是對的。

⚠ 誠實說明第 2 塊的極限:這裡驗證的是「給定假的網頁元素,程式的
hover/click 順序和文字比對邏輯正確」,**不是**「HKEXnews 真實頁面上
Circulars → Notifiable Transactions → Major Transaction 這條路徑真的
能展開」。跟 hkexnews_selenium.py 檔頭的警語一致:annual_report 那條
路徑是實測過的,其餘路徑目前只對照了畫面截圖上的文字,DOM 巢狀展開
的真實行為需要在有網路連線的本機用 --show-browser 肉眼驗證一次。
這個測試無法也不假裝能夠取代那一步。

用法
----
    python3 test_doc_types.py
"""
try:
    import console  # noqa: F401
except ImportError:
    pass

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from hkexnews_selenium import Filing, HKEXBrowser  # noqa: E402

PASS, FAIL = [], []


def ok(cond, label, detail=""):
    (PASS if cond else FAIL).append(label)
    mark = "✓" if cond else "✗"
    print(f"  {mark} {label}" + (f"  {detail}" if detail else ""))


# ──────────────────────────────────────────────────────────────
# 第一塊:config.DOC_TYPES 結構 + Filing 檔名邏輯
# ──────────────────────────────────────────────────────────────
def test_config_structure():
    print("config.DOC_TYPES 結構")
    ok("annual_report" in config.DOC_TYPES, "包含 annual_report(向下相容基準)")
    ok(config.DEFAULT_DOC_TYPE == "annual_report", "預設類型是 annual_report")
    for key, spec in config.DOC_TYPES.items():
        ok(isinstance(spec.get("path"), list) and len(spec["path"]) >= 2,
           f"{key}: path 至少兩層", spec.get("path"))
        ok("filename_tag" in spec, f"{key}: 有 filename_tag 欄位")
    tags = [v["filename_tag"] for k, v in config.DOC_TYPES.items() if k != "annual_report"]
    ok(all(tags) and len(tags) == len(set(tags)),
       "非年報類型的 filename_tag 皆非空且互不重複(避免撞檔名)", tags)


def test_filename_backward_compat():
    print("\nFiling 檔名:向下相容 + 撞檔名防護")
    f_old_style = Filing("00700", "TENCENT", "Annual Report", "08/04/2025",
                         "https://x/a.pdf")  # 不傳 doc_type,用 dataclass 預設值
    ok(f_old_style.doc_type == "annual_report", "doc_type 預設值仍是 annual_report")
    ok(f_old_style.local_filename() == "00700_TENCENT_20250408.pdf",
       "annual_report 檔名格式與擴充前完全一致(舊 downloads/ 資料夾不受影響)",
       f_old_style.local_filename())

    # 同一間公司、同一天,四種不同文件類型 —— 這是新增文件類型後
    # 真正會出現、而且原本設計完全沒防到的撞檔名情境
    same_day = [
        Filing("00700", "TENCENT", "t", "08/04/2025", "https://x/1.pdf", doc_type=dt)
        for dt in config.DOC_TYPES
    ]
    names = [f.local_filename() for f in same_day]
    ok(len(names) == len(set(names)),
       "同公司同日、不同文件類型,檔名彼此不同", names)


def test_unknown_doc_type_is_safe():
    print("\n未知的 doc_type 不會讓檔名產生器崩潰")
    f = Filing("00700", "TENCENT", "t", "08/04/2025", "https://x/1.pdf",
              doc_type="not_in_config_yet")
    try:
        name = f.local_filename()
        ok(True, "未知類型仍能產生檔名(退回不加 tag)", name)
    except Exception as e:
        ok(False, "未知類型不應該丟例外", str(e))


# ──────────────────────────────────────────────────────────────
# 第二塊:set_document_type 的路徑展開邏輯(假 DOM)
# ──────────────────────────────────────────────────────────────
class FakeElement:
    def __init__(self, text, displayed=True):
        self.text = text
        self._displayed = displayed

    def is_displayed(self):
        return self._displayed


def make_fake_browser(level1_labels, deeper_by_label):
    """
    造一個 HKEXBrowser,不連真實 Selenium driver,只用 MagicMock 記錄
    互動順序,並依照呼叫的 XPath/CSS 回傳對應的假元素。

    level1_labels   : 第一層(CATEGORY_LEVEL1_ITEM)可見的分類文字
    deeper_by_label  : dict,label -> 該 label hover 展開後可見的下一層元素文字清單
                       (最後一層 leaf 也放在這裡,值可以是空list)
    """
    b = HKEXBrowser.__new__(HKEXBrowser)   # 跳過 __init__,不需要真的開瀏覽器
    b.driver = MagicMock()
    b.wait = MagicMock()
    b.timeout = 5

    hovered = []   # 記錄實際 hover 過哪些 label,順序就是走過的路徑
    clicked = []

    def fake_find_elements(by, selector):
        from hkexnews_selenium import SELECTORS
        if selector == SELECTORS.CATEGORY_LEVEL1_ITEM:
            return [FakeElement(t) for t in level1_labels]
        # XPath 文字比對(新版是 //li[normalize-space(.)='X'] | //a[...] | ...)
        if "normalize-space(.)" in selector:
            # 目前展開到哪一層,由「最後一次 hover 的 label」決定
            current_scope = hovered[-1] if hovered else None
            available = deeper_by_label.get(current_scope, [])
            wanted = selector.split("'")[1]
            return [FakeElement(wanted)] if wanted in available else []

        return []

    b.driver.find_elements.side_effect = fake_find_elements
    b._wait_visible = MagicMock(return_value=FakeElement("dummy"))
    b._wait_clickable = MagicMock(return_value=FakeElement("dummy"))
    # 新版會在選完之後讀下拉欄位的文字來驗證真的選中了。
    # 假 DOM 這裡回報「最後點過的東西」,模擬選取成功的頁面狀態。
    b._selected_category_text = lambda: (clicked[-1] if clicked else "")
    b._visible_menu_labels = lambda limit=25: list(level1_labels)

    def fake_hover(el):
        hovered.append(el.text)

    def fake_click(el):
        clicked.append(el.text)

    b._hover = fake_hover
    b._js_click = fake_click
    b.wait.until = MagicMock(return_value=True)
    return b, hovered, clicked


def test_two_level_path():
    print("\n選單展開:兩層路徑(annual_report,已用真實下載驗證過的既有路徑)")
    b, hovered, clicked = make_fake_browser(
        level1_labels=["Announcements and Notices", "Circulars",
                       "Financial Statements/ESG Information"],
        deeper_by_label={
            "Financial Statements/ESG Information": ["Annual Report", "Interim/Half-Year Report"],
        },
    )
    b.set_document_type(["Financial Statements/ESG Information", "Annual Report"])
    ok(hovered == ["Financial Statements/ESG Information"],
       "只 hover 了中間那一層", hovered)
    ok(clicked[-1] == "Annual Report",
       "最後一次點擊的是目標葉節點(其餘點擊是展開下拉選單本身)", clicked[-1])


def test_three_level_path():
    print("\n選單展開:三層路徑(通函,尚待實機驗證的新路徑)")
    b, hovered, clicked = make_fake_browser(
        level1_labels=["Circulars", "Financial Statements/ESG Information"],
        deeper_by_label={
            "Circulars": ["Notifiable Transactions", "Connected Transaction"],
            "Notifiable Transactions": ["Major Transaction", "Very Substantial Acquisition",
                                       "Very Substantial Disposal", "Reverse Takeover"],
        },
    )
    b.set_document_type(["Circulars", "Notifiable Transactions", "Major Transaction"])
    ok(hovered == ["Circulars", "Notifiable Transactions"],
       "依序 hover 展開中間兩層", hovered)
    ok(clicked[-1] == "Major Transaction",
       "最後一次點擊的是真正要的通函類型", clicked[-1])


def test_missing_intermediate_level_does_not_crash():
    print("\n選單展開:中間層在假 DOM 裡找不到(模擬選單改版)")
    b, hovered, clicked = make_fake_browser(
        level1_labels=["Circulars"],
        deeper_by_label={"Circulars": []},   # Notifiable Transactions 不存在
    )
    try:
        b.set_document_type(["Circulars", "Notifiable Transactions", "Major Transaction"])
        ok("Major Transaction" not in clicked and "Notifiable Transactions" not in hovered,
           "找不到中間層時,不會誤點/誤展開任何一層",
           f"hovered={hovered} clicked={clicked}")
    except Exception as e:
        ok(False, "不該丟未捕捉的例外(該記錄錯誤然後 return)", str(e))


def test_all_config_paths_are_walkable():
    """
    把 config.DOC_TYPES 裡每一條路徑都在假 DOM 上完整跑一次,
    確保「路徑本身的控制流程」不會卡住 —— 不代表真實頁面也一定通。
    """
    print("\nconfig.DOC_TYPES 裡的每一條路徑,控制流程都能走完")
    for key, spec in config.DOC_TYPES.items():
        path = spec["path"]
        level1_labels = [path[0]]
        deeper = {}
        for i in range(len(path) - 1):
            deeper[path[i]] = [path[i + 1]]
        b, hovered, clicked = make_fake_browser(level1_labels, deeper)
        b.set_document_type(path)
        ok(clicked[-1] == path[-1], f"{key}: 走到底並點擊「{path[-1]}」", clicked[-1])


def test_returns_bool():
    print("\nset_document_type 回傳成功與否(呼叫端要靠它決定要不要中止)")
    b, hovered, clicked = make_fake_browser(
        level1_labels=["Circulars"],
        deeper_by_label={"Circulars": ["Notifiable Transactions"],
                         "Notifiable Transactions": ["Major Transaction"]},
    )
    r = b.set_document_type(["Circulars", "Notifiable Transactions", "Major Transaction"])
    ok(r is True, "成功時回傳 True", r)

    b2, _, _ = make_fake_browser(level1_labels=["Circulars"],
                                 deeper_by_label={"Circulars": []})
    r2 = b2.set_document_type(["Circulars", "Notifiable Transactions", "Major Transaction"])
    ok(r2 is False, "失敗時回傳 False", r2)

    b3, _, _ = make_fake_browser(level1_labels=["Announcements and Notices"],
                                 deeper_by_label={})
    r3 = b3.set_document_type(["Circulars", "Notifiable Transactions", "Major Transaction"])
    ok(r3 is False, "第一層就找不到時也回傳 False", r3)


def test_failed_doc_type_aborts_search():
    """
    這是整組測試裡最重要的一項。

    實測踩到的坑:選單沒展開成功時,舊版程式照樣按下 SEARCH,
    HKEXnews 就用「ALL」查詢 —— 回傳 100 筆全類型公告,而且被標記成
    使用者指定的 major_transaction、用 _MT_ 檔名存檔。畫面上完全看不出
    有問題,筆數還特別多。這正是這個專案一路在防的「安靜的失敗」。

    正確行為:文件類型設定失敗 → 完全不搜尋、不讀結果、回報 0 筆。
    """
    print("\n文件類型設定失敗時,絕不能回傳「全部類型」的結果")
    from unittest.mock import MagicMock as MM
    from hkexnews_selenium import HKEXBrowser as HB

    b = HB.__new__(HB)
    b.driver = MM()
    b.wait = MM()
    calls = []

    b.open_search_page = lambda: calls.append("open")
    b.set_stock_code = lambda c: True
    b.set_document_type = lambda p: calls.append("doctype") or False   # 永遠失敗
    b.set_date_range = lambda a, c: calls.append("date")
    b.click_search = lambda: calls.append("SEARCH")
    b.read_current_page = lambda doc_type="annual_report": (
        calls.append("read") or [object()])
    b.has_next_page = lambda: False

    res = b.search_all_pages("00700", "20250101", "20251231",
                             doc_type="major_transaction")
    ok(res == [], "回傳空清單,而不是一堆錯標類型的結果", res)
    ok("SEARCH" not in calls, "沒有按下 SEARCH")
    ok("read" not in calls, "沒有讀取任何結果列")
    ok(calls.count("doctype") == 2, "有重試一次才放棄", calls.count("doctype"))


def test_xpath_literal_handles_awkward_text():
    print("\nXPath 字面值:含逗號/斜線/單引號的選項名稱不會產生壞掉的 XPath")
    from hkexnews_selenium import HKEXBrowser as HB
    plain = HB._xpath_literal("Major Transaction")
    ok(plain == "'Major Transaction'", "一般文字直接加引號", plain)
    comma = HB._xpath_literal("Environmental, Social and Governance Information/Report")
    ok(comma.startswith("'") and comma.endswith("'"),
       "逗號與斜線不需特殊處理", comma[:40] + "...")
    quoted = HB._xpath_literal("Director's Report")
    ok("concat(" in quoted, "含單引號時改用 concat() 組出來", quoted)


def main():
    test_config_structure()
    test_filename_backward_compat()
    test_unknown_doc_type_is_safe()
    test_two_level_path()
    test_three_level_path()
    test_missing_intermediate_level_does_not_crash()
    test_all_config_paths_are_walkable()
    test_returns_bool()
    test_failed_doc_type_aborts_search()
    test_xpath_literal_handles_awkward_text()

    print(f"\n{'='*56}")
    print(f"通過 {len(PASS)} 項,失敗 {len(FAIL)} 項")
    if FAIL:
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("全部通過")
    print()
    print("提醒:annual_report 以外的路徑尚未在真實 HKEXnews 頁面上驗證過,")
    print("第一次使用新的 --type 之前,請先用 --show-browser 肉眼確認一次。")


if __name__ == "__main__":
    main()
