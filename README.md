# bittimes-mycoin-feed

BITTIMES 固定ページ「マイ銘柄」の**「本日の主な材料」ブロック**へ配信する、公開データ（見出しJSON）の生成・配信リポジトリ。

- **配信物**: [`mycoin_extnews.json`](./mycoin_extnews.json) を GitHub raw で配信。WPページの JS が fetch する（同スキーマ）。
  - raw URL: `https://raw.githubusercontent.com/SIMPLIFY-CoLtd/bittimes-mycoin-feed/main/mycoin_extnews.json`
- **中身**: 主要媒体（Reuters / Bloomberg / CoinDesk / The Block / Decrypt / CNBC / Yahoo Finance 等）の**当日（直近24h）× 価格材料 × 銘柄関連**の見出し＋出典＋公開時刻＋元記事リンク。
  - **AI要約はしない**（見出しの日本語訳のみ）。**因果は断定しない**（枠名「本日の主な材料」）。
  - 該当0件の銘柄は空配列（ページ側で非表示）。
- **対象銘柄**: BTC / ETH / XRP / SOL / ADA / DOGE / SUI。

## 仕組み

1. `generate.py` が Google News RSS（無料・リアルタイム）から各銘柄の直近24hの信頼媒体見出しを収集。
2. Haiku 1コールで「日本語訳＋material（価格材料か）＋relevant（その銘柄自身の材料か）」を相乗り分類。
3. `material かつ relevant` のみ新着順 top2 を採用し JSON 出力。
4. `.github/workflows/build.yml` が3時間ごとに実行→`mycoin_extnews.json` を更新コミット。

## 必要な設定

- リポジトリ Secret に **`ANTHROPIC_API_KEY`** を設定（Actions → Settings → Secrets and variables → Actions）。
  - 未設定の間は分類が行われず、`coins` は空のまま配信される（課金は発生しない）。

## コスト

- Google News RSS 取得＝¥0。GitHub Actions（publicリポ）＝無料枠内。
- Haiku 1コール/実行 × 3時間ごと ≈ 月¥100前後。

## 法務・方針

- 見出し＋出典＋リンクの**アグリゲーション**（本文転載・AI要約なし・リンクアウト）。
- 因果を断定しない（第248・BITTIMES 方針）。公開されるのは価格材料の見出しJSONのみ（機密情報なし）。
