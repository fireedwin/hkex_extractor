# -*- coding: utf-8 -*-
"""
check_menu.py — HKEXnews 文件類型選單診斷

為什麼需要這支程式:
    「找不到 Major Transaction」有兩種可能 —— 文字對不上(例如網站寫的
    其實是別的字),或是選單根本沒展開。兩者的錯誤訊息一樣,但處理方式
    完全不同。這支工具會實際打開瀏覽器,一層一層印出**真實頁面上看得到
    的選項文字**,讓你直接對照 config.DOC_TYPES 裡寫的字串。

    這是唯一能取代「猜」的方法。hkexnews.py 當年就是敗在猜參數,
    所以這次寧可多做一支診斷工具。

用法
----
    # 診斷單一類型(預設會顯示瀏覽器,方便肉眼看)
    python3 check_menu.py --type major_transaction

    # 只列出第一層有哪些分類
    python3 check_menu.py --list-top

    # 診斷全部已設定的類型
    python3 check_menu.py --all

    # 不顯示瀏覽器視窗(通常不建議,看不到就失去意義)
    python3 check_menu.py --type major_transaction --headless
"""
try:
    import console  # noqa: F401
except ImportError:
    pass

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from hkexnews_selenium import HKEXBrowser, SELECTORS  # noqa: E402


def dump_level1(browser):
    """印出第二段下拉裡的第一層分類。"""
    from selenium.webdriver.common.by import By
    items = [e for e in browser.driver.find_elements(
        By.CSS_SELECTOR, SELECTORS.CATEGORY_LEVEL1_ITEM) if e.is_displayed()]
    print(f"\n  第一層分類({len(items)} 項):")
    for e in items:
        print(f"    · {(e.text or '').strip()[:60]!r}")
    return items


def walk(browser, path, label=""):
    """
    照 path 一層一層走,每層印出「展開後看得到什麼」。
    不做選取,只做觀察 —— 目的是拿到可以貼回 config.py 的正確文字。
    """
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    print(f"\n{'='*66}")
    print(f"診斷路徑{(' ['+label+']') if label else ''}: {' → '.join(path)}")
    print("=" * 66)

    browser.open_search_page()

    # 前兩步跟文件類型無關
    browser._js_click(browser._wait_visible(SELECTORS.TIER1_FIELD))
    time.sleep(1.0)
    try:
        opt = browser.driver.find_element(
            By.CSS_SELECTOR, SELECTORS.TIER1_OPTION_HEADLINE_CATEGORY)
        browser._js_click(opt)
        print("  ✓ 已切到 Headline Category 模式")
        time.sleep(1.2)
    except Exception as e:
        print(f"  ✗ 切換 Headline Category 失敗: {e}")
        return False

    try:
        browser.wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, SELECTORS.CATEGORY_GROUP)))
    except Exception:
        print("  ⚠ #rbAfter2006 沒有如預期顯示")

    browser._js_click(browser._wait_visible(SELECTORS.CATEGORY_FIELD))
    time.sleep(1.2)

    level1 = dump_level1(browser)
    head = path[0].split("/")[0].strip().lower()
    current = [e for e in level1 if head in (e.text or "").strip().lower()]
    if not current:
        print(f"\n  ✗ 第一層找不到「{path[0]}」")
        print("  → 請從上面那份清單挑正確的文字,改到 config.DOC_TYPES")
        return False
    print(f"  ✓ 第一層命中「{path[0]}」({len(current)} 個候選元素)")

    for depth in range(1, len(path)):
        target = path[depth]
        okay, items = browser._expand_to(current, target)
        if okay:
            print(f"  ✓ 第 {depth+1} 層找到「{target}」({len(items)} 個候選元素)")
            current = items
            continue

        print(f"\n  ✗ 第 {depth+1} 層找不到「{target}」")
        print(f"  展開「{path[depth-1]}」之後,畫面上看得到的項目:")
        for t in browser._visible_menu_labels(limit=40):
            print(f"    · {t!r}")
        print("\n  → 對照上面的清單,把 config.DOC_TYPES 裡的文字改成一模一樣")
        return False

    print(f"\n  ✓ 整條路徑都走得通:{' → '.join(path)}")
    print("    (這代表選單能展開;實際查詢結果仍請用 --show-browser 跑一次確認)")
    return True


def main():
    ap = argparse.ArgumentParser(description="HKEXnews 文件類型選單診斷")
    ap.add_argument("--type", dest="doc_type",
                    choices=list(config.DOC_TYPES.keys()),
                    help="要診斷的文件類型")
    ap.add_argument("--all", action="store_true", help="診斷 config 裡全部類型")
    ap.add_argument("--list-top", action="store_true", help="只列出第一層分類")
    ap.add_argument("--headless", action="store_true",
                    help="不顯示瀏覽器(不建議,看不到過程就失去診斷意義)")
    args = ap.parse_args()

    if not (args.doc_type or args.all or args.list_top):
        ap.error("請指定 --type / --all / --list-top 其中之一")

    results = {}
    with HKEXBrowser(headless=args.headless) as browser:
        if args.list_top:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            browser.open_search_page()
            browser._js_click(browser._wait_visible(SELECTORS.TIER1_FIELD))
            time.sleep(1.0)
            browser._js_click(browser.driver.find_element(
                By.CSS_SELECTOR, SELECTORS.TIER1_OPTION_HEADLINE_CATEGORY))
            time.sleep(1.2)
            try:
                browser.wait.until(EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, SELECTORS.CATEGORY_GROUP)))
            except Exception:
                pass
            browser._js_click(browser._wait_visible(SELECTORS.CATEGORY_FIELD))
            time.sleep(1.2)
            dump_level1(browser)
            return

        targets = list(config.DOC_TYPES) if args.all else [args.doc_type]
        for key in targets:
            results[key] = walk(browser, config.DOC_TYPES[key]["path"], label=key)

    print(f"\n{'='*66}")
    print("診斷結果")
    print("=" * 66)
    for k, v in results.items():
        print(f"  {'✓ 可展開' if v else '✗ 需校正'}  {k}")
    if not all(results.values()):
        print("\n把上面印出的實際選項文字,貼回 config.DOC_TYPES 對應的 path 即可。")
        sys.exit(1)


if __name__ == "__main__":
    main()
