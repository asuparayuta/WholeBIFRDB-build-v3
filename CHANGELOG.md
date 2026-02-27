# Changelog

## v0.1.0 (2026-02-27)

初回リリース。パイプライン図の赤枠部分（manual_to_bdbra_converter.py + 信頼度計算）を実装。

### 実装内容

**パイプラインコア**
- `schema.py` — wbConnections（42列）/ wbReferences（23列）のスキーマ定義、dataclass、バリデーション
- `credibility_calculator.py` — PDER（50+手法パターン）、CSI（キャッシュ16論文 + 年代別ヒューリスティック）、CR積計算
- `manual_to_bdbra_converter.py` — CSV読み込み → 参照整合性チェック → 派生フィールド生成 → 信頼度計算 → CSV出力
- `pipeline.py` — オーケストレータ、レポート生成、エラーハンドリング

**スタンドアロンツール**
- `tools/score_pder_with_claude_api.py` — 既存CSV全行のPDERをClaude APIで一括スコアリング
- `tools/score_citation_sentiment.py` — 85参考文献のCSIをSemantic Scholar + Claude APIでスコアリング

**テスト**
- 99件のテスト（45 信頼度計算 + 31 コンバータ + 23 統合）
- 全件合格、カバレッジ74%
- 実データ（WholeBIF_RDBv2 Row 176, 319, 181）との照合済み

**ドキュメント**
- テスト設計書（設計意図と全99件の解説）
- テスト実行結果報告書（pytest出力全文、カバレッジ詳細、構造ツリー）

### スコアリング実績

既存データ（177,097行）に対する一括スコアリングを完了。

- PDER: 568行のスコアリング完了
- CSI: 85参考文献（738行に影響）のスコアリング完了
- 結果CSV: `WholeBIF_RDBv2_scored.csv`（24MB、リポジトリには含まず）
