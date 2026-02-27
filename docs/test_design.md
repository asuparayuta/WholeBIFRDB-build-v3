# WholeBIF-RDB パイプライン テスト設計書

2026-02-27

---

## 前置き

このドキュメントは、WholeBIF-RDB の新規データ取り込みパイプラインに書いたテスト99件について、何を考えてそう設計したかを書き残したものである。

テスト設計の教科書的な話は世の中にいくらでもあるので、ここではあまり一般論は書かない。代わりに、「このシステム固有の事情として、ここは絶対に壊してはいけない」「ここは正直あまりリスクが高くないので最低限にした」といった、設計判断の理由を中心に書く。

後から読む人が「なんでこのテストがあるんだ？」「なんでここにはテストがないんだ？」と思ったときに、答えが見つかるようにしたい。

---

## このシステムで一番壊れてはいけないもの

テストの話をする前に、このシステムで何が一番大事かをはっきりさせておく。

WholeBIF-RDB は脳の神経接続データベースで、各レコードに Credibility Rating (CR) という信頼度スコアがついている。CR は6つのスコアの積で求まる。

```
CR = Source Region × Receiver Region × CSI × Literature Type × Taxon × PDER
```

このパイプラインの仕事は、新しいデータが来たときに PDER と CSI を計算して、最終的に CR を算出し、BDBRA CSV として吐き出すことだ。

したがって、**CR の計算が間違っていたら、このシステムの存在意義がない**。ここが一番壊れてはいけない部分であり、テストもここに最も厚く書いている。

逆に、CSVのヘッダの文字列が微妙に違うとか、ログの出力フォーマットがどうとかは、困りはするが致命的ではない。テストの厚みにはこの優先順位が反映されている。

---

## テスト対象の構成

ファイルは4つ。

| ファイル | 行数 | 何をやっているか |
|---------|------|----------------|
| schema.py | 344 | データ型の定義とバリデーション |
| credibility_calculator.py | 307 | PDER・CSI・CRの計算 |
| manual_to_bdbra_converter.py | 398 | CSV読み込み → 変換 → CSV出力 |
| pipeline.py | 226 | 上記を束ねるオーケストレータ |

合計で約1,300行。そこまで大きなシステムではないが、計算ロジックの正しさが命なので、テストコードのほうが本体より長い（約1,100行）。これは意図的にそうしている。

---

## テストの全体方針

### 何をテストして、何をテストしないか

テストしているもの：

- PDER のスコアリングロジック（ルールベース）
- CSI のスコアリングロジック（キャッシュ + ヒューリスティック）
- CR = 6スコアの積という計算
- CSV の読み書きでデータが壊れないこと
- バリデーションで不正データを弾けること
- パイプライン全体が通しで動くこと

テストしていないもの：

- Claude API を叩く部分（外部依存、テストが不安定になる）
- Semantic Scholar API を叩く部分（同上）
- PostgreSQL へのインポート（DB接続が必要で、ユニットテストに向かない）
- CLI のエントリーポイント（argparse + print文が主体で、壊れても被害が小さい）

API 周りをテストしていないのは怠慢ではなくて、判断である。外部 API のテストは mock を書けばできるが、mock のメンテナンスコストと得られる安心感が釣り合わない。API のレスポンス形式が変わったら mock も壊れるし、本物のAPIを叩くテストはCIで回せない。それよりも、API がコケたときにヒューリスティックにフォールバックする設計にしておいて、ヒューリスティック側を厚くテストするほうが実用的だ。

### カバレッジについて

全体で74%。内訳は以下の通り。

```
schema.py                    99%
manual_to_bdbra_converter.py 73%
pipeline.py                  69%
credibility_calculator.py    53%
```

credibility_calculator.py の53%が低く見えるかもしれないが、テストを通っていない47%はほぼ全部 API 呼び出しのコードパスだ。ヒューリスティック計算のパスはほぼ100%通っている。

カバレッジ100%を目指すことに僕はあまり意味を感じない。カバレッジが高くても、肝心のアサーションが甘ければ意味がない。逆にカバレッジが70%でも、重要な部分が厳密にテストされていれば十分に機能する。今回は CR 計算周りの正しさに集中した。

