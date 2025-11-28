# 動物園語音 AI 客服自動化測試指南

本專案協助台北市立動物園 AI 小幫手進行語音測試，涵蓋：

1. 以 Azure Speech TTS 批次產生測試語音。
2. 只測 STT 的批次評估。
3. 端到端（語音→STT→Chatbase 回答）的整體測試。

---

## 一、環境需求

- Python 3.10+（建議 3.11，以符合 Google API 後續支援）
- macOS / Linux / WSL 皆可
- 已取得下列雲端憑證：
  - Azure Speech：`AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` + 支援的 TTS voice 名稱
  - Google Cloud Speech-to-Text：Service Account JSON 檔
  - Chatbase：API Key + Bot ID

安裝套件：

```bash
pip install -r requirements.txt
```

## 二、設定 `.env`

建立 `.env`（或複製 `.env.example`），填入：

```
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
AZURE_TTS_VOICE=zh-TW-HsiaoYuNeural  # 依實際可用 voice 調整
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service_account.json
CHATBASE_API_KEY=...
CHATBASE_BOT_ID=...
CHATBASE_API_URL=https://www.chatbase.co/api/v1/chat
DEFAULT_LANGUAGE_CODE=zh-TW
```

> ⚠️ 修改 `.env` 後，請重新啟動終端或 `source .env`，以免沿用舊的環境變數。

## 三、資料檔案

請將下列檔案置於專案根目錄：

- `zoo_dataset.csv`：題庫（必備，欄位如「編號」「中文問題」）。
- `answer_keywords.csv`：可選，用於 E2E 自動評分。格式：`id,check_keywords_zh`。
- `stt_testset.csv`：若先前尚未建立，可由 TTS 工具自動生成。
- `audio/`、`results/` 目錄由腳本自動建立。

## 四、產生語音與 STT 測試集

使用 Azure TTS 批次產生 WAV，同時輸出基礎版 `stt_testset.csv`：

```bash
python tts_generate.py \
    --input zoo_dataset.csv \
    --outdir audio \
    --language zh-TW \
    --voice zh-TW-HsiaoYuNeural \
    --speed 1.0 \
    --generate-testset \
    --testset-output stt_testset.csv \
    --id-column 編號 \
    --question-column 中文問題
```

說明：
- `--speed`：語速倍率（1.0 原速，>1.0 變快，<1.0 變慢）。
- `--id-column`/`--question-column`：CSV 若非英文欄名，可在此指定。
- WAV 會存放於 `audio/q{id}_v1.wav`，並在結果中標記 speaker/noise/ref_transcript。

（若已有真人錄音，只需手動編輯 `stt_testset.csv`，將 `wav_path` 指向對應檔案即可。）

## 五、STT 單獨測試

執行 Google Cloud STT，計算 CER / WER / intent：

```bash
python stt_test.py \
    --stt-testset stt_testset.csv \
    --outdir results \
    --intent-strict
```

輸出：
- `results/stt_results_YYYYMMDD.csv`
- `results/error_cases_stt_YYYYMMDD.csv`
- 終端會印出平均 CER、WER，以及（開啟 `--intent-strict` 時）Intent Accuracy。

## 六、端到端（E2E）測試

串接 STT + Chatbase，自動判斷回答是否正確：

```bash
python e2e_test.py \
    --stt-testset stt_testset.csv \
    --dataset zoo_dataset.csv \
    --keywords answer_keywords.csv \
    --outdir results \
    --intent-strict
```

- 若無 `answer_keywords.csv`，可省略 `--keywords`，此時 AI 正確率顯示為 `None`，需人工審查。
- 結果輸出於：
  - `results/e2e_results_YYYYMMDD.csv`
  - `results/error_cases_e2e_YYYYMMDD.csv`
- 終端統計：STT Intent Accuracy、AI Correct Rate、End-to-End Accuracy。

## 七、結果檔案說明

| 檔案 | 內容 |
| --- | --- |
| `audio/q{id}_v1.wav` | TTS 產生的測試音檔。 |
| `stt_testset.csv` | STT 測試清單（`wav_path`, `ref_transcript`, `speaker_type`, ...）。 |
| `results/stt_results_YYYYMMDD.csv` | STT 指標結果。 |
| `results/e2e_results_YYYYMMDD.csv` | 端到端結果，包含 `stt_raw`, `ai_answer`, `ai_correct`, `e2e_success`。 |
| `results/error_cases_*.csv` | 失敗或錯誤案例，方便人工追查。 |

## 八、常見問題

- **Azure TTS 報 Unsupported voice**：表示你的 Speech Service 區域不支援該 voice，請換成支援的名稱（可在 Speech Studio 查詢）。
- **STT 報 `SERVICE_DISABLED`**：到 GCP Console 啟用 Speech-to-Text API，或確認 service account 權限。
- **Chatbase 401 Unauthorized**：確認 `.env` 的 `CHATBASE_API_KEY`/`CHATBASE_BOT_ID` 與實際 bot 一致，更新後重新載入環境變數。
- **CSV 欄名不符**：利用 `--id-column` / `--question-column` 指定對應欄位，或直接在 CSV 中改成英文欄名。

## 九、後續擴充

- 可在 `answer_keywords.csv` 增加英文關鍵字欄位，並擴充 `scoring.py` 的比對邏輯。
- 針對 STT / Chatbase 結果加入自動回報或 dashboard。
- 錄製不同說話者、環境的真實語音，擴充 `stt_testset.csv` 以提升測試覆蓋率。

祝測試順利！
