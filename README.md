# WholeBIF-RDB Pipeline

WholeBIF-RDB（Whole Brain Interconnection Fluency - Research Database）のデータ取り込みパイプライン。Google Spreadsheet から新規の神経接続データを受け取り、信頼度スコア（PDER, CSI, CR）を計算して BDBRA CSV を生成する。

## このリポジトリの位置づけ

WholeBIF-RDB は脳の神経接続を記録したデータベースで、各レコードに **Credibility Rating (CR)** という信頼度スコアが付与されている。CR は以下の6つのスコアの積で計算される。

```
CR = Source Region Score × Receiver Region Score × CSI × Literature Type Score × Taxon Score × PDER
```

このパイプラインは、下図の赤枠部分に対応する。

```
Google Spreadsheet (wbConnections / wbReferences)
        │
        ▼
┌────────────────────────────────────┐
│  manual_to_bdbra_converter.py      │ ← このリポジトリ
│    ├── schema.py                   │
│    ├── credibility_calculator.py   │
│    └── pipeline.py                 │
└────────────────────────────────────┘
        │
        ▼
   BDBRA CSV  →  import_bdbra_into_wholebif.py  →  PostgreSQL
```

## ディレクトリ構成

```
.
├── src/                         ソースコード
│   ├── schema.py                  データ型定義・バリデーション（344行）
│   ├── credibility_calculator.py  PDER・CSI・CR計算（307行）
│   ├── manual_to_bdbra_converter.py  CSV変換コンバータ（398行）
│   └── pipeline.py                オーケストレータ（226行）
│
├── tests/                       テスト（99件、全件合格）
│   ├── conftest.py                共有フィクスチャ
│   ├── test_credibility.py        信頼度計算テスト（45件）
│   ├── test_converter.py          コンバータテスト（31件）
│   └── test_pipeline.py           統合テスト（23件）
│
├── tools/                       スタンドアロンツール
│   ├── score_pder_with_claude_api.py   PDER一括スコアリング（Claude API）
│   └── score_citation_sentiment.py     CSI一括スコアリング（Semantic Scholar + Claude API）
│
├── docs/                        ドキュメント
│   ├── test_design.md             テスト設計書（設計意図・全件解説）
│   └── test_results.md            テスト実行結果報告書
│
├── data/                        データ（.gitignore対象、ローカルで配置）
├── pyproject.toml               プロジェクト設定
└── README.md                    この文書
```

## セットアップ

```bash
git clone https://github.com/<your-org>/wholebif-rdb-pipeline.git
cd wholebif-rdb-pipeline
pip install pytest pytest-cov requests
```

## 使い方

### パイプライン実行（ヒューリスティックモード）

外部 API を使わず、ルールベースで PDER・CSI を計算する。テストやドライランに向く。

```bash
python src/pipeline.py \
  -c data/new_connections.csv \
  -r data/new_references.csv \
  -o ./output \
  --contributor "YourName" \
  --project-id "PROJECT01" \
  --dry-run
```

### パイプライン実行（高精度モード）

Claude API で PDER を、Semantic Scholar API で CSI を計算する。本番運用向け。

```bash
export ANTHROPIC_API_KEY="your-key"
python src/pipeline.py \
  -c data/new_connections.csv \
  -r data/new_references.csv \
  -o ./output \
  --contributor "YourName" \
  --project-id "PROJECT01"
```

### スタンドアロンツール

既存の wbConnections CSV に対して PDER や CSI を一括スコアリングする場合：

```bash
# PDER 一括スコアリング（Claude API 使用）
export ANTHROPIC_API_KEY="your-key"
python tools/score_pder_with_claude_api.py \
  -i data/WholeBIF_RDBv2_wbConnections.csv \
  -o data/WholeBIF_RDBv2_scored.csv

# CSI 一括スコアリング（Semantic Scholar + Claude API 使用）
python tools/score_citation_sentiment.py \
  -i data/WholeBIF_RDBv2_wbConnections.csv \
  -r data/WholeBIF_RDBv2_wbReferences.csv \
  -o data/WholeBIF_RDBv2_scored.csv
```

## テスト

```bash
# 全99件実行
python -m pytest tests/ -v

# カバレッジ付き
python -m pytest tests/ --cov=src --cov-report=term-missing

# 特定のテストだけ
python -m pytest tests/test_credibility.py::TestCRCalculation -v
python -m pytest tests/ -k "pder" -v
```

### テスト結果（2026-02-27 時点）

```
99 passed in 0.41s

src/schema.py                    99%
src/manual_to_bdbra_converter.py 73%
src/pipeline.py                  69%
src/credibility_calculator.py    53%
TOTAL                            74%
```

テスト設計の詳細は [docs/test_design.md](docs/test_design.md)、実行結果の全ログは [docs/test_results.md](docs/test_results.md) を参照。

## CR 計算の検証

実データ（WholeBIF_RDBv2）との照合でパイプラインの計算精度を確認済み。

| 参照行 | スコア6つ | 期待 CR | 計算結果 |
|--------|----------|--------|---------|
| Row 176 | (1, 1, 0.95, 1, 0.5, 0.4) | 0.190 | ✓ 一致 |
| Row 319 | (1, 1, 0.95, 1, 0.6, 0.8) | 0.456 | ✓ 一致 |
| Row 181 | (1, 1, 0.95, 0.5, 0.5, 0.3) | 0.0712 | ✓ 一致 |

## PDER スコア体系

計測手法ごとの PDER スコア範囲。方向性特定能力の高い手法ほど高スコア。

```
手法カテゴリ               スコア範囲    既存データでの件数
─────────────────────────────────────────────────────
Various tracing            0.85-0.95     200行
Tracer study               0.80-0.95    1,094行
Electrophys / Opto/Chemo   0.55-0.75    2,266行
DTI / tractography         0.35-0.55      815行
fMRI / rs-fMRI             0.30-0.50    1,500+行
Review / Unspecified       0.20-0.40   18,159行
Textbook                   0.15-0.35       54行
```

## ライセンス

MIT License

## 関連リソース

- [WholeBIF-RDB プロジェクト](https://wholebif.org)（日本大学）
- [BDBRA フォーマット仕様](https://wholebif.org/bdbra)