---

## テストの詳細

以下、テストファイルごとに解説する。

### test_credibility.py（45件）

信頼度計算のテスト。このファイルが一番重要。

#### PDER のスコア範囲テスト（18件）

PDER は計測手法の文字列を受け取ってスコアを返す関数だ。ルールテーブルで手法名のパターンマッチをしている。

テストでは、主要な手法カテゴリごとにスコアの範囲を確認している。範囲で見ているのは、ヒューリスティックなのでピンポイントの値を要求するのは過剰だからだ。ただし範囲は適当に決めたわけではなく、「この手法がこの範囲を外れたら、既存データとの整合性が崩れる」というラインで引いている。

トレーサー系（6件）。方向性を直接証明できる手法で、DBの中で最も信頼度が高い手法群。0.80〜0.95。

```
test_tracer_study          "Tracer study"             → 0.80-0.95
test_various_tracing       "Various tracing"          → 0.85-0.95
test_anterograde_tracer    "anterograde tracer (BDA)" → 0.85-0.95
test_retrograde_tracer     "retrograde tracer (FG)"   → 0.85-0.95
test_viral_tracing         "viral tracing (AAV)"      → 0.80-0.90
test_hrp_method            "HRP injection"            → 0.80-0.90
```

電気生理・光遺伝学系（5件）。方向性の推定はできるが、トレーサーほど直接的ではない。0.55〜0.75。

```
test_electrophysiology     "Electrophys"              → 0.55-0.75
test_patch_clamp           "patch clamp recording"    → 0.55-0.75
test_optogenetics          "optogenetics"             → 0.55-0.75
test_opto_chemo            "Opto/Chemo"               → 0.55-0.75
test_channelrhodopsin      "channelrhodopsin-..."     → 0.55-0.75
```

イメージング系（4件）。結合の存在は分かるが方向は原理的に曖昧。0.30〜0.55。

```
test_fmri                  "fMRI"                     → 0.30-0.50
test_resting_state_fmri    "resting-state func..."    → 0.30-0.50
test_dti_tractography      "DTI/tractography"         → 0.35-0.55
test_diffusion_tensor      "diffusion tensor..."      → 0.35-0.55
```

二次情報源（3件）。自分で実験していないので最低帯。0.15〜0.40。

```
test_review                "Review"                   → 0.20-0.40
test_unspecified           "Unspecified"              → 0.20-0.40
test_textbook              "Textbook reference"       → 0.15-0.35
```

#### PDER の文脈調整テスト（1件）

```
test_review_of_tracing
```

同じ "Tracer study" でも、実験論文に書かれているのかレビュー論文で紹介されているだけなのかで意味が違う。このテストは、レビュー文脈では実験文脈よりスコアが下がることを確認する。

これがないと何が起きるかというと、レビュー論文で「Smith (2020) は BDA を使って CA1→Sub の投射を報告した」と一文書いてあるだけのレコードが、Smith 本人の実験論文と同じ PDER を得てしまう。それはまずい。

#### PDER のエッジケース（4件）

```
test_empty_method          "" → 0.0
test_none_method           None → 0.0
test_unknown_method        知らない文字列 → 0〜1のどこか（クラッシュしない）
test_score_always_in_range 主要10手法が全て0〜1
```

空文字列と None の2つを分けてテストしているのは、Python では `""` と `None` の扱いが微妙に違う場面があるからだ。`if not method` で両方弾けるはずだが、念のため両方確認している。

`test_unknown_method` は「見たことのない文字列が来てもプログラムが死なない」ことの確認。PubMed からの自動抽出データには、こちらが想定していない表記の手法名がいくらでも出てくる。そのたびに例外が飛んでパイプラインが止まるようでは運用にならない。

#### CSI のテスト（8件）

CSI は論文の被引用評価。既知の有名論文はキャッシュに入っていて、未知の論文は発表年からヒューリスティックで推定する。

キャッシュの確認（2件）。

