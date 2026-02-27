"""
WholeBIF-RDB: Method Score (PDER) スコアリングプログラム
=====================================================
Claude API を使用して、Measurement method (実験手法) の
「有向性を含む神経投射 (Projection Direction) の計測における有効性」
を最大1.0でスコアリングする。

PDER = Projection Direction Evaluation Rating

スコアリング基準:
- 1.0: 方向性を完全に特定できる手法 (理論上の最大値)
- 0.8-0.9: 順行性/逆行性トレーサー等、方向性の直接計測が可能
- 0.6-0.7: 電気生理学・光遺伝学等、間接的に方向性を推定可能
- 0.4-0.5: fMRI・DTI等、機能的結合は測れるが方向性は限定的
- 0.2-0.3: レビュー・教科書等、二次情報源
- 0.0: 評価不能

使い方:
    pip install anthropic pandas --break-system-packages
    export ANTHROPIC_API_KEY="your-api-key"
    python score_pder_with_claude_api.py --input input.csv --output output.csv
"""

import argparse
import csv
import json
import os
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("anthropic パッケージをインストールしてください: pip install anthropic")
    raise


# ============================================================
# 1. スコアリング用プロンプトテンプレート
# ============================================================

SYSTEM_PROMPT = """\
あなたは神経科学の専門家です。脳の神経投射（neural projection）データベースの品質評価を行っています。

## タスク
与えられた実験手法（Measurement method）について、「有向性を含む神経投射を計測する上での有効性」をスコアリングしてください。

## スコアリング基準 (PDER: Projection Direction Evaluation Rating)
- **0.90〜0.95**: 順行性トレーサー(anterograde tracer)、逆行性トレーサー(retrograde tracer)、\
トランスシナプティックトレーシング(trans-synaptic tracing)など、投射の方向性を直接的かつ精密に計測できる手法。\
これらの手法は二つの脳領域間の方向付き投射を直接証明できるため、最高スコアに近い値を付与する。
- **0.80〜0.85**: 微量電気泳動注入(microiontophoretic injections)、ウイルスベクタートレーシングなど、\
トレーサー送達法として方向性を高精度で特定できる手法
- **0.60〜0.70**: 電気生理学(electrophysiology)、光遺伝学(optogenetics)など、\
刺激-応答パターンから方向性を推定できる手法
- **0.40〜0.50**: fMRI、DTI/tractography、拡散テンソル画像など、\
機能的・構造的結合を測れるが方向性の特定は限定的な手法
- **0.30〜0.35**: レビュー論文、教科書、データ記述など、\
一次実験データではなく二次情報源からの報告
- **0.15〜0.20**: 仮説段階や洞察のみの記述、参照IDエラー

## 重要な参考情報
既存のスコアリング例:
- "Various tracing" (複数のトレーシング手法を含むレビュー) → 0.9
- "Tracer study" → 0.5
- "Electrophys" → 0.5
- "Opto/Chemo" → 0.5
- "DTI/tractography" → 0.5
- "Unspecified" (手法不明) → 0.5
- "Review" (レビュー論文) → 手法に応じて変動（下記参照）
- "Anatomical imaging/clearing" → 0.5

## レビュー・教科書のスコアリング指針
レビューや教科書は一律に低スコアにせず、「元の実験手法の質」を反映してスコアリングしてください：
- レビューがtract-tracing研究を主にまとめている → 0.65〜0.70
- レビューがtract-tracing + 電気生理の混合 → 0.55〜0.65
- レビューがfMRI/イメージング + 電気生理の混合 → 0.45〜0.55
- レビューがfMRI中心 → 0.40〜0.50
- 教科書（tract-tracing/電気生理に基づく） → 0.35〜0.40
- 概説的・定性的記述のみ → 0.25〜0.35

## Measurement Method 追記ルール
Method欄が空の場合、スコアと同時にMethodも記入してください：
- 一次研究: 具体的な手法名を記入 (例: "Anterograde tracer (PHA-L)")
- レビュー: "Review based on [元の手法] ([トピック])" 形式で記入
- 教科書: "Textbook based on [元の手法] ([書名/トピック])" 形式で記入

## 出力形式
JSONで回答してください。余計なテキストは不要です。
"""

