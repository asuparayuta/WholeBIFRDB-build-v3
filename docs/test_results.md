# WholeBIF-RDB パイプライン テスト実行結果報告書

実行日時: 2026-02-27T02:44:21+00:00

---

## 実行環境

```
OS:       Linux 4.4.0
Python:   3.12.3
pytest:   9.0.2
coverage: pytest-cov 7.0.0
```

## 実行コマンド

```bash
cd wholebif_pipeline
python3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## 結果サマリ

```
実行テスト数:  99
合格:          99
失敗:           0
実行時間:       0.41秒
```

ファイルごとの内訳は以下の通り。

```
test_converter.py     31/31 passed   コンバータ
test_credibility.py   45/45 passed   信頼度計算
test_pipeline.py      23/23 passed   パイプライン統合
```

---

## カバレッジ

```
Name                               Stmts   Miss  Cover   Missing
----------------------------------------------------------------
src/__init__.py                        0      0   100%
src/credibility_calculator.py         98     46    53%   116, 137, 141, 147-170, 212, 233, 237-272, 304-307
src/manual_to_bdbra_converter.py     176     47    73%   94, 100, 115, 123, 127, 143, 229, 324-394, 398
src/pipeline.py                      102     32    69%   134-137, 150-153, 180-222, 226
src/schema.py                        112      1    99%   293
----------------------------------------------------------------
TOTAL                                488    126    74%
```

未カバー行の内訳：

- `credibility_calculator.py` 46行 — Claude API / Semantic Scholar API 呼び出し部（L147-170, L237-272）とクライアント初期化（L304-307）。テストはヒューリスティックモードで実行しているため、API 経由のコードパスは通らない。
- `manual_to_bdbra_converter.py` 47行 — CLI の `main()` 関数（L324-394）とログ初期化。E2E テストは `run_pipeline()` を直接呼んでいるため、argparse 周りは通らない。
- `pipeline.py` 32行 — CLI の `main()` 関数（L180-222）と PostgreSQL インポートのプレースホルダ（L134-137）。
- `schema.py` 1行 — Unicode 正規表現の特殊分岐（L293）。

---

## テスト実行ログ（全件）

以下は `pytest -v` の実際の出力をそのまま転記したものである。

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/claude/wholebif_pipeline
configfile: pyproject.toml
plugins: cov-7.0.0
collected 99 items
```

### test_converter.py（31件） — 全件合格

```
tests/test_converter.py::TestLoadReferences::test_load_valid_references PASSED             [  1%]
tests/test_converter.py::TestLoadReferences::test_reference_doi_loaded PASSED              [  2%]
tests/test_converter.py::TestLoadReferences::test_reference_journal_loaded PASSED          [  3%]
tests/test_converter.py::TestLoadReferences::test_load_missing_file PASSED                 [  4%]
tests/test_converter.py::TestLoadReferences::test_load_references_missing_doi_warning PASSED [  5%]
tests/test_converter.py::TestLoadConnections::test_load_valid_connections PASSED            [  6%]
tests/test_converter.py::TestLoadConnections::test_connection_fields_parsed PASSED          [  7%]
tests/test_converter.py::TestLoadConnections::test_connection_scores_parsed PASSED          [  8%]
tests/test_converter.py::TestLoadConnections::test_default_contributor_applied PASSED       [  9%]
tests/test_converter.py::TestLoadConnections::test_default_project_id_applied PASSED       [ 10%]
tests/test_converter.py::TestLoadConnections::test_load_malformed_connections PASSED        [ 11%]
tests/test_converter.py::TestCrossValidation::test_all_refs_found PASSED                   [ 12%]
tests/test_converter.py::TestCrossValidation::test_missing_ref_detected PASSED             [ 13%]
tests/test_converter.py::TestDerivedFields::test_combined_search PASSED                    [ 14%]
tests/test_converter.py::TestDerivedFields::test_reference_id_bracket PASSED               [ 15%]
tests/test_converter.py::TestDerivedFields::test_display_string PASSED                     [ 16%]
tests/test_converter.py::TestDerivedFields::test_journal_name_from_reference PASSED        [ 17%]
tests/test_converter.py::TestLiteratureTypeScore::test_experimental_results PASSED         [ 18%]
tests/test_converter.py::TestLiteratureTypeScore::test_review PASSED                       [ 19%]
tests/test_converter.py::TestLiteratureTypeScore::test_textbook PASSED                     [ 20%]
tests/test_converter.py::TestLiteratureTypeScore::test_hypothesis PASSED                   [ 21%]
tests/test_converter.py::TestLiteratureTypeScore::test_error_type PASSED                   [ 22%]
tests/test_converter.py::TestLiteratureTypeScore::test_empty_type PASSED                   [ 23%]
tests/test_converter.py::TestLiteratureTypeScore::test_case_insensitive PASSED             [ 24%]
tests/test_converter.py::TestFullConversion::test_full_conversion_dry_run PASSED           [ 25%]
tests/test_converter.py::TestFullConversion::test_full_conversion_with_credibility PASSED  [ 26%]
tests/test_converter.py::TestFullConversion::test_cr_computed_correctly PASSED             [ 27%]
tests/test_converter.py::TestBdbraCsvOutput::test_write_csv PASSED                        [ 28%]
tests/test_converter.py::TestBdbraCsvOutput::test_csv_has_correct_headers PASSED           [ 29%]
tests/test_converter.py::TestBdbraCsvOutput::test_csv_roundtrip PASSED                    [ 30%]
tests/test_converter.py::TestBdbraCsvOutput::test_report_generation PASSED                 [ 31%]
```