```
test_known_seminal_paper   "Amaral, 1991" → 0.80以上
test_known_high_impact     "Wei, 2016"    → 0.70以上
```

Amaral 1991 は海馬解剖学のランドマーク論文で、443回以上引用されている。これが 0.80 を下回ったら何かがおかしい。

ヒューリスティックの確認（2件）。

```
test_new_paper_default     "NewAuthor, 2025" → 0.45-0.55
test_older_paper_default   "OldAuthor, 1995" → 0.55-0.70
```

2025年の論文は引用が溜まっていないので判断できない。中立の 0.50 付近にする。1995年の論文が今もデータベースで参照されているなら、少なくとも否定はされていないと推定できるので、やや肯定寄りにする。この推定はかなり粗いが、API を叩けないときの fallback としては妥当だと考えている。

エラー入力（3件）と範囲保証（1件）。

```
test_invalid_reference     "author, year" → 0.20以下
test_error_reference       "#N/A"         → 0.20以下
test_empty_reference       ""             → 0.20以下
test_score_always_in_range 全入力が0〜1
```

"author, year" はスプレッドシートのプレースホルダーで、実際のデータに紛れ込んでいることがある（実データで確認済み）。これに高いスコアをつけたら困る。

#### CR 計算のテスト（9件）

ここがこのシステムのテストで一番大事な部分。

数学的性質（6件）。

```
test_all_ones              (1,1,1,1,1,1) → 1.0
test_all_zeros             (0,0,0,0,0,0) → 0.0
test_one_zero_makes_cr_zero  1つ0があれば全体0
test_symmetric             SourceとReceiverを入れ替えてもCR同値
test_monotonic_increase    スコアを上げればCRも上がる
test_cr_precision          0.3^6 = 0.000729 → 丸めて0.0007
```

`test_one_zero_makes_cr_zero` は掛け算なら自明だが、将来誰かが「0のときは0.01にする」みたいな「親切な」変更をしないとも限らない。そういう変更を入れたら、このテストが落ちて「本当にそれでいいのか？」と問いかけてくれる。テストにはそういうガードレールとしての役割がある。

**実データとの照合（3件）**。

```
test_known_example_from_data   Row 176: (1, 1, 0.95, 1, 0.5, 0.4) → 0.190
test_known_example_2           Row 319: (1, 1, 0.95, 1, 0.6, 0.8) → 0.456
test_known_example_3           Row 181: (1, 1, 0.95, 0.5, 0.5, 0.3) → 0.0712
```

WholeBIF_RDBv2 の実データから、CR が非ゼロの行を3つ取ってきて、プログラムの計算結果と突き合わせている。

なぜ3つだけかというと、既存データで CR が非ゼロの行がそもそも10行しかなかったからだ。うち3つを選んだ。スコアの組み合わせが異なるものを選んでいる（Row 176 は Taxon=0.5/PDER=0.4、Row 319 は Taxon=0.6/PDER=0.8、Row 181 は LitType=0.5 で他と違う）。

このテストが99件の中で最も価値が高いと思っている。理由は単純で、「本番のデータと一致する」以上に強い検証はないからだ。テストデータをどんなに工夫しても、本番データの複雑さには及ばない。

#### 手法間の順序テスト（5件）

```
test_tracing_higher_than_electrophys       Tracer > Electrophys
test_electrophys_higher_than_fmri          Electrophys > fMRI
test_fmri_higher_than_review               fMRI > Review
test_experimental_higher_than_review_same_method  同一手法で実験 > レビュー
test_optogenetics_comparable_to_electrophys      |Opto - Electro| < 0.15
```

個々のスコアが範囲に収まっていても、手法間の順序が逆転していたら意味がない。Tracer study が 0.80 で fMRI が 0.82 だったら、範囲チェックは通るが順序がおかしい。このテストはそういう事態を防ぐ。

最後の `test_optogenetics_comparable_to_electrophys` は、差が 0.15 以内であることの確認。光遺伝学と電気生理は方向性推定の能力が同程度なので、スコアも同程度であるべきだ。片方だけ極端に高い・低いと、特定の手法を使った論文が不当に評価されることになる。

