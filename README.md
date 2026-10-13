# 急上昇アナライザー

YouTube の急上昇（日本）を毎日自動で記録し、PC と iPhone のブラウザで分析できるアプリです。

- **ランキング**：急上昇の順位、前回からの順位の変化、NEW、連続ランクイン日数、勢い（1時間あたり再生）、登録者比など。カテゴリ・キーワードで絞り込めます。
- **分析**：カテゴリ別の本数、動画の長さ、投稿時間帯、公開からの経過時間、タイトルの頻出語、よく使われるタグ、よく入るチャンネル
- **推移**：日ごとの指標とカテゴリ別本数の推移、長く残っている動画
- **小規模**：登録者5000人以下のチャンネルで伸びている動画（ジャンル別キーワード検索から毎朝収集）
- **今すぐ取得**：API キーを設定すれば、その場で最新の急上昇を取得できます（キーは端末内にだけ保存）

## しくみ

| ファイル | 役割 |
|---|---|
| `index.html` | アプリ本体（GitHub Pages で公開） |
| `scripts/collect.py` | YouTube Data API で急上昇（最大200本）を取得し `data/` に保存 |
| `.github/workflows/collect.yml` | 毎日 7:07 と 19:07（日本時間）に `collect.py` を実行してデータをコミット |
| `scripts/collect_small.py` | ジャンル別に直近7日の人気動画を検索し、登録者5000人以下だけを `data/small/` に保存（1日1回・約3,000ユニット） |
| `data/YYYY-MM-DD.json` | その日のスナップショット |
| `data/index.json` | 日付一覧と日ごとの集計（推移グラフ用） |

API の使用量は急上昇が1回約10ユニット、小規模動画の検索が1日約3,000ユニットで、無料枠（1日 10,000）に収まります。

## 初期設定

1. **API キーを作る**：[Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作り、「YouTube Data API v3」を有効にして、「認証情報」→「API キーを作成」。
2. **キーを GitHub に登録**：リポジトリの Settings → Secrets and variables → Actions → New repository secret で、名前 `YOUTUBE_API_KEY`、値に API キーを入れて保存。
3. **公開**：Settings → Pages で「Deploy from a branch」、Branch `main`・フォルダ `/ (root)` を選んで Save。
4. **初回の収集**：Actions → 「急上昇データの収集」→ Run workflow。
5. `https://<ユーザー名>.github.io/youtube_analytics/` を開く。iPhone では Safari の共有ボタン →「ホーム画面に追加」。

## 手元で動かす

```bash
YOUTUBE_API_KEY=xxxx python3 scripts/collect.py
python3 -m http.server 8000   # http://localhost:8000 を開く
```