USER_PROMPT_TEMPLATE = """\
以下の神経投射データベースエントリについて、Method score (PDER) を評価してください。

参考文献: {reference}
文献タイプ: {literature_type}
実験手法: {method}
生物種: {taxon}
送信領域: {sender}
受信領域: {receiver}

もし実験手法(Measurement method)が空欄の場合は、参考文献名や文献タイプから推測してスコアリングしてください。
参考文献の著者名と年から、その論文で使われていた可能性が高い実験手法を推定し、それに基づいてスコアリングしてください。

以下のJSON形式で回答してください:
{{
  "score": <0.0〜1.0の数値>,
  "inferred_method": "<推定された実験手法（空欄だった場合）>",
  "reasoning": "<スコアの根拠を1-2文で>"
}}
"""

# ============================================================
# 2. バッチスコアリング用プロンプト（複数エントリを一括処理）
# ============================================================

BATCH_USER_PROMPT_TEMPLATE = """\
以下の神経投射データベースエントリ群について、それぞれの Method score (PDER) を評価してください。

{entries_text}

以下のJSON形式で回答してください（余計なテキストは不要、JSONのみ出力）:
{{
  "results": [
    {{
      "reference": "<参考文献>",
      "score": <0.0〜1.0の数値>,
      "inferred_method": "<推定された実験手法>",
      "reasoning": "<根拠を1文で>"
    }},
    ...
  ]
}}
"""


# ============================================================
# 3. メイン処理クラス
# ============================================================

class PDERScorer:
    """Claude API を使って PDER スコアを算出するクラス"""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.cache = {}  # reference -> score result のキャッシュ

    def score_single(self, reference: str, literature_type: str, method: str,
                     taxon: str, sender: str, receiver: str) -> dict:
        """単一エントリをスコアリング"""
        cache_key = f"{reference}|{method}|{literature_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        user_prompt = USER_PROMPT_TEMPLATE.format(
            reference=reference or "(なし)",
            literature_type=literature_type or "(なし)",
            method=method or "(空欄)",
            taxon=taxon or "(不明)",
            sender=sender,
            receiver=receiver,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text.strip()
            # JSON パース（```json ... ``` 対応）
            text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
        except json.JSONDecodeError:
            result = {"score": 0.3, "inferred_method": "parse_error", "reasoning": "JSON解析エラー"}
        except Exception as e:
            result = {"score": 0.3, "inferred_method": "api_error", "reasoning": str(e)}

        self.cache[cache_key] = result
        return result

    def score_batch(self, entries: list[dict], batch_size: int = 10) -> list[dict]:
        """
        複数エントリを一括スコアリング（API呼び出し回数を削減）

        Parameters
        ----------
        entries : list[dict]
            各要素は {reference, literature_type, method, taxon, sender, receiver} を持つ dict
        batch_size : int
            1回のAPI呼び出しで処理するエントリ数（10〜20推奨）

        Returns
        -------
        list[dict]
            各要素は {score, inferred_method, reasoning} を持つ dict
        """
        all_results = []

        for i in range(0, len(entries), batch_size):
            batch = entries[i:i + batch_size]
            entries_text = ""
            for j, entry in enumerate(batch):
                entries_text += f"""
エントリ {j + 1}:
  参考文献: {entry.get('reference', '(なし)')}
  文献タイプ: {entry.get('literature_type', '(なし)')}
  実験手法: {entry.get('method', '(空欄)')}
  生物種: {entry.get('taxon', '(不明)')}
  送信領域: {entry.get('sender', '')}
  受信領域: {entry.get('receiver', '')}
"""
            user_prompt = BATCH_USER_PROMPT_TEMPLATE.format(entries_text=entries_text)

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = response.content[0].text.strip()
                text = text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                batch_results = parsed.get("results", [])
            except Exception as e:
                print(f"  バッチ {i // batch_size + 1} でエラー: {e}")
                batch_results = [
                    {"score": 0.3, "inferred_method": "batch_error", "reasoning": str(e)}
                    for _ in batch
                ]

            # バッチ結果数の補正
            while len(batch_results) < len(batch):
                batch_results.append(
                    {"score": 0.3, "inferred_method": "missing", "reasoning": "結果不足"}
                )

            all_results.extend(batch_results[:len(batch)])

            # レートリミット対策
            if i + batch_size < len(entries):
                time.sleep(1)

            print(f"  処理済み: {min(i + batch_size, len(entries))}/{len(entries)}")

        return all_results

    def score_by_unique_reference(self, entries: list[dict]) -> dict:
        """
        ユニーク参考文献ごとにスコアリングし、同一参考文献は同一スコアを適用

        Returns
        -------
        dict
            {cache_key: {score, inferred_method, reasoning}} の辞書
        """
        # ユニークな (reference, method, literature_type) を抽出
        unique_entries = {}
        for entry in entries:
            key = f"{entry['reference']}|{entry['method']}|{entry['literature_type']}"
            if key not in unique_entries:
                unique_entries[key] = entry

        print(f"ユニークエントリ数: {len(unique_entries)} / 全{len(entries)}行")

        unique_list = list(unique_entries.values())
        results = self.score_batch(unique_list, batch_size=10)

        # キャッシュに保存
        score_map = {}
        for entry, result in zip(unique_list, results):
            key = f"{entry['reference']}|{entry['method']}|{entry['literature_type']}"
            score_map[key] = result

        return score_map