---

### test_converter.py（31件）

コンバータのテスト。CSV の読み書きと変換処理を検証する。

#### CSV読み込み（11件）

参考文献の読み込みが5件、コネクションの読み込みが6件。

正直、ここのテストはあまり面白くない。「3件のCSVを読んだら3件取れるか」「DOIフィールドが正しく読めるか」「存在しないファイルでエラーが出るか」という、当たり前のことの確認だ。

ただ、当たり前のことが壊れるのがCSV処理の怖いところで、42列のCSVはヘッダを1列いじっただけで全フィールドがずれる。`test_reference_doi_loaded` と `test_connection_fields_parsed` はそのずれを検出するためにある。

```
test_load_valid_references             3件読めるか
test_reference_doi_loaded              DOI欄が正しいか（列ずれ検出）
test_reference_journal_loaded          ジャーナル名欄が正しいか（同上）
test_load_missing_file                 ないファイル → FileNotFoundError
test_load_references_missing_doi_warning  DOI欠損 → 警告

test_load_valid_connections            3件読めるか
test_connection_fields_parsed          sender_cid, receiver_cid等
test_connection_scores_parsed          数値フィールドのfloat変換
test_default_contributor_applied       空欄のContributorにデフォルト値が入るか
test_default_project_id_applied        同上（Project ID）
test_load_malformed_connections        必須欠損 → エラー2件以上
```

`test_default_contributor_applied` は運用上の理由で入れた。Google Spreadsheet からのエクスポートでは Contributor が空になっていることが多く、パイプライン側で埋める必要がある。

#### 参照整合性（2件）

```
test_all_refs_found        全参照が解決できる（正常系）
test_missing_ref_detected  "Nonexistent, 2099" を検出できるか
```

コネクションが「Smith, 2020 に基づく」と言っているのに、参考文献テーブルに Smith, 2020 がなかったら問題だ。参照が解決できないと CSI の計算で DOI が取れず、ヒューリスティックの推定値が使われる。Amaral 1991 のような高インパクト論文が 0.50（中立）にされてしまうと、CR が過小評価される。

#### 派生フィールド（4件）

```
test_combined_search           "CA1" + "Sub" → "CA1Sub"
test_reference_id_bracket      "Smith, 2020" → "[Smith, 2020]"
test_display_string            → "Sub (00/00) [Smith, 2020];"
test_journal_name_from_reference  → "Journal of Neuroscience"
```

文字列の結合や整形。地味だが、検索UIの表示に使われるフィールドなので、形式が違うと既存のフロントエンドが壊れる。

#### 文献種別スコア（7件）

```
test_experimental_results   "Experimental results" → 1.0
test_review                 "Review" → 0.8
test_textbook               "Textbook" → 0.5
test_hypothesis             "Hypothesis" → 0.3
test_error_type             "#Error: Reference ID" → 0.0
test_empty_type             "" → 0.0
test_case_insensitive       "review" == "REVIEW"
```

`test_case_insensitive` は入れておいてよかったテストの筆頭。Google Spreadsheet の手入力データでは "Review" と "review" と "REVIEW" が混在している。ここで大文字小文字を区別してしまうと、同じ種類の論文にバラバラなスコアがつく。

#### 変換パイプライン（3件）

```
test_full_conversion_dry_run           スコア計算なしの変換
test_full_conversion_with_credibility  スコア計算ありの変換
test_cr_computed_correctly             全レコードでCR = 6スコアの積
```

3番目が統合テストとして重要。個々の計算が正しくても、組み合わせたときに別の値を参照していた、というバグは統合テストでしか見つからない。

```python
def test_cr_computed_correctly(self, converter, ...):
    records = converter.convert(skip_credibility=False)
    for rec in records:
        expected = (rec.source_region_score * rec.receiver_region_score
                    * rec.citation_sentiment_index * rec.literature_type_score
                    * rec.taxon_score * rec.method_score_pder)
        assert abs(rec.credibility_rating - round(expected, 4)) < 0.001
```

