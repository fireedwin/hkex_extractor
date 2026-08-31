# HKEX Document Extractor — 港交所文件資料萃取工具

為 business valuation / appraisal 工作流設計的年報與招股書資料萃取工具。

---

## 這個工具解決什麼問題

把整份 400 頁年報丟給 AI 問問題,通常會失敗,原因有三個:

| 問題 | 本工具的處理方式 |
|---|---|
| 文件太大,超出模型上下文 | 規則層先把全份縮減到少數相關頁面再交給 AI |
| AI 讀數字會出錯或幻覺 | 數字一律由正則式從原文精確擷取,並做合理範圍檢查,不經模型生成 |
| 答案無法追溯、不敢採用 | 每一列輸出都帶 PDF 頁碼、年報印刷頁碼與**原文行**,可即時翻回原文覆核 |

核心理念:**規則層負責「找」,AI 負責「讀懂」。** 兩者分工,而不是把全部工作丟給 AI。

旺季的實際工作型態是「每天新增幾十份」而不是「一次重跑全部」,所以工具
內建**增量處理**:已經分析過、且分析邏輯沒有更新的檔案,重跑時會自動跳過。

也不只抓年報。除了 Annual Report,還能下載**通函**(主要交易、非常重大
收購/出售、反收購)、中期報告、ESG 報告 —— 通函裡常附獨立估值師的正式
估值報告,是折現率/資本化率最直接的 benchmark 來源。

工具也會**誠實回報自己的失誤**:交叉驗證沒過、擷取到 0 個科目、查無
結果這類狀況,終端機容易被大量正常輸出淹沒,所以會自動彙整成一份錯誤
紀錄檔,不會讓「畫面顯示成功但實際沒抓到東西」的情況被忽略。

---

## 兩個入口,分工明確

```
pipeline.py    下載 + 分析(端到端)
run.py         只分析本機 PDF
```

下載一律走 `pipeline.py`。`run.py` 不再負責下載 —— 舊的 `hkexnews.py`
假設 HKEXnews 有公開 API,實測證實沒有,而且失敗時會回傳空白結果卻不報錯。
該檔案已標記為棄用,匯入時會直接擋下。

---

## 安裝

```bash
pip install -r requirements.txt
```

會安裝:`pymupdf`(PDF 讀取,預設引擎)、`pdfplumber`(備用引擎)、
`openpyxl`(Excel)、`selenium`(HKEXnews 下載)、`requests`、`reportlab`(產生測試檔)。

下載功能另需電腦已安裝 **Google Chrome**。

---

## 常用指令

```bash
# 先確認環境正常(產生模擬年報再分析)
python3 make_sample_pdf.py
python3 run.py --pdf sample_annual_report.pdf

# 分析單一 PDF
python3 run.py --pdf downloads/00700_TENCENT_20250408.pdf

# 分析整個資料夾(旺季批次最常用)
python3 pipeline.py --pdf downloads
python3 pipeline.py --pdf downloads --recursive        # 連子資料夾
python3 pipeline.py --pdf "downloads/007*.pdf"         # 萬用字元要加引號

# 下載 + 分析(指定公司)
python3 pipeline.py --stocks 00700,00731 --from 20250101 --to 20251231
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --show-browser

# 下載其他文件類型(預設是年報 annual_report;可用選項見 config.DOC_TYPES)
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --type interim_report
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --type major_transaction

# 下載 + 分析(全市場,資料量大,不建議現場示範)
python3 pipeline.py --all-market --from 20250301 --to 20250430

# 加上 AI 語意層(選用)
export ANTHROPIC_API_KEY=sk-ant-...
python3 pipeline.py --pdf downloads --ai

# 增量處理(預設開啟):已分析過且結果仍有效的檔案自動跳過
python3 pipeline.py --pdf downloads              # 第二次跑幾乎是零成本
python3 pipeline.py --pdf downloads --force      # 忽略帳本,強制全部重跑
python3 pipeline.py --pdf downloads --no-incremental   # 完全不讀寫帳本
python3 pipeline.py --reset-ledger               # 清空帳本,下次視同全新開始

# 查帳本:哪些已處理、下次會跑還是跳、理由是什麼
python3 check_ledger.py
python3 check_ledger.py downloads

# 錯誤紀錄:預設自動產生,不需額外指令。想換位置或關掉才需要加參數
python3 pipeline.py --pdf downloads --error-dir "logs/問題紀錄"
python3 pipeline.py --pdf downloads --no-error-report
```

沒有 API key 時工具仍完整運作,AI 只是加分項,不是單點故障。

---

## 增量處理:不只比對檔案,還比對「分析邏輯」

