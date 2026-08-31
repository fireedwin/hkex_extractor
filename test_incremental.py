# -*- coding: utf-8 -*-
"""
test_incremental.py — 增量處理(路線三)回歸測試

用真實年報 PDF 驗證六種情境。每一條都是「跳過不該跳過的檔案」
可能出錯的地方,鎖住之後才敢在正式工作裡開增量。

    python3 test_incremental.py [PDF資料夾]
"""
try:                      # 修正 Windows 主控台 cp950 編碼(✓ ✗ 會爆掉)
    import console        # noqa: F401
except ImportError:
    pass

import os
import sys
import glob
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from incremental import Ledger, compute_logic_version, file_fingerprint  # noqa: E402

PASS, FAIL = [], []


def ok(cond, label, detail=""):
    (PASS if cond else FAIL).append(label)
    mark = "✓" if cond else "✗"
    print(f"  {mark} {label}" + (f"  {detail}" if detail else ""))


def fake_output(out_dir, pdf):
    """假造一個 Excel 輸出檔,模擬 process_one 的產物。"""
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, os.path.splitext(os.path.basename(pdf))[0] + "_extract.xlsx")
    with open(p, "w") as f:
        f.write("dummy")
    return p


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads"
    pdfs = sorted(glob.glob(os.path.join(src, "*.pdf")))
    if not pdfs:
        print(f"找不到 PDF:{src}")
        sys.exit(1)

    work = tempfile.mkdtemp(prefix="ledger_test_")
    root = os.path.join(work, "proj")
    out_dir = os.path.join(root, "output")
    dl_dir = os.path.join(root, "downloads")
    os.makedirs(out_dir); os.makedirs(dl_dir)

    # 複製專案原始碼(邏輯版本要算得到)與 PDF
    here = os.path.dirname(os.path.abspath(__file__))
    for n in ("config.py", "incremental.py"):
        shutil.copy(os.path.join(here, n), root)
    # 造出專案裡其他模組的替身,才測得出「哪些該算進邏輯版本、哪些不該」。
    # 內容不重要,重要的是檔名 —— 排除規則是按檔名判斷的。
    for n in ("pdf_reader.py", "scanner.py", "financials.py", "excel_out.py",
              "ai_layer.py", "run.py",                    # 參與萃取,該納入
              "hkexnews_selenium.py", "batch_download.py",  # 只負責下載,不該納入
              "error_report.py",                            # 只負責記錄,不該納入
              "console.py", "pipeline.py"):                 # 既有排除項
        with open(os.path.join(root, n), "w", encoding="utf-8") as f:
            f.write(f"# {n}\n")
    local = []
    for p in pdfs:
        d = os.path.join(dl_dir, os.path.basename(p))
        shutil.copy(p, d)
        local.append(d)
    print(f"測試樣本:{len(local)} 份年報\n")

    # ── 情境 1:第一次跑 — 全部都要分析 ──────────────────
    print("情境 1:第一次執行")
    led = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led.split(local)
    ok(len(todo) == len(local) and not skipped,
       "全部視為新檔案", f"待分析 {len(todo)}/{len(local)}")
    outs = {}
    for p in todo:
        outs[p] = fake_output(out_dir, p)
        led.record(p, outs[p])
    ok(os.path.exists(led.path), "帳本已寫入", os.path.basename(led.path))

    # ── 情境 2:立刻重跑 — 全部跳過 ────────────────────
    print("\n情境 2:內容與邏輯都沒變,立刻重跑")
    led2 = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led2.split(local)
    ok(not todo and len(skipped) == len(local),
       "全部正確跳過", f"跳過 {len(skipped)}/{len(local)}")
    ok(all(r == "已分析過" for _, r, _ in skipped), "跳過原因正確")
    ok(all(os.path.exists(o) for _, _, os_ in skipped for o in os_),
       "回報的既有輸出路徑存在")

    # ── 情境 3:改了 config.py — 必須全部重跑 ──────────
    print("\n情境 3:擴充 config.py 別名(這是本專案最常發生的事)")
    v_before, files = compute_logic_version(root)
    with open(os.path.join(root, "config.py"), "a", encoding="utf-8") as f:
        f.write('\n# 新增別名 "turnover"\n')
    v_after, _ = compute_logic_version(root)
    ok(v_before != v_after, "邏輯版本隨 config.py 改變",
       f"{v_before} → {v_after}")
    led3 = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led3.split(local)
    ok(len(todo) == len(local) and not skipped,
       "全部強制重新分析(不會給出舊科目數的結果)")
    ok(led3.stale_count() == len(local), "帳本能算出過期筆數",
       f"{led3.stale_count()} 筆")
    for p in todo:
        led3.record(p, outs[p])

    # ── 情境 4:輸出 Excel 被刪掉 — 只重跑那一份 ────────
    print("\n情境 4:使用者手動刪掉其中一份 Excel")
    victim = local[0]
    os.remove(outs[victim])
    led4 = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led4.split(local)
    ok(todo == [victim], "只有遺失輸出的那一份要重跑",
       f"待分析 {[os.path.basename(t) for t in todo]}")
    ok(len(skipped) == len(local) - 1, "其餘維持跳過")
    fake_output(out_dir, victim)
    led4.record(victim, outs[victim])

    # ── 情境 5:PDF 內容被換掉(公司重新提交修訂版)────
    print("\n情境 5:同檔名但內容改變(修訂版年報)")
    target = local[1]
    fp_old = file_fingerprint(target)
    with open(target, "ab") as f:
        f.write(b"%%revised\n")
    fp_new = file_fingerprint(target)
    ok(fp_old != fp_new, "指紋隨內容改變", f"{fp_old} → {fp_new}")
    led5 = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led5.split(local)
    ok(target in todo, "修訂版被抓出來重新分析")
    ok(len(todo) == 1, "沒有波及其他文件")

    # ── 情境 6:同一份年報下載兩次(檔名不同)──────────
    print("\n情境 6:同內容不同檔名(重複下載)")
    dup = os.path.join(dl_dir, "DUPLICATE_" + os.path.basename(local[2]))
    shutil.copy(local[2], dup)
    led6 = Ledger(out_dir=out_dir, root=root)
    can_skip, reason, _ = led6.check(dup)
    ok(can_skip and "相同" in reason, "辨識為重複檔案並跳過", reason)

    # ── 情境 7:帳本毀損 — 不能讓 pipeline 停擺 ─────────
    print("\n情境 7:帳本檔毀損")
    with open(os.path.join(out_dir, ".analysis_ledger.json"), "w") as f:
        f.write("{ this is not valid json")
    led7 = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led7.split(local)
    ok(len(todo) == len(local) and not skipped,
       "退回全部重跑,不丟例外(最壞情況=沒有增量,不會給錯結果)")

    # ── 情境 8:AI 開關不同 ─────────────────────────────
    print("\n情境 8:--ai 開關改變")
    led8 = Ledger(out_dir=out_dir, root=root)
    led8.clear()
    for p in local:
        led8.record(p, outs.get(p, fake_output(out_dir, p)), use_ai=False)
    todo_ai, skip_ai = led8.split(local, use_ai=True)
    ok(len(todo_ai) == len(local), "無 AI 的舊結果不會被當成有 AI 的結果")
    ok(all("AI" in led8.check(p, use_ai=True)[1] for p in local),
       "重跑原因明確指出是 AI 設定不同",
       led8.check(local[0], use_ai=True)[1])
    todo_no, skip_no = led8.split(local, use_ai=False)
    ok(not todo_no, "同樣設定則正常跳過")

    # ── 效能:雜湊成本 ────────────────────────────────
    print("\n效能:指紋計算成本")
    led9 = Ledger(out_dir=out_dir, root=root)
    led9.split(local)
    total_mb = sum(os.path.getsize(p) for p in local) / 1024 / 1024
    sec = led9.stats["hash_seconds"]
    print(f"  {len(local)} 份 / {total_mb:.1f} MB → {sec*1000:.0f} ms "
          f"({total_mb/sec:.0f} MB/s)")
    print(f"  推算 200 份(平均 5 MB)約 {1000/ (total_mb/sec):.1f} 秒")

    # ── 情境 9:哪些模組該/不該觸發全量重跑 ──────────────
    print("\n情境 9:只有「會改變萃取結果」的模組才該讓帳本失效")
    led9 = Ledger(out_dir=out_dir, root=root)
    led9.clear()
    for p in local:
        led9.record(p, outs.get(p, fake_output(out_dir, p)))
    base_v = led9.logic_version

    # 不該觸發:下載層與錯誤紀錄層 —— 帳本用 PDF 內容雜湊當 key,
    # 「這份 PDF 怎麼來的」「錯誤怎麼記」都不影響它的萃取結果
    for name in ("hkexnews_selenium.py", "batch_download.py", "error_report.py"):
        with open(os.path.join(root, name), "a", encoding="utf-8") as f:
            f.write(f"\n# 改一行 {name}\n")
    v_after, _ = compute_logic_version(root)
    ok(v_after == base_v,
       "改下載層/錯誤紀錄層,邏輯版本不變(不會白白重跑幾百份)",
       f"{base_v} → {v_after}")
    led9b = Ledger(out_dir=out_dir, root=root)
    todo, skipped = led9b.split(local)
    ok(not todo, "→ 所有文件仍正常跳過", f"待分析 {len(todo)}")

    # 該觸發:任何參與萃取的模組
    for name in ("config.py", "financials.py", "scanner.py", "pdf_reader.py"):
        before, _ = compute_logic_version(root)
        with open(os.path.join(root, name), "a", encoding="utf-8") as f:
            f.write(f"\n# 改一行 {name}\n")
        after, _ = compute_logic_version(root)
        ok(after != before, f"改 {name},邏輯版本必須改變(否則會給出過期結果)")

    # ── 情境 10:要能指出是「哪個檔案」變了 ────────────────
    print("\n情境 10:全部重跑時要說得出兇手是哪個模組")
    led10 = Ledger(out_dir=out_dir, root=root)
    led10.clear()
    for p in local:
        led10.record(p, outs.get(p, fake_output(out_dir, p)))
    with open(os.path.join(root, "financials.py"), "a", encoding="utf-8") as f:
        f.write("\n# 修正稅務抵免判斷\n")
    led10b = Ledger(out_dir=out_dir, root=root)
    ch = led10b.logic_changes()
    ok("financials.py" in ch.get("modified", []),
       "指出 financials.py 被修改", ch.get("modified"))
    ok("config.py" not in ch.get("modified", []),
       "沒有把沒動過的檔案也算進去", ch.get("modified"))

    # 新增一個分析模組也要看得出來(而且必須觸發重跑)
    with open(os.path.join(root, "new_analysis_step.py"), "w", encoding="utf-8") as f:
        f.write("# 將來新增的分析模組\n")
    led10c = Ledger(out_dir=out_dir, root=root)
    ok("new_analysis_step.py" in led10c.logic_changes().get("added", []),
       "新增的分析模組會被偵測為 added(白名單排除的安全性沒有被破壞)")
    todo10, _ = led10c.split(local)
    ok(len(todo10) == len(local), "→ 而且確實觸發全部重新分析")
    os.remove(os.path.join(root, "new_analysis_step.py"))

    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'='*56}")
    print(f"通過 {len(PASS)} 項,失敗 {len(FAIL)} 項")
    if FAIL:
        for f_ in FAIL:
            print("  ✗", f_)
        sys.exit(1)
    print("全部通過")


if __name__ == "__main__":
    main()