#### CSV出力（4件）

```
test_write_csv                ファイルが生成されて3行あるか
test_csv_has_correct_headers  ヘッダが42列か
test_csv_roundtrip            書いたCSVを読み直して一致するか
test_report_generation        JSONレポートの内容確認
```

`test_csv_roundtrip` はかなり重要度が高い。出力した CSV は import_bdbra_into_wholebif.py で読み込まれる前提なので、「書いたものが読める」ことは保証しなければならない。BibTeX フィールドに改行やカンマが入っていてCSVが壊れる、というのは実際に起こり得る。

---

### test_pipeline.py（23件）

パイプライン全体のテスト。

#### E2E（5件）

```
test_full_pipeline_dry_run               正常完了するか
test_pipeline_output_csv_valid           出力の中身が正しいか
test_pipeline_report_generated           レポートが出るか
test_pipeline_with_missing_connections_file  ファイルなし → success=False
test_pipeline_duration_tracked           実行時間が記録されるか
```

`test_pipeline_with_missing_connections_file` はエラーハンドリングの確認。パイプラインが例外で死ぬのと、`success=False` を返して制御された形で終了するのとでは、運用上の扱いが全然違う。夜間バッチで走らせることを考えると、プロセスが異常終了してくれると困る。

#### バリデーションルール（8件）

```
test_valid_connection              正常データ → エラー0
test_missing_sender_cid            sender空 → エラー
test_missing_receiver_cid          receiver空 → エラー
test_missing_reference_id          reference空 → エラー
test_score_out_of_range            1.5 → エラー
test_negative_score                -0.1 → エラー
test_reference_id_format_warning   "Bad Format 2020" → 警告
test_valid_reference_id_formats    "O'Brien, 2019" → エラーにならない
```

最後のテストは、アポストロフィを含む名前がバリデーションに引っかからないことの確認。正規表現で Reference ID のフォーマットチェックをしているが、`O'Brien` や `D'Angelo` を弾いてしまうのはよくある失敗だ。WholeBIF-RDB には D'Angelo, 2013（小脳回路の論文）が実際に登録されている。

#### 参考文献バリデーション（3件）

```
test_valid_reference           正常 → エラー0
test_missing_reference_id      空 → エラー
test_missing_doi_warning       DOI欠損 → 警告（エラーではない）
```

DOI 欠損をエラーにしなかったのは判断。古い論文にはDOIがないことも多い。ただ CSI の API 計算には DOI が要るので、警告は出す。

#### データ整合性（3件）

```
test_cr_product_formula              実データ3件 + 零元のCR検証
test_pder_ordering_matches_existing  7手法の順序確認
test_literature_type_score_ordering  5種別の順序確認
```

`test_pder_ordering_matches_existing` は以下の順序が成り立つことを確認する。

```
Various tracing ≥ Tracer study ≥ Electrophys ≥ fMRI ≥ Review
```

この順序は、test_credibility.py のPDER個別テストが全部通れば自動的に成り立つはず……だが、保証はない。個別テストでは「Tracer study は 0.80〜0.95」「fMRI は 0.30〜0.50」と確認しているので、普通は Tracer > fMRI になるが、レンジが重なっている手法ペアでは逆転し得る。だから明示的に順序テストを書いている。

#### シリアル化（4件）

```
test_to_row_length         to_row() → 42要素
test_from_row_roundtrip    to_row() → from_row() で一致
test_from_row_short_row    4列の行 → クラッシュしない
test_from_row_invalid_float  "not_a_number" → 0.0
```

`test_from_row_short_row` と `test_from_row_invalid_float` は、Google Spreadsheet エクスポートの汚さ対策。末尾の空列が切り落とされる、数式エラーが文字列で残っている、というのは日常的に起きる。ここで例外が飛んで止まるようでは使い物にならない。

---

## テストの実行

```bash
pip install pytest pytest-cov requests
cd wholebif_pipeline
python -m pytest tests/ -v
```

`99 passed` が出ればOK。1件でも `FAILED` があったらコードを変更してはいけない。

