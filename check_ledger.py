# -*- coding: utf-8 -*-
"""
check_ledger.py — 增量處理帳本診斷

增量處理最大的風險不是慢,是「跳過了不該跳過的東西而沒人發現」。
所以要有工具讓人隨時查得到:現在的分析邏輯版本是什麼、哪些檔案被
記錄過、下次執行每一份會跑還是會跳、理由是什麼。

用法
----
    python3 check_ledger.py                    # 看帳本總覽
    python3 check_ledger.py downloads          # 逐份說明下次會跑還是跳
    python3 check_ledger.py --out output2      # 指定不同的輸出資料夾
"""
import console  # noqa: F401

import os
import sys
import glob
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from incremental import Ledger  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="增量處理帳本診斷")
    ap.add_argument("target", nargs="?", help="PDF 檔案或資料夾(不給則只看總覽)")
    ap.add_argument("--out", default="output", help="Excel 輸出資料夾")
    ap.add_argument("--ai", action="store_true", help="以「有 AI 層」的設定判斷")
    args = ap.parse_args()

    led = Ledger(out_dir=args.out)

    print("=" * 68)
    print(f"帳本位置    {led.path}")
    print(f"是否存在    {'是' if os.path.exists(led.path) else '否(尚未跑過)'}")
    print(f"邏輯版本    {led.logic_version}")
    print(f"納入計算    {len(led.logic_files)} 個模組:{', '.join(led.logic_files)}")
    print("=" * 68)

    entries = led.entries()
    print(f"已記錄 {len(entries)} 份文件,其中 {led.stale_count()} 份是舊邏輯版本產生的")
    if led.stale_count():
        print("→ 這些會在下次執行時自動重新分析(避免給出舊版擷取結果)")

    # 「為什麼突然全部重跑」要能直接查到答案,不用去翻程式碼
    ch = led.logic_changes()
    if ch and (ch.get("modified") or ch.get("added") or ch.get("removed")):
        print()
        print("自帳本上次存檔以來,以下模組有變動(這就是全部重跑的原因):")
        for label, key in (("已修改", "modified"), ("新增", "added"), ("移除", "removed")):
            for n in ch.get(key, []):
                print(f"    {label}  {n}")
        print("  若其中有不該影響萃取結果的檔案,把它加進 incremental.py 的")
        print("  _EXCLUDE_EXACT,以後改它就不會再觸發全量重跑。")
    elif ch:
        print("\n模組快照與帳本一致,沒有因為程式碼變動而需要重跑的情況。")
    print()

    if not args.target:
        for fp, e in sorted(entries.items(), key=lambda kv: kv[1]["file"]):
            stale = "" if e.get("logic_version") == led.logic_version else "  ⚠ 過期"
            ai = "  [AI]" if e.get("ai") else ""
            print(f"  {e['file']}")
            print(f"    指紋 {fp}  分析於 {e.get('analysed_at')}{ai}{stale}")
            for o in e.get("outputs", []):
                mark = "" if os.path.exists(led._abs(o)) else "  ← 檔案不見了"
                print(f"    → {o}{mark}")
        return

    # 逐份說明下次會怎麼處理
    t = args.target
    if os.path.isdir(t):
        pdfs = sorted(glob.glob(os.path.join(t, "*.pdf")))
    else:
        pdfs = sorted(glob.glob(t)) or [t]

    if not pdfs:
        print(f"找不到 PDF:{t}")
        sys.exit(1)

    todo, skipped = led.split(pdfs, use_ai=args.ai)
    print(f"下次執行 {len(pdfs)} 份 → 分析 {len(todo)} 份,跳過 {len(skipped)} 份")
    print(f"(指紋比對耗時 {led.stats['hash_seconds']*1000:.0f} ms)")
    print()
    for p in pdfs:
        mark = "○ 跳過" if p not in todo else "● 分析"
        print(f"  {mark}  {os.path.basename(p):<44} {led.reasons.get(p, '')}")


if __name__ == "__main__":
    main()
