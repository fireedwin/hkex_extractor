# -*- coding: utf-8 -*-
"""
test_config_split.py — config.py / ops_config.py 分界回歸測試

分界只有一條線:
    改了它,同一份 PDF 產出的 Excel 內容會不會不一樣?
        會   → config.py     (改了就該讓既有結果失效、全部重跑)
        不會 → ops_config.py (改了不該波及任何一份已分析的年報)

這組測試鎖住三件事:
  1. 向下相容 —— 既有的 config.DOC_TYPES 等寫法不能斷
  2. 隔離有效 —— 改 ops_config.py 不會改變分析邏輯版本
  3. 安全沒破 —— 改 config.py 仍然會改變分析邏輯版本

第 3 項比前兩項更重要。拆檔案是為了少重跑,但如果拆過頭、把真正影響
萃取的設定放到不會觸發重跑的那一邊,使用者會拿到過期結果而毫無察覺 ——
那比每次都重跑嚴重得多。

    python3 test_config_split.py
"""
try:
    import console  # noqa: F401
except ImportError:
    pass

import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS, FAIL = [], []


def ok(cond, label, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'✓' if cond else '✗'} {label}" + (f"  {detail}" if detail else ""))


# 這些名稱在拆檔案之前就存在於 config,其他模組都是這樣取用的。
# 拆完之後一個都不能少,否則等於默默改了公開介面。
REEXPORTED = [
    "DOC_TYPES", "DEFAULT_DOC_TYPE", "ERROR_DIR",
    "ERROR_SEVERITY_ORDER", "ERROR_SEVERITY_LABELS", "ERROR_PATTERNS",
]
# 這些必須留在 config.py —— 每一項都會改變萃取結果
EXTRACTION_NAMES = [
    "TOPICS", "VALUATION_PARAMS", "PARAM_WINDOW", "FIN_STATEMENTS", "SETTINGS",
]


def test_backward_compatible():
    print("向下相容:既有的 config.<名稱> 寫法不能斷")
    import config
    import ops_config
    for name in REEXPORTED:
        ok(hasattr(config, name), f"config.{name} 仍取得到")
        if hasattr(config, name) and hasattr(ops_config, name):
            ok(getattr(config, name) is getattr(ops_config, name),
               f"config.{name} 與 ops_config.{name} 是同一物件(不會不同步)")


def test_extraction_settings_stay_in_config():
    print("\n影響萃取的設定必須留在 config.py")
    import config
    import ops_config
    for name in EXTRACTION_NAMES:
        ok(hasattr(config, name), f"config.{name} 存在")
        ok(not hasattr(ops_config, name),
           f"{name} 沒有被誤搬到 ops_config.py(搬過去就不會觸發重跑了)")


def _fake_project():
    """複製一份最小專案,用來實際計算分析邏輯版本。"""
    work = tempfile.mkdtemp(prefix="split_")
    for n in ("config.py", "ops_config.py", "incremental.py"):
        shutil.copy(os.path.join(HERE, n), work)
    for n in ("pdf_reader.py", "scanner.py", "financials.py",
              "excel_out.py", "ai_layer.py", "run.py",
              "hkexnews_selenium.py", "error_report.py"):
        with open(os.path.join(work, n), "w", encoding="utf-8") as f:
            f.write(f"# {n}\n")
    return work


def test_ops_config_does_not_invalidate():
    print("\n隔離:改 ops_config.py 不該改變分析邏輯版本")
    from incremental import compute_logic_version
    work = _fake_project()
    before, files = compute_logic_version(work)
    ok("ops_config.py" not in files,
       "ops_config.py 沒有被算進分析邏輯版本", files)

    with open(os.path.join(work, "ops_config.py"), "a", encoding="utf-8") as f:
        f.write('\n# 旺季調整:把估值參數 0 筆改列為 medium\n')
    after, _ = compute_logic_version(work)
    ok(after == before, "改了之後版本不變(幾百份年報不會白重跑)",
       f"{before} → {after}")
    shutil.rmtree(work, ignore_errors=True)


def test_config_still_invalidates():
    print("\n安全:改 config.py 仍然必須讓既有結果失效")
    from incremental import compute_logic_version
    work = _fake_project()
    before, files = compute_logic_version(work)
    ok("config.py" in files, "config.py 有被算進分析邏輯版本")

    with open(os.path.join(work, "config.py"), "a", encoding="utf-8") as f:
        f.write('\n# 新增科目別名 turnover\n')
    after, _ = compute_logic_version(work)
    ok(after != before, "改了之後版本必須改變(否則會給出過期擷取結果)",
       f"{before} → {after}")
    shutil.rmtree(work, ignore_errors=True)


def test_reexport_line_is_stable():
    """
    隔離之所以成立,是因為 config.py 只寫了一行 import,不隨
    ops_config.py 的內容改變。這裡直接驗證那個前提。
    """
    print("\n前提驗證:ops_config.py 改動不會連帶改到 config.py 的內容")
    work = _fake_project()
    cfg = os.path.join(work, "config.py")
    before = open(cfg, "rb").read()
    with open(os.path.join(work, "ops_config.py"), "a", encoding="utf-8") as f:
        f.write("\nERROR_DIR = '別的資料夾'\n")
    after = open(cfg, "rb").read()
    ok(before == after, "config.py 的位元組完全沒變")
    shutil.rmtree(work, ignore_errors=True)


def main():
    test_backward_compatible()
    test_extraction_settings_stay_in_config()
    test_ops_config_does_not_invalidate()
    test_config_still_invalidates()
    test_reexport_line_is_stable()

    print(f"\n{'='*56}")
    print(f"通過 {len(PASS)} 項,失敗 {len(FAIL)} 項")
    if FAIL:
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("全部通過")


if __name__ == "__main__":
    main()