特定のテストだけ回したいときは：

```bash
# CRの実データ照合だけ
python -m pytest tests/test_credibility.py::TestCRCalculation -v

# "pder" を含むテストだけ
python -m pytest tests/ -k "pder" -v

# カバレッジ確認
python -m pytest tests/ --cov=src --cov-report=term-missing
```

---

## 変更を加えるときの注意

PDER_RULES にエントリを足したら、範囲テストと順序テストを追加すること。順序テストを忘れると、新しい手法が既存の手法との大小関係を壊していても気づけない。

CR の計算方法を変更する場合は慎重に。`test_known_example_from_data` 等の実データ照合テストの期待値を変えることになるが、それは「既存データベースとの互換性を切る」ことを意味する。本当にそれでいいのか、データベース側の既存レコードも更新するのか、確認してから進めること。

テストのサンプルデータ（conftest.py）を変えると、そのデータに依存する全テストに波及する。テストが落ちたとき、テストの期待値がおかしいのか、サンプルデータの変更が意図通りなのか、区別がつきにくくなる。サンプルデータはできるだけ触らないほうがいい。

---

## 全99件テスト一覧

### test_credibility.py（45件）

| # | クラス | テスト名 |
|:--|:------|:--------|
| 1 | TestPDERHeuristic | test_tracer_study |
| 2 | TestPDERHeuristic | test_various_tracing |
| 3 | TestPDERHeuristic | test_anterograde_tracer |
| 4 | TestPDERHeuristic | test_retrograde_tracer |
| 5 | TestPDERHeuristic | test_viral_tracing |
| 6 | TestPDERHeuristic | test_hrp_method |
| 7 | TestPDERHeuristic | test_electrophysiology |
| 8 | TestPDERHeuristic | test_patch_clamp |
| 9 | TestPDERHeuristic | test_optogenetics |
| 10 | TestPDERHeuristic | test_opto_chemo |
| 11 | TestPDERHeuristic | test_channelrhodopsin |
| 12 | TestPDERHeuristic | test_fmri |
| 13 | TestPDERHeuristic | test_resting_state_fmri |
| 14 | TestPDERHeuristic | test_dti_tractography |
| 15 | TestPDERHeuristic | test_diffusion_tensor |
| 16 | TestPDERHeuristic | test_review |
| 17 | TestPDERHeuristic | test_unspecified |
| 18 | TestPDERHeuristic | test_textbook |
| 19 | TestPDERHeuristic | test_review_of_tracing |
| 20 | TestPDERHeuristic | test_empty_method |
| 21 | TestPDERHeuristic | test_none_method |
| 22 | TestPDERHeuristic | test_unknown_method |
| 23 | TestPDERHeuristic | test_score_always_in_range |
| 24 | TestCSIHeuristic | test_known_seminal_paper |
| 25 | TestCSIHeuristic | test_known_high_impact |
| 26 | TestCSIHeuristic | test_new_paper_default |
| 27 | TestCSIHeuristic | test_older_paper_default |
| 28 | TestCSIHeuristic | test_invalid_reference |
| 29 | TestCSIHeuristic | test_error_reference |
| 30 | TestCSIHeuristic | test_empty_reference |
| 31 | TestCSIHeuristic | test_score_always_in_range |
| 32 | TestCRCalculation | test_all_ones |
| 33 | TestCRCalculation | test_all_zeros |
| 34 | TestCRCalculation | test_one_zero_makes_cr_zero |
| 35 | TestCRCalculation | test_known_example_from_data |
| 36 | TestCRCalculation | test_known_example_2 |
| 37 | TestCRCalculation | test_known_example_3 |
| 38 | TestCRCalculation | test_symmetric |
| 39 | TestCRCalculation | test_cr_precision |
| 40 | TestCRCalculation | test_monotonic_increase |
| 41 | TestPDERMethodOrdering | test_tracing_higher_than_electrophys |
| 42 | TestPDERMethodOrdering | test_electrophys_higher_than_fmri |
| 43 | TestPDERMethodOrdering | test_fmri_higher_than_review |
| 44 | TestPDERMethodOrdering | test_experimental_higher_than_review_same_method |
| 45 | TestPDERMethodOrdering | test_optogenetics_comparable_to_electrophys |