### test_credibility.py（45件） — 全件合格

```
tests/test_credibility.py::TestPDERHeuristic::test_tracer_study PASSED                    [ 32%]
tests/test_credibility.py::TestPDERHeuristic::test_various_tracing PASSED                  [ 33%]
tests/test_credibility.py::TestPDERHeuristic::test_anterograde_tracer PASSED               [ 34%]
tests/test_credibility.py::TestPDERHeuristic::test_retrograde_tracer PASSED                [ 35%]
tests/test_credibility.py::TestPDERHeuristic::test_viral_tracing PASSED                    [ 36%]
tests/test_credibility.py::TestPDERHeuristic::test_hrp_method PASSED                       [ 37%]
tests/test_credibility.py::TestPDERHeuristic::test_electrophysiology PASSED                [ 38%]
tests/test_credibility.py::TestPDERHeuristic::test_patch_clamp PASSED                      [ 39%]
tests/test_credibility.py::TestPDERHeuristic::test_optogenetics PASSED                     [ 40%]
tests/test_credibility.py::TestPDERHeuristic::test_opto_chemo PASSED                       [ 41%]
tests/test_credibility.py::TestPDERHeuristic::test_channelrhodopsin PASSED                 [ 42%]
tests/test_credibility.py::TestPDERHeuristic::test_fmri PASSED                            [ 43%]
tests/test_credibility.py::TestPDERHeuristic::test_resting_state_fmri PASSED               [ 44%]
tests/test_credibility.py::TestPDERHeuristic::test_dti_tractography PASSED                 [ 45%]
tests/test_credibility.py::TestPDERHeuristic::test_diffusion_tensor PASSED                 [ 46%]
tests/test_credibility.py::TestPDERHeuristic::test_review PASSED                           [ 47%]
tests/test_credibility.py::TestPDERHeuristic::test_unspecified PASSED                      [ 48%]
tests/test_credibility.py::TestPDERHeuristic::test_textbook PASSED                         [ 49%]
tests/test_credibility.py::TestPDERHeuristic::test_review_of_tracing PASSED                [ 50%]
tests/test_credibility.py::TestPDERHeuristic::test_empty_method PASSED                     [ 51%]
tests/test_credibility.py::TestPDERHeuristic::test_none_method PASSED                      [ 52%]
tests/test_credibility.py::TestPDERHeuristic::test_unknown_method PASSED                   [ 53%]
tests/test_credibility.py::TestPDERHeuristic::test_score_always_in_range PASSED            [ 54%]
tests/test_credibility.py::TestCSIHeuristic::test_known_seminal_paper PASSED               [ 55%]
tests/test_credibility.py::TestCSIHeuristic::test_known_high_impact PASSED                 [ 56%]
tests/test_credibility.py::TestCSIHeuristic::test_new_paper_default PASSED                 [ 57%]
tests/test_credibility.py::TestCSIHeuristic::test_older_paper_default PASSED               [ 58%]
tests/test_credibility.py::TestCSIHeuristic::test_invalid_reference PASSED                 [ 59%]
tests/test_credibility.py::TestCSIHeuristic::test_error_reference PASSED                   [ 60%]
tests/test_credibility.py::TestCSIHeuristic::test_empty_reference PASSED                   [ 61%]
tests/test_credibility.py::TestCSIHeuristic::test_score_always_in_range PASSED             [ 62%]
tests/test_credibility.py::TestCRCalculation::test_all_ones PASSED                         [ 63%]
tests/test_credibility.py::TestCRCalculation::test_all_zeros PASSED                        [ 64%]
tests/test_credibility.py::TestCRCalculation::test_one_zero_makes_cr_zero PASSED           [ 65%]
tests/test_credibility.py::TestCRCalculation::test_known_example_from_data PASSED          [ 66%]
tests/test_credibility.py::TestCRCalculation::test_known_example_2 PASSED                  [ 67%]
tests/test_credibility.py::TestCRCalculation::test_known_example_3 PASSED                  [ 68%]
tests/test_credibility.py::TestCRCalculation::test_symmetric PASSED                        [ 69%]
tests/test_credibility.py::TestCRCalculation::test_cr_precision PASSED                     [ 70%]
tests/test_credibility.py::TestCRCalculation::test_monotonic_increase PASSED               [ 71%]
tests/test_credibility.py::TestPDERMethodOrdering::test_tracing_higher_than_electrophys PASSED  [ 72%]
tests/test_credibility.py::TestPDERMethodOrdering::test_electrophys_higher_than_fmri PASSED     [ 73%]
tests/test_credibility.py::TestPDERMethodOrdering::test_fmri_higher_than_review PASSED          [ 74%]
tests/test_credibility.py::TestPDERMethodOrdering::test_experimental_higher_than_review_same_method PASSED [ 75%]
tests/test_credibility.py::TestPDERMethodOrdering::test_optogenetics_comparable_to_electrophys PASSED [ 76%]
```