單純「PDF 沒變就跳過」是不夠的。這個工具的 `config.py` 會持續擴充科目
別名(例如補上 `Cost of inventories`、`Bank balances and cash`),如果
增量處理只看 PDF 內容,補齊的別名永遠不會套用到已經處理過的舊文件上 ——
使用者會拿到**過期結果**,畫面上卻顯示「已完成」。

所以每份文件的處理紀錄同時記錄:

1. **PDF 內容指紋**(SHA-256) —— 內容變了(例如公司重新提交修訂版)就重跑
2. **分析邏輯版本** —— `config.py`、`scanner.py`、`financials.py` 等所有
   會影響擷取結果的模組原始碼一起雜湊。改一行別名,受影響的文件會**全部**
   自動重新分析,不需要手動判斷「這次改動要不要清快取」。
   全部重跑時會直接指出是哪個模組變動,不用自己去翻程式碼:

   ```
   [pipeline] 分析邏輯已更新,157 份既有結果視為過期,重新分析以免給出舊版擷取結果
   [pipeline]   變動的模組 — 已修改: config.py
   ```
3. **`--ai` 開關** —— 有無 AI 層的輸出不同,不會互相當成快取命中
4. **輸出檔是否還在** —— 使用者手動刪掉 Excel,下次會自動補回來

指紋比對成本很低:實測 3 份年報(12.4 MB)約 10 ms,推算 200 份約 1 秒,
相對於分析本身可以忽略。

指紋用**內容**而非檔名當 key,所以:

- 同一份年報被下載兩次(檔名不同,例如多了 `-R` 或時間戳)會被辨識為
  重複檔案,自動跳過並在訊息中說明,不會被誤判成新文件
- 帳本毀損或格式不符時,不會讓整條 pipeline 停擺,而是退回「全部重跑」
  —— 這是最壞情況,但不會產生錯誤結果

批次執行時,**每分析成功一份就立刻寫入帳本**,不等全部跑完。跑到一半
當機或被中斷,重跑只需補齊剩下的部分。

---

## 下載更多種文件類型

除了年報,`--type` 還可以下載:

| `--type` 值 | 中文 | 說明 |
|---|---|---|
| `annual_report`(預設) | 年報 | 已用真實下載驗證過完整流程 |
| `interim_report` | 中期報告 | 港交所已取消強制季報,這是年報之外唯一另一份法定財務資訊 |
| `esg_report` | ESG 報告 | |
| `major_transaction` | 主要交易通函 | 常附獨立估值師報告 |
| `very_substantial_acquisition` | 非常重大收購事項通函 | 常附獨立估值師報告 |
| `very_substantial_disposal` | 非常重大出售事項通函 | 常附獨立估值師報告 |
| `reverse_takeover` | 反收購行動通函 | 常附獨立估值師報告 |

四種通函類型的價值,不是通函本身有財務數據,而是規則上達到一定規模的
資產收購/處置**通常要附獨立估值師的正式報告**——裡面的折現率、WACC、
資本化率是別人已經簽字負責的估值結論,比從年報附註裡零散地撈參數更
直接,是估值參數 benchmark 資料庫最有含金量的來源。

七種類型的選單展開路徑已用 `check_menu.py --all` 在真實 HKEXnews 頁面
上驗證過。但除了年報,其餘類型「搜尋結果內容是否正確」還沒有大量實測,
第一次用新類型建議搭配 `--show-browser` 肉眼確認一次。想自己校正或
新增文件類型時:

```bash
python3 check_menu.py --type major_transaction   # 逐層印出真實選單看到什麼
python3 check_menu.py --list-top                 # 只看第一層有哪些分類
python3 check_menu.py --all                      # 全部類型一次診斷
```

要新增文件類型,在 `config.py` 的 `DOC_TYPES` 加一筆(照畫面上的分類
路徑填),不用改程式邏輯。

---

## 錯誤紀錄:抓出「畫面看起來成功,實際有問題」的狀況

批次跑幾十份時,警告訊息會被大量正常輸出淹沒;更麻煩的是有些失敗在
畫面上長得像成功。實測踩過的坑:一份通函分析完,終端機顯示

```
[check] ✓ 1 項會計恆等式交叉驗證全部通過
完成:1 / 1 份成功
```

但實際上是 **0 個財務科目**、報表頁相距 39 頁——因為通函本來就不是
財務報表類文件,恆等式檢查項目太少,巧合地全部通過。只看最後一行會
以為沒事。

工具會自動彙整這類狀況成一份 txt,放進 `error message/` 資料夾
(預設,可用 `--error-dir` 換位置,`--no-error-report` 關閉):