### test_converter.py（31件）

| # | クラス | テスト名 |
|:--|:------|:--------|
| 46 | TestLoadReferences | test_load_valid_references |
| 47 | TestLoadReferences | test_reference_doi_loaded |
| 48 | TestLoadReferences | test_reference_journal_loaded |
| 49 | TestLoadReferences | test_load_missing_file |
| 50 | TestLoadReferences | test_load_references_missing_doi_warning |
| 51 | TestLoadConnections | test_load_valid_connections |
| 52 | TestLoadConnections | test_connection_fields_parsed |
| 53 | TestLoadConnections | test_connection_scores_parsed |
| 54 | TestLoadConnections | test_default_contributor_applied |
| 55 | TestLoadConnections | test_default_project_id_applied |
| 56 | TestLoadConnections | test_load_malformed_connections |
| 57 | TestCrossValidation | test_all_refs_found |
| 58 | TestCrossValidation | test_missing_ref_detected |
| 59 | TestDerivedFields | test_combined_search |
| 60 | TestDerivedFields | test_reference_id_bracket |
| 61 | TestDerivedFields | test_display_string |
| 62 | TestDerivedFields | test_journal_name_from_reference |
| 63 | TestLiteratureTypeScore | test_experimental_results |
| 64 | TestLiteratureTypeScore | test_review |
| 65 | TestLiteratureTypeScore | test_textbook |
| 66 | TestLiteratureTypeScore | test_hypothesis |
| 67 | TestLiteratureTypeScore | test_error_type |
| 68 | TestLiteratureTypeScore | test_empty_type |
| 69 | TestLiteratureTypeScore | test_case_insensitive |
| 70 | TestFullConversion | test_full_conversion_dry_run |
| 71 | TestFullConversion | test_full_conversion_with_credibility |
| 72 | TestFullConversion | test_cr_computed_correctly |
| 73 | TestBdbraCsvOutput | test_write_csv |
| 74 | TestBdbraCsvOutput | test_csv_has_correct_headers |
| 75 | TestBdbraCsvOutput | test_csv_roundtrip |
| 76 | TestBdbraCsvOutput | test_report_generation |

### test_pipeline.py（23件）

| # | クラス | テスト名 |
|:--|:------|:--------|
| 77 | TestPipelineE2E | test_full_pipeline_dry_run |
| 78 | TestPipelineE2E | test_pipeline_output_csv_valid |
| 79 | TestPipelineE2E | test_pipeline_report_generated |
| 80 | TestPipelineE2E | test_pipeline_with_missing_connections_file |
| 81 | TestPipelineE2E | test_pipeline_duration_tracked |
| 82 | TestValidationRules | test_valid_connection |
| 83 | TestValidationRules | test_missing_sender_cid |
| 84 | TestValidationRules | test_missing_receiver_cid |
| 85 | TestValidationRules | test_missing_reference_id |
| 86 | TestValidationRules | test_score_out_of_range |
| 87 | TestValidationRules | test_negative_score |
| 88 | TestValidationRules | test_reference_id_format_warning |
| 89 | TestValidationRules | test_valid_reference_id_formats |
| 90 | TestReferenceValidation | test_valid_reference |
| 91 | TestReferenceValidation | test_missing_reference_id |
| 92 | TestReferenceValidation | test_missing_doi_warning |
| 93 | TestDataIntegrity | test_cr_product_formula |
| 94 | TestDataIntegrity | test_pder_ordering_matches_existing |
| 95 | TestDataIntegrity | test_literature_type_score_ordering |
| 96 | TestConnectionRecordSerialization | test_to_row_length |
| 97 | TestConnectionRecordSerialization | test_from_row_roundtrip |
| 98 | TestConnectionRecordSerialization | test_from_row_short_row |
| 99 | TestConnectionRecordSerialization | test_from_row_invalid_float |
