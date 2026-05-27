# 機票追蹤器

每天自動查 Amadeus 票價，跌破門檻就在 GitHub 開 issue（GitHub 會自動寄信給你）。所有歷史價格存在 `history.json`，可以畫線圖看趨勢。

## 一次性設定（約 10 分鐘）

### 1. 申請 Amadeus API key
1. 到 https://developers.amadeus.com 註冊
2. 進 **My Self-Service Workspace** → **Create new app**
3. 拿到 **API Key** 和 **API Secret**
4. 預設用的是 production endpoint（免費 2000 次/月）。新申請的 app 通常會先給 test 環境，要切到 production 看 [這篇](https://developers.amadeus.com/get-started/move-to-production-697)。想先用 test 跑通的話，到 repo Settings 加一個 secret `AMADEUS_BASE` = `https://test.api.amadeus.com`。

### 2. 把 key 放進 GitHub Secrets
repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|---|---|
| `AMADEUS_KEY` | 你的 API Key |
| `AMADEUS_SECRET` | 你的 API Secret |

`GITHUB_TOKEN` 不用自己設，GitHub Actions 會自動給。

### 3. 確認通知打開
GitHub 預設新 issue 會寄 email 到你註冊的信箱。如果沒收到，到 https://github.com/settings/notifications 檢查。

### 4. 改 `config.yml`
編輯航線、日期、門檻。要加多條航線就在 `routes:` 下面複製一段。

### 5. 跑一次測試
repo → **Actions** → **Track flight prices** → **Run workflow**

跑完後：
- 看 log 確認有抓到價格
- `history.json` 會多一筆紀錄
- 如果已經低於門檻，會看到一個新 issue

## 之後

排程是每天台北早上 9 點，會自動跑。不用管它。

- **看歷史**：直接打開 `history.json`，或丟給我幫你畫圖
- **改門檻**：編輯 `config.yml` 的 `threshold`
- **加航線**：在 `config.yml` 加一段
- **暫停**：把 `.github/workflows/track-flight.yml` 改個檔名（或在 Actions 頁面 disable）

## 注意事項

- Amadeus 的價格是 LCC 之外的 GDS 行情，跟 Google Flights 看到的可能差幾百塊（Google 整合了 OTA），但走勢一致
- 跌破門檻時，同一條航線只會開一個 issue。關掉 issue 後，下次再跌破才會再開
- 免費 tier 2000 次/月，每天 1 次 × 1 條航線 = 30 次/月，超夠
