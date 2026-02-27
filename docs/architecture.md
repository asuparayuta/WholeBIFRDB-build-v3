# パイプラインアーキテクチャ

## 全体フロー

```
                       ┌───────────────────────────────────┐
                       │      Google Spreadsheet           │
                       │  wbConnections  /  wbReferences   │
                       └─────────┬─────────────────────────┘
                                 │ CSV export
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      pipeline.py                                │
│                                                                 │
│  1. load_references()         wbReferences CSV → ReferenceRecord│
│  2. load_connections()        wbConnections CSV → ConnectionRecord
│  3. cross_validate()          参照整合性チェック                 │
│  4. compute_derived_fields()  combined_search, display_string等 │
│  5. compute_credibility()     PDER + CSI + CR 計算              │
│  6. write_bdbra_csv()         BDBRA CSV 出力                    │
│  7. generate_report()         JSON レポート生成                  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  credibility_calculator.py                              │    │
│  │                                                         │    │
│  │  score_pder(method, lit_type)                           │    │
│  │    ├── ヒューリスティック: PDER_RULES テーブル照合      │    │
│  │    └── 高精度: Claude API                               │    │
│  │                                                         │    │
│  │  score_csi(reference_id)                                │    │
│  │    ├── キャッシュ: KNOWN_CSI (16論文)                   │    │
│  │    ├── ヒューリスティック: 発表年による推定             │    │
│  │    └── 高精度: Semantic Scholar API + Claude API        │    │
│  │                                                         │    │
│  │  compute_cr(src, rcv, csi, lit, tax, pder)             │    │
│  │    └── CR = 6スコアの積                                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌──────────────────────────────────────┐                       │
│  │  schema.py                           │                       │
│  │  ├── WB_CONNECTIONS_COLUMNS (42列)   │                       │
│  │  ├── WB_REFERENCES_COLUMNS (23列)    │                       │
│  │  ├── ConnectionRecord (dataclass)    │                       │
│  │  ├── ReferenceRecord (dataclass)     │                       │
│  │  └── validate_connection/reference   │                       │
│  └──────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                          BDBRA CSV (42列)
                                 │
                                 ▼
                    import_bdbra_into_wholebif.py
                                 │
                                 ▼
                           PostgreSQL
```

## データフロー

### 入力

| ファイル | 列数 | 内容 |
|---------|------|------|
| wbConnections CSV | 42 | 神経接続レコード（送信元/受信先の脳領域CID、手法、スコア等） |
| wbReferences CSV | 23 | 参考文献レコード（Reference ID、DOI、ジャーナル名等） |

### 計算される値

| 値 | 計算方法 | 入力 |
|----|---------|------|
| PDER | ルールテーブル or Claude API | 手法名 + 文献種別 |
| CSI | キャッシュ / ヒューリスティック / Semantic Scholar | Reference ID + DOI |
| Literature Type Score | 固定マッピング | 文献種別（Experimental=1.0, Review=0.8 等） |
| CR | 6スコアの積 | 上記 + Source/Receiver/Taxon（入力値） |

### 派生フィールド

| フィールド | 生成ルール |
|-----------|-----------|
| combined_search | sender_cid + receiver_cid |
| reference_id_bracket | "[" + Reference ID + "]" |
| display_string | receiver_cid (00/00) [Reference ID]; |
| journal_name | wbReferences から Reference ID で引き当て |

### 出力

| ファイル | 内容 |
|---------|------|
| BDBRA CSV | 42列、全スコア計算済みの接続レコード |
| report.json | 処理件数、エラー/警告数、実行時間 |

## モード

| モード | PDER | CSI | 用途 |
|--------|------|-----|------|
| dry-run | スキップ | スキップ | CSV変換のみ確認 |
| ヒューリスティック | ルールテーブル | キャッシュ+年代推定 | テスト、オフライン |
| 高精度 | Claude API | Semantic Scholar + Claude | 本番 |