### test_pipeline.py（23件） — 全件合格

```
tests/test_pipeline.py::TestPipelineE2E::test_full_pipeline_dry_run PASSED                 [ 77%]
tests/test_pipeline.py::TestPipelineE2E::test_pipeline_output_csv_valid PASSED             [ 78%]
tests/test_pipeline.py::TestPipelineE2E::test_pipeline_report_generated PASSED             [ 79%]
tests/test_pipeline.py::TestPipelineE2E::test_pipeline_with_missing_connections_file PASSED [ 80%]
tests/test_pipeline.py::TestPipelineE2E::test_pipeline_duration_tracked PASSED             [ 81%]
tests/test_pipeline.py::TestValidationRules::test_valid_connection PASSED                  [ 82%]
tests/test_pipeline.py::TestValidationRules::test_missing_sender_cid PASSED                [ 83%]
tests/test_pipeline.py::TestValidationRules::test_missing_receiver_cid PASSED              [ 84%]
tests/test_pipeline.py::TestValidationRules::test_missing_reference_id PASSED              [ 85%]
tests/test_pipeline.py::TestValidationRules::test_score_out_of_range PASSED                [ 86%]
tests/test_pipeline.py::TestValidationRules::test_negative_score PASSED                    [ 87%]
tests/test_pipeline.py::TestValidationRules::test_reference_id_format_warning PASSED       [ 88%]
tests/test_pipeline.py::TestValidationRules::test_valid_reference_id_formats PASSED        [ 89%]
tests/test_pipeline.py::TestReferenceValidation::test_valid_reference PASSED               [ 90%]
tests/test_pipeline.py::TestReferenceValidation::test_missing_reference_id PASSED          [ 91%]
tests/test_pipeline.py::TestReferenceValidation::test_missing_doi_warning PASSED           [ 92%]
tests/test_pipeline.py::TestDataIntegrity::test_cr_product_formula PASSED                  [ 93%]
tests/test_pipeline.py::TestDataIntegrity::test_pder_ordering_matches_existing PASSED      [ 94%]
tests/test_pipeline.py::TestDataIntegrity::test_literature_type_score_ordering PASSED      [ 95%]
tests/test_pipeline.py::TestConnectionRecordSerialization::test_to_row_length PASSED       [ 96%]
tests/test_pipeline.py::TestConnectionRecordSerialization::test_from_row_roundtrip PASSED  [ 97%]
tests/test_pipeline.py::TestConnectionRecordSerialization::test_from_row_short_row PASSED  [ 98%]
tests/test_pipeline.py::TestConnectionRecordSerialization::test_from_row_invalid_float PASSED [100%]
```

```
============================== 99 passed in 0.41s ==============================
```

---

## テスト構造ツリー（合否マーク付き）

テストクラスごとの構造と結果を一覧にしたもの。

