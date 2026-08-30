# 使用教學 — HKEX Document Extractor

這份教學假設你完全沒碰過這個程式,從零開始一步步操作。

---

## 第 0 步:確認環境

需要 Python 3.9 以上。終端機輸入:

```bash
python3 --version
```

看到 `Python 3.9.x` 或更高就沒問題。

**Windows 注意**:如果 `python3` 沒反應,改用 `py`。而且**安裝套件和執行程式
要用同一個指令開頭**,否則會出現「明明裝了卻說找不到模組」:

```bash
py -m pip install -r requirements.txt
py run.py --pdf sample_annual_report.pdf
```

---

## 第 1 步:安裝套件

把 `hkex_extractor` 資料夾整個下載到電腦上(例如放桌面),然後:

```bash
cd Desktop/hkex_extractor
python3 -m pip install -r requirements.txt
```

用 `python3 -m pip` 而不是直接 `pip`,可以確保裝到正在用的那個 Python。

**下載功能另外需要 Google Chrome**(不是 Edge)。只做分析的話不用裝。

---

## 第 2 步:先跑一次測試,確認一切正常

不用自己找 PDF,程式內建產生模擬年報的腳本:

```bash
python3 make_sample_pdf.py
python3 run.py --pdf sample_annual_report.pdf
```

終端機會即時顯示處理過程:

```
====================================================================
處理: sample_annual_report.pdf
====================================================================
[pdf_reader] 開啟 sample_annual_report.pdf,共 12 頁 (引擎: PyMuPDF)
[pdf_reader] 完成。可能需要 OCR 的頁數: 1
[scanner] 主題段落 14 筆;估值參數 10 筆
[scanner] 高優先頁面 6 頁 / 全份 12 頁 = 縮減至 50.0%
[financials] 綜合損益表: PDF p.6 (年度欄 2024 / 2023)
[financials] 共擷取 28 個財務科目
[check] ✓ 5 項會計恆等式交叉驗證全部通過

✓ 已輸出: output/sample_annual_report_extract.xlsx
```

兩個地方要看:

- 最後的 `✓ 已輸出` — 代表成功
- `[check] ✓ ...交叉驗證全部通過` — 代表**抓到的數字彼此對得上**

---

## 第 3 步:看懂 Excel 輸出

打開 `output/sample_annual_report_extract.xlsx`,下方七個分頁:

| 分頁 | 你會看到什麼 |
|---|---|
| **Summary 摘要** | 統計數字 + **會計恆等式驗證結果** + 方法論 |
| **Valuation Params 估值參數** | 折現率、WACC 等,附信心度和來源頁 |
| **Financials 財務數據** | 三大報表科目,本年 vs 上年,**附原文行** |
| **Ratios 財務比率** | 毛利率、流動比率等,以公式連結 |
| **Chart 趨勢圖** | 主要科目柱狀圖 |
| **Extracts 主題段落** | 無形資產、ESG 等段落原文 |
| **Review Queue 待覆核** | **沒抓到的科目** + 疑似掃描頁 |

**最重要的兩欄:**

- **來源頁** — 每筆資料都能照頁碼翻回原始 PDF 核對
- **原文行** — 直接顯示那一行原文長什麼樣,不用翻 PDF 就能初步判斷對不對

「待覆核」分頁也要看 —— 沒抓到的科目會列在那裡,不會靜靜消失。

---

## 第 4 步:處理你自己的 PDF

```bash
# 單一檔案
python3 run.py --pdf 你的檔案.pdf

# 完整路徑
python3 run.py --pdf C:\Users\你\Downloads\某公司2024年報.pdf
```

**一次處理多份**,用 `pipeline.py`:

```bash
# 1) 直接給資料夾,裡面所有 PDF 都會處理(旺季批次最常用)
python3 pipeline.py --pdf downloads

# 2) 連子資料夾一起掃
python3 pipeline.py --pdf downloads --recursive

# 3) 逐一指定,或用萬用字元
python3 pipeline.py --pdf 公司A.pdf --pdf 公司B.pdf
python3 pipeline.py --pdf "downloads/007*.pdf"
```

萬用字元**要加引號** —— Windows 的 cmd 不會自己展開 `*`,必須由程式處理。
重複指定同一個檔案不會被處理兩次。

批次處理結束時,失敗的檔案會單獨再列一次,不會被大量正常輸出淹沒。

---

## 第 5 步:從 HKEXnews 下載

**下載一律用 `pipeline.py`,不是 `run.py`。**

```bash
# 指定公司(最常用,也最穩定)
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231

# 多間公司
python3 pipeline.py --stocks 00700,00731,00673 --from 20250101 --to 20251231

# 顯示瀏覽器視窗(除錯用,可以看到它在做什麼)
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --show-browser

# 全市場(資料量大,對網站負擔重,不建議面試現場示範)
python3 pipeline.py --all-market --from 20250301 --to 20250430
```