```
檔案名                                      | stock號 | 什麼事                  | 執行時間
--------------------------------------------------------------------------
01007_LONGHUI_INTL_MT_20260825_extract.xlsx | 01007  | 找不到報表頁:現金流量表  | 2026-08-31 08:26:29
01007_LONGHUI_INTL_MT_20260825_extract.xlsx | 01007  | 完全沒有擷取到財務科目   | 2026-08-31 08:26:29
無法生成                                     | 09999  | 分析失敗:PDF 檔案毀損   | 2026-08-31 08:26:29
```

沒有產生檔案的那筆,檔案名欄位會寫「無法生成」。**沒有偵測到任何問題
就完全不會建檔**——每次都產生一個空紀錄,只會讓人學會忽略這個資料夾,
真的有問題那次反而看不到。

會被記錄的狀況定義在 `config.py` 的 `ERROR_PATTERNS`,跟科目別名一樣
是設定檔,要多抓一種狀況只要加一列。目前涵蓋:交叉驗證未通過、擷取
到 0 個財務科目、找不到特定報表頁、科目未擷取、年度欄未偵測、疑似
掃描頁、估值參數 0 筆,以及下載階段的查無結果、下載失敗、分析中途
丟例外。

---

## 輸出成果

一個 Excel 檔,七個分頁:

| 分頁 | 內容 |
|---|---|
| Summary 摘要 | 文件統計、擷取筆數、**會計恆等式交叉驗證**、方法論 |
| **Valuation Params 估值參數** | 折現率 / WACC / 永續增長率 / 資本化率 / 預期波幅 + 信心度 + 來源頁 |
| Financials 財務數據 | 三大報表科目,本年 vs 上年,附**原文行** |
| Ratios 財務比率 | 毛利率、流動比率、商譽佔比、ROE —— 以公式連結,改數字會自動重算 |
| Chart 趨勢圖 | 主要科目本年 vs 上年柱狀圖 |
| Extracts 主題段落 | 無形資產 / 減值測試 / 公允價值 / 投資物業 / 研發 / ESG 段落 |
| Review Queue 待覆核 | **未擷取到的財務科目** + 文字量過低(疑似掃描頁)的頁面 |

估值參數分頁是對估值行價值最高的部分 —— 它把每份年報變成 benchmark 資料庫裡的幾行資料。

---

## 自動驗證機制

工具不只擷取,還會自己檢查抓得對不對。終端機與 Excel 摘要頁都會顯示:

```
[check] ✓ 5 項會計恆等式交叉驗證全部通過
```

檢查項目:

- 流動資產 − 流動負債 = 淨流動資產
- 總資產 = 總負債 + 總權益
- 收入 − 銷售成本 = 毛利
- 除稅前溢利 ± 稅項 = 年內溢利(自動判斷稅項是費用還是抵免)
- 三大報表應相鄰(離群代表某張抓錯頁)

**報表數字之間本來就該對得上,對不上就代表某欄錯位。** 這比人工逐頁核對快得多。

另外,沒抓到的科目會列進待覆核分頁,不會靜靜消失。

---

## 檔案結構

```
核心流程
  config.py            領域知識層 —— 主題關鍵字、科目別名、估值參數、擷取參數
                        改這裡會讓既有結果失效並自動全部重新分析(刻意的)
  ops_config.py        操作設定層 —— 下載文件類型(DOC_TYPES)、錯誤紀錄
                        規則(ERROR_PATTERNS)。改這裡不會觸發重跑
  pdf_reader.py        逐頁萃取 + 印刷頁碼校正 + 掃描頁標記 + 雙引擎切換
  scanner.py           主題定位 + 估值參數擷取 + 合理性檢查
  financials.py        三大報表解析 + 會計恆等式驗證
  excel_out.py         Excel 輸出 + 公式 + 圖表
  ai_layer.py          AI 語意層(選用)
  incremental.py       增量處理帳本 —— 檔案指紋 + 分析邏輯版本追蹤
  error_report.py      錯誤紀錄 —— 彙整交叉驗證失敗、查無結果等問題成 txt
  console.py           Windows 編碼修正
  run.py               分析單一/多個 PDF
  pipeline.py          端到端主流程

下載
  hkexnews_selenium.py 瀏覽器自動化下載核心,支援多種文件類型
  batch_download.py    只下載不分析
  hkexnews.py          已棄用(保留作技術調查紀錄)

測試與診斷
  test_financials.py   財務科目擷取回歸測試
  test_engines.py      雙引擎一致性測試
  test_pagenos.py      頁碼偵測回歸測試
  test_incremental.py  增量處理回歸測試(帳本、邏輯版本、中斷續跑等情境)
  test_doc_types.py    文件類型擴充回歸測試(檔名防撞、選單展開控制流程)
  test_error_report.py 錯誤紀錄回歸測試(用真實執行輸出當測試素材)
  test_config_split.py config/ops_config 分界回歸測試(向下相容 + 隔離 + 安全)
  check_files.py       確認檔案為最新版、無重複副本
  check_pagenos.py     頁碼偵測可靠度分析
  check_ledger.py      增量處理帳本診斷 —— 哪些已處理、下次會跑還是跳
  check_menu.py        HKEXnews 文件類型選單診斷 —— 逐層印出真實頁面選項
  compare_engines.py   雙引擎逐項比對
  diagnose_params.py   估值參數漏抓診斷
  make_sample_pdf.py   產生測試樣本
```