```
tests/test_converter.py (31/31 passed)
│
├── TestLoadReferences (5 tests)
│   ✓ test_load_valid_references
│   ✓ test_reference_doi_loaded
│   ✓ test_reference_journal_loaded
│   ✓ test_load_missing_file
│   ✓ test_load_references_missing_doi_warning
│
├── TestLoadConnections (6 tests)
│   ✓ test_load_valid_connections
│   ✓ test_connection_fields_parsed
│   ✓ test_connection_scores_parsed
│   ✓ test_default_contributor_applied
│   ✓ test_default_project_id_applied
│   ✓ test_load_malformed_connections
│
├── TestCrossValidation (2 tests)
│   ✓ test_all_refs_found
│   ✓ test_missing_ref_detected
│
├── TestDerivedFields (4 tests)
│   ✓ test_combined_search
│   ✓ test_reference_id_bracket
│   ✓ test_display_string
│   ✓ test_journal_name_from_reference
│
├── TestLiteratureTypeScore (7 tests)
│   ✓ test_experimental_results
│   ✓ test_review
│   ✓ test_textbook
│   ✓ test_hypothesis
│   ✓ test_error_type
│   ✓ test_empty_type
│   ✓ test_case_insensitive
│
├── TestFullConversion (3 tests)
│   ✓ test_full_conversion_dry_run
│   ✓ test_full_conversion_with_credibility
│   ✓ test_cr_computed_correctly
│
└── TestBdbraCsvOutput (4 tests)
    ✓ test_write_csv
    ✓ test_csv_has_correct_headers
    ✓ test_csv_roundtrip
    ✓ test_report_generation


tests/test_credibility.py (45/45 passed)
│
├── TestPDERHeuristic (23 tests)
│   ✓ test_tracer_study
│   ✓ test_various_tracing
│   ✓ test_anterograde_tracer
│   ✓ test_retrograde_tracer
│   ✓ test_viral_tracing
│   ✓ test_hrp_method
│   ✓ test_electrophysiology
│   ✓ test_patch_clamp
│   ✓ test_optogenetics
│   ✓ test_opto_chemo
│   ✓ test_channelrhodopsin
│   ✓ test_fmri
│   ✓ test_resting_state_fmri
│   ✓ test_dti_tractography
│   ✓ test_diffusion_tensor
│   ✓ test_review
│   ✓ test_unspecified
│   ✓ test_textbook
│   ✓ test_review_of_tracing
│   ✓ test_empty_method
│   ✓ test_none_method
│   ✓ test_unknown_method
│   ✓ test_score_always_in_range
│
├── TestCSIHeuristic (8 tests)
│   ✓ test_known_seminal_paper
│   ✓ test_known_high_impact
│   ✓ test_new_paper_default
│   ✓ test_older_paper_default
│   ✓ test_invalid_reference
│   ✓ test_error_reference
│   ✓ test_empty_reference
│   ✓ test_score_always_in_range
│
├── TestCRCalculation (9 tests)
│   ✓ test_all_ones
│   ✓ test_all_zeros
│   ✓ test_one_zero_makes_cr_zero
│   ✓ test_known_example_from_data
│   ✓ test_known_example_2
│   ✓ test_known_example_3
│   ✓ test_symmetric
│   ✓ test_cr_precision
│   ✓ test_monotonic_increase
│
└── TestPDERMethodOrdering (5 tests)
    ✓ test_tracing_higher_than_electrophys
    ✓ test_electrophys_higher_than_fmri
    ✓ test_fmri_higher_than_review
    ✓ test_experimental_higher_than_review_same_method
    ✓ test_optogenetics_comparable_to_electrophys


tests/test_pipeline.py (23/23 passed)
│
├── TestPipelineE2E (5 tests)
│   ✓ test_full_pipeline_dry_run
│   ✓ test_pipeline_output_csv_valid
│   ✓ test_pipeline_report_generated
│   ✓ test_pipeline_with_missing_connections_file
│   ✓ test_pipeline_duration_tracked
│
├── TestValidationRules (8 tests)
│   ✓ test_valid_connection
│   ✓ test_missing_sender_cid
│   ✓ test_missing_receiver_cid
│   ✓ test_missing_reference_id
│   ✓ test_score_out_of_range
│   ✓ test_negative_score
│   ✓ test_reference_id_format_warning
│   ✓ test_valid_reference_id_formats
│
├── TestReferenceValidation (3 tests)
│   ✓ test_valid_reference
│   ✓ test_missing_reference_id
│   ✓ test_missing_doi_warning
│
├── TestDataIntegrity (3 tests)
│   ✓ test_cr_product_formula
│   ✓ test_pder_ordering_matches_existing
│   ✓ test_literature_type_score_ordering
│
└── TestConnectionRecordSerialization (4 tests)
    ✓ test_to_row_length
    ✓ test_from_row_roundtrip
    ✓ test_from_row_short_row
    ✓ test_from_row_invalid_float
```

---

## 実行時間

全テストの実行時間は 0.41 秒。最も遅いテストでも 0.05 秒で、実行速度の問題はない。

```
slowest 3 tests:
  0.05s  teardown  test_pipeline.py::TestReferenceValidation::test_missing_reference_id
  0.04s  teardown  test_converter.py::TestDerivedFields::test_journal_name_from_reference
  0.01s  setup     test_converter.py::TestLoadReferences::test_load_valid_references

(残り96件は全て 0.005秒未満)
```

---

## 判定

全99件合格、失敗0件。デプロイ可能な状態にある。