幾個實務重點:

- **日期不能超過今天**,否則 HKEXnews 會跳出警告視窗導致失敗
- 指定股票代號時,查詢區間上限約 366 天;不指定(全市場)時只有 30 天,
  程式會自動把長區間切成多段
- 查無結果的公司會在最後列出來,提醒你人手確認
- 已下載過的檔案會自動略過,不會重複下載

**`run.py` 不再支援 `--from/--to/--stock`。** 舊的 `hkexnews.py` 假設
HKEXnews 有公開 API,實測證實沒有 —— 它會「查到 1 筆」但欄位全空且不報錯。
現在用 `run.py` 下載會直接顯示改用 `pipeline.py` 的指令。

---

## 第 6 步(選用):啟用 AI 語意層

不是必要的,沒開也能拿到完整的財務數據和估值參數。AI 層額外幫你判斷
「這個折現率是用在哪裡」這類需要理解上下文的問題。

1. 到 https://console.anthropic.com 申請 API key
2. 設定環境變數:

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-你的金鑰

# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-你的金鑰"
```

3. 加上 `--ai`:

```bash
python3 pipeline.py --pdf downloads --ai
```

Excel 會多一個 **AI Review AI複核** 分頁。

**注意**:會消耗 API 額度(付費)。忘記設定 key 不會出錯,程式只會印一行
提示然後跳過這層,其他分頁照常輸出。

---

## 常見問題

**Q: 明明 pip install 成功了,執行卻說找不到模組?**
A: Windows 上常見,原因是 `pip` 和 `python3` 指到不同的 Python。改用
`py -m pip install ...` 和 `py run.py ...`,前後用同一個指令開頭。

**Q: 改了程式碼卻沒生效?**
A: 跑 `python3 check_files.py`。它會找出重複的檔案副本(例如子資料夾裡
還留著舊版),並檢查每個檔案是不是最新版。

**Q: 財務數據那頁是空的?**
A: 看 Summary 分頁的「需人手/OCR 頁數」。如果接近總頁數,代表這份是掃描檔
(圖片型 PDF),本工具無法處理,需要另接 OCR。

**Q: 某些科目沒抓到?**
A: 先看「待覆核」分頁列出的清單。有兩種可能:
- **公司真的沒揭露** — 例如沒有商譽、沒有投資物業,或該科目在附註而非報表表面
- **措辭沒對上** — 到 `config.py` 的 `FIN_STATEMENTS` 補一個別名即可

用 `python3 diagnose_params.py 你的檔案.pdf --page 頁碼` 可以直接印出某頁原文,
確認實際寫法。

**Q: Excel 顯示 `#NAME?` 或 `#N/A`?**
A: 兩者意義不同:
- `#N/A` — 該科目沒抓到,公式找不到對應項目(真的缺料)
- `#NAME?` — 試算表軟體不認得公式裡的函式。工具已改用最古老相容的
  `ISERROR` 寫法,並把計算結果一起寫進檔案,正常不會再出現

**Q: 估值參數抓到不相關的東西?**
A: 跑 `python3 diagnose_params.py 你的檔案.pdf`,它會告訴你是「文件裡真的
沒有」還是「有但格式沒對上」,並印出原文供判斷。調整範圍在 `config.py` 的
`VALUATION_PARAMS` 和 `scanner.py` 的 `_plausible`。

---

## 面試現場 demo 建議(3-5 分鐘)

1. **先跑批次**:`python3 pipeline.py --pdf downloads`
   讓面試官看到即時處理過程 —— 逐頁掃描、縮減比例、擷取筆數、
   以及最後的 `[check] ✓ 會計恆等式交叉驗證全部通過`
2. **打開 Excel,先開 Valuation Params 分頁** —— 對估值行最直接有價值
3. **秀「原文行」和「來源頁」** —— 說明每個數字都能三秒鐘核對回原文
4. **翻到「待覆核」分頁** —— 強調工具會誠實列出沒抓到的東西
5. **最後開 `config.py`** —— 「換產業或客戶只要改設定檔,不用重寫程式」

**準備 Plan B**:事先把 PDF 下載好放在 `downloads/`。萬一現場網路不穩或
HKEXnews 有異動,直接用 `--pdf` 模式照常展示核心分析能力。自動下載很吸睛,
但真正有價值的是後面的估值參數萃取,不要讓前者的風險拖累後者。

建議 demo 控制在 5 分鐘內,把時間留給問答 —— 面試官通常對「你怎麼想到這樣
設計」比看你跑程式更有興趣。