要換一個行業或客戶,只需要改 `config.py`,不用動程式邏輯。

### config.py 與 ops_config.py 的分界

只有一條線:**改了它,同一份 PDF 產出的 Excel 內容會不會不一樣?**

| | 放哪 | 改了會怎樣 |
|---|---|---|
| 科目別名、主題關鍵字、估值參數、擷取參數 | `config.py` | 既有結果失效,全部重新分析 |
| 下載文件類型、錯誤紀錄規則與嚴重度 | `ops_config.py` | 不影響任何已分析的結果 |

分開的原因很實際:旺季調一次錯誤訊息措辭或新增一種文件類型,不該讓
幾百份已經分析好的年報陪著重跑。而科目別名改了就**必須**重跑 ——
否則使用者會拿到過期結果卻以為是最新的。

`config.py` 會 re-export `ops_config.py` 的名稱,所以 `config.DOC_TYPES`、
`config.ERROR_PATTERNS` 這些既有寫法照常可用。

新增設定前先問一次那條分界線的問題;放錯邊的後果是「改了萃取邏輯卻
沿用舊結果」,比多重跑幾次嚴重得多。

---

## 已在真實年報上驗證

用四份真實港股年報實測(騰訊 00700、C&D 00731、中國衛生 00673、WLS 08021):

- 騰訊 24 個財務科目,與 PDF 原文逐項核對 28 個數字全部一致
- 四份年報的會計恆等式交叉驗證全部通過
- 支援中英對照年報(港股半數以上是這種格式)
- 支援虧損公司(Profit → Loss 自動對稱)、毛損、稅務抵免
- 破折號(nil)正確轉為 0,不會造成年度欄位左移
- 自動剔除附註編號,但保留真實的小額數值
- 報表頁自動校正(曾把附註頁誤判為現金流量表,已修正)

處理速度:274 頁年報約 0.5 秒(PyMuPDF 引擎)。

增量處理已用真實年報驗證 8 種情境(首次執行、立即重跑、`config.py` 更新後
強制重跑、輸出檔遺失、內容變動的修訂版、同內容不同檔名的重複下載、帳本
毀損、`--ai` 開關切換),詳見 `test_incremental.py`。

七種文件類型的選單展開路徑已用 `check_menu.py --all` 在真實 HKEXnews
頁面上驗證通過;檔名防撞、選單展開控制流程另有 43 項離線回歸測試,
詳見 `test_doc_types.py`。

錯誤紀錄的判斷邏輯直接拿真實踩到的問題案例(01007 通函擷取到 0 個科目、
交叉驗證未通過)當測試素材,共 41 項,詳見 `test_error_report.py`。

`config.py` / `ops_config.py` 的分界另有 27 項測試,同時鎖住三件事:
既有寫法不能斷、改 ops_config 不觸發重跑、改 config 一定觸發重跑。

---

## 已知限制(誠實揭露)

- **掃描版 PDF 無法處理**,只會被標記進待覆核清單。要處理需另接 OCR。
- **跨頁表格**目前不會自動接續(報表跨頁已處理,附註表格未處理)。
- **附註中的科目不擷取**,例如 R&D、折舊、攤銷若不在報表表面就抓不到。
- **HKEXnews 沒有官方 API**,下載走瀏覽器自動化,網站改版可能失效。
  `hkexnews_selenium.py` 的 `SELECTORS` 集中管理所有頁面元素,便於校正。
  下載已內建延遲,請遵守網站使用條款。
- **PyMuPDF 採 AGPL 授權**,自用無虞;若要對外散布或架成網路服務,
  請先確認授權合規。
- **這是輔助工具,不是取代人手覆核。** 信心度標為 Low、以及待覆核分頁
  列出的項目,應由分析師確認。