# ============================================================
# 4. CSV処理
# ============================================================

def process_csv(input_path: str, output_path: str, scorer: PDERScorer):
    """
    CSVファイルを読み込み、score=0の行をスコアリングして新しいCSVを出力

    Parameters
    ----------
    input_path : str
        入力CSVファイルパス
    output_path : str
        出力CSVファイルパス
    scorer : PDERScorer
        スコアリングインスタンス
    """
    # 1. CSVを読み込み、スコアリング対象行を特定
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        all_rows = list(reader)

    method_col = headers.index("Measurement method")
    score_col = headers.index("Method score (PDER)")
    ref_col = headers.index("Reference ID")
    lit_col = headers.index("Litterature type")
    taxon_col = headers.index("Taxon")
    sender_col = 0  # Sender Circuit ID (sCID)
    receiver_col = 3  # Receiver Circuit ID (rCID)

    # 2. スコアリング対象のエントリを収集
    entries_to_score = []
    target_indices = []

    for i, row in enumerate(all_rows):
        if len(row) > score_col:
            score = row[score_col].strip()
            if score == '0':
                entry = {
                    'reference': row[ref_col].strip(),
                    'literature_type': row[lit_col].strip(),
                    'method': row[method_col].strip(),
                    'taxon': row[taxon_col].strip() if len(row) > taxon_col else '',
                    'sender': row[sender_col].strip(),
                    'receiver': row[receiver_col].strip(),
                }
                entries_to_score.append(entry)
                target_indices.append(i)

    print(f"スコアリング対象: {len(entries_to_score)} 行")

    if not entries_to_score:
        print("スコアリング対象の行がありません。")
        return

    # 3. ユニーク参考文献ごとにスコアリング
    score_map = scorer.score_by_unique_reference(entries_to_score)

    # 4. スコアを適用
    scored_count = 0
    for idx, entry in zip(target_indices, entries_to_score):
        key = f"{entry['reference']}|{entry['method']}|{entry['literature_type']}"
        if key in score_map:
            result = score_map[key]
            new_score = result.get('score', 0.3)
            # スコアを小数点以下2桁に丸める
            all_rows[idx][score_col] = f"{float(new_score):.2f}"
            scored_count += 1

    print(f"スコア適用完了: {scored_count} 行")

    # 5. CSVに書き出し
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(all_rows)

    print(f"出力ファイル: {output_path}")

    # 6. スコアリング結果サマリーを出力
    print("\n--- スコアリング結果サマリー ---")
    for key, result in sorted(score_map.items()):
        ref = key.split('|')[0]
        print(f"  {ref}: score={result.get('score')}, "
              f"method={result.get('inferred_method', 'N/A')}, "
              f"reason={result.get('reasoning', 'N/A')}")


# ============================================================
# 5. エントリーポイント
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="WholeBIF-RDB: Method Score (PDER) スコアリング（Claude API使用）"
    )
    parser.add_argument("--input", "-i", required=True, help="入力CSVファイルパス")
    parser.add_argument("--output", "-o", required=True, help="出力CSVファイルパス")
    parser.add_argument(
        "--model", "-m",
        default="claude-sonnet-4-20250514",
        help="使用するClaudeモデル (default: claude-sonnet-4-20250514)"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int, default=10,
        help="バッチサイズ (default: 10)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ドライラン（APIを呼ばずにヒューリスティックスコアを使用）"
    )

    args = parser.parse_args()

    if args.dry_run:
        print("ドライランモード: ヒューリスティックスコアを使用します")
        apply_heuristic_scores(args.input, args.output)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
            print("  export ANTHROPIC_API_KEY='your-api-key'")
            return

        scorer = PDERScorer(model=args.model)
        process_csv(args.input, args.output, scorer)


# ============================================================
# 6. ヒューリスティックスコアリング（APIなしのフォールバック）
# ============================================================

# 既知の実験手法 → PDERスコアのマッピング
KNOWN_METHOD_SCORES = {
    # トレーシング系（最高スコア: 方向性を直接的かつ精密に測定）
    # 順行性/逆行性トレーサーは投射の方向を直接証明できる
    "anterograde tracer": 0.95,
    "retrograde tracer": 0.95,
    "trans-synaptic tracing": 0.95,
    "transsynaptic tracing": 0.95,
    "transsynaptic labeling": 0.95,
    "neural tracer injections": 0.95,
    "various tracing": 0.90,
    "tracer study": 0.50,

    # 微量電気泳動注入（本質的にトレーサー送達法）
    "microiontophoretic injections": 0.85,

    # 電気生理・光遺伝学（高スコア: 刺激→応答で方向性を推定可能）
    "electrophys": 0.50,
    "electrophysiology": 0.65,
    "opto/chemo": 0.50,
    "optogenetics": 0.70,
    "optogenetic stimulation": 0.70,
    "optogenetic activation": 0.70,

    # イメージング系（中スコア: 方向性の特定は限定的）
    "fmri": 0.50,
    "functional magnetic resonance imaging": 0.50,
    "resting-state fmri": 0.50,
    "dti/tractography": 0.50,
    "diffusion tensor imaging": 0.50,
    "anatomical imaging/clearing": 0.50,
    "immunohistochemistry(biocytin)": 0.60,

    # MRI系
    "1.5 tesla mri": 0.45,

    # 非侵襲的脳刺激（方向性の特定は困難）
    "transcranial ac stimulation (tacs)": 0.40,
    "stimulation": 0.55,

    # カテゴリ
    "unspecified": 0.50,
    "review": 0.50,
}

# 文献タイプによるデフォルトスコア（メソッドが空の場合のフォールバック）
LITERATURE_TYPE_DEFAULT_SCORES = {
    "Experimental results": 0.40,
    "Review": 0.30,
    "Textbook": 0.30,
    "Data description": 0.30,
    "Hypothesis": 0.20,
    "Insight": 0.20,
    "#Error: Reference ID": 0.20,
    "": 0.30,
}


def get_heuristic_score(method: str, literature_type: str) -> float:
    """ヒューリスティックルールに基づくスコア算出"""
    if method:
        method_lower = method.lower().strip()
        # 完全一致
        if method_lower in KNOWN_METHOD_SCORES:
            return KNOWN_METHOD_SCORES[method_lower]
        # 部分一致
        for key, score in KNOWN_METHOD_SCORES.items():
            if key in method_lower or method_lower in key:
                return score

    # メソッドが空の場合は文献タイプで判定
    return LITERATURE_TYPE_DEFAULT_SCORES.get(
        literature_type, 0.30
    )


def apply_heuristic_scores(input_path: str, output_path: str):
    """ヒューリスティックスコアを適用してCSV出力"""
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        all_rows = list(reader)

    method_col = headers.index("Measurement method")
    score_col = headers.index("Method score (PDER)")
    lit_col = headers.index("Litterature type")

    scored_count = 0
    for row in all_rows:
        if len(row) > score_col:
            score = row[score_col].strip()
            if score == '0':
                method = row[method_col].strip()
                lit_type = row[lit_col].strip()
                new_score = get_heuristic_score(method, lit_type)
                row[score_col] = f"{new_score:.2f}"
                scored_count += 1

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(all_rows)

    print(f"ヒューリスティックスコアリング完了: {scored_count} 行")
    print(f"出力: {output_path}")


if __name__ == "__main__":
    main()
