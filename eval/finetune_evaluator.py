#!/usr/bin/env python3
"""
Fine-Tune Evaluator - Compares base model vs fine-tuned model on K8s diagnostic tasks.

Uses the oMLX API (OpenAI-compatible) for inference, matching production serving path.
Replaces the previous evaluate.py that only measured response length.

Usage:
    python finetune_evaluator.py [--base-url http://127.0.0.1:8000] [--output-dir ./reports]
    python finetune_evaluator.py --adapter-url http://127.0.0.1:8001  # Compare base vs fine-tuned
"""

import argparse
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.lib.metrics import keyword_recall, command_recall, hallucination_score, structure_score
from eval.lib.llm_judge import judge_response
from eval.lib.report_generator import generate_summary, save_report, format_table


def load_eval_dataset(path: str) -> list[dict]:
    """Load the fine-tune eval JSONL dataset."""
    examples = []
    with open(path) as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line))
    return examples


def load_rag_dataset_as_finetune(path: str) -> list[dict]:
    """Convert the RAG eval dataset to fine-tune eval format."""
    with open(path) as f:
        dataset = json.load(f)
    examples = []
    for case in dataset:
        examples.append({
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "expected_keywords": case.get("expected_answer_keywords", []),
            "expected_commands": case.get("expected_kubectl_commands", []),
        })
    return examples


def generate_response(question: str, base_url: str, model: str = "default") -> str:
    """Generate a response via the oMLX OpenAI-compatible API."""
    system_prompt = (
        "You are a Kubernetes operations expert. Diagnose issues, "
        "suggest kubectl commands, and provide actionable fixes."
    )
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                "max_tokens": 512,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


def evaluate_model(
    examples: list[dict],
    base_url: str,
    model_name: str = "default",
    use_llm_judge: bool = False,
) -> list[dict]:
    """Evaluate a model on all examples."""
    results = []
    total = len(examples)

    for i, ex in enumerate(examples):
        question = ex.get("question", "")
        if not question and "messages" in ex:
            # JSONL format: extract user message
            question = next(
                (m["content"] for m in ex["messages"] if m["role"] == "user"), ""
            )

        print(f"  [{i+1}/{total}] {question[:60]}...")

        response = generate_response(question, base_url)

        expected_kw = ex.get("expected_keywords", ex.get("expected_answer_keywords", []))
        expected_cmd = ex.get("expected_commands", ex.get("expected_kubectl_commands", []))

        metrics = {
            "answer_keyword_coverage": keyword_recall(response, expected_kw),
            "command_recall": command_recall(response, expected_cmd),
            "hallucination_score": hallucination_score(response),
            "structure_score": structure_score(response),
            "response_length": len(response),
        }

        result = {
            "id": ex.get("id", f"ex-{i}"),
            "category": ex.get("category", "unknown"),
            "question": question[:100],
            "response_preview": response[:300],
            "model": metrics,
        }

        # Optional LLM-as-Judge
        if use_llm_judge:
            result["llm_judge"] = judge_response(question, response, expected_kw, base_url)

        results.append(result)
        time.sleep(0.5)

    return results


def compare_models(base_results: list[dict], ft_results: list[dict]) -> str:
    """Generate a comparison table between base and fine-tuned model."""
    lines = ["\n--- Base vs Fine-Tuned Comparison ---\n"]

    metric_keys = ["answer_keyword_coverage", "command_recall", "hallucination_score", "structure_score"]
    headers = ["Metric", "Base", "Fine-Tuned", "Delta", "Winner"]
    rows = []

    for key in metric_keys:
        base_vals = [r["model"][key] for r in base_results if key in r.get("model", {})]
        ft_vals = [r["model"][key] for r in ft_results if key in r.get("model", {})]
        base_mean = sum(base_vals) / len(base_vals) if base_vals else 0
        ft_mean = sum(ft_vals) / len(ft_vals) if ft_vals else 0
        delta = ft_mean - base_mean
        winner = "FT" if delta > 0.01 else ("Base" if delta < -0.01 else "Tie")
        rows.append([key, f"{base_mean:.3f}", f"{ft_mean:.3f}", f"{delta:+.3f}", winner])

    lines.append(format_table(headers, rows, [28, 10, 12, 10, 8]))

    ft_wins = sum(1 for r in rows if r[4] == "FT")
    base_wins = sum(1 for r in rows if r[4] == "Base")
    lines.append(f"\n  Fine-Tune Wins: {ft_wins}/{len(rows)}  |  Base Wins: {base_wins}/{len(rows)}")
    lines.append(f"  Verdict: {'FINE-TUNE HELPS' if ft_wins > base_wins else 'FINE-TUNE NEEDS MORE DATA' if ft_wins == base_wins else 'BASE IS BETTER'}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fine-Tune Evaluation")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base model API URL")
    parser.add_argument("--adapter-url", default=None, help="Fine-tuned model API URL (for comparison)")
    parser.add_argument("--dataset", default=None, help="Path to eval dataset (JSONL or JSON)")
    parser.add_argument("--llm-judge", action="store_true", help="Enable LLM-as-Judge")
    parser.add_argument("--output-dir", default="eval/reports", help="Output directory")
    args = parser.parse_args()

    print("=" * 60)
    print("  Fine-Tune Evaluation Framework")
    print("=" * 60)

    # Load dataset
    if args.dataset and os.path.exists(args.dataset):
        if args.dataset.endswith(".jsonl"):
            examples = load_eval_dataset(args.dataset)
        else:
            examples = load_rag_dataset_as_finetune(args.dataset)
    else:
        # Fall back to RAG eval dataset
        fallback = "eval/datasets/k8s_eval_dataset.json"
        if os.path.exists(fallback):
            print(f"  Using RAG dataset as fallback: {fallback}")
            examples = load_rag_dataset_as_finetune(fallback)
        else:
            print("  ERROR: No dataset found. Provide --dataset path.")
            sys.exit(1)

    print(f"\n  Dataset: {len(examples)} examples\n")

    # Evaluate base model
    print("--- Evaluating Base Model ---\n")
    base_results = evaluate_model(examples, args.base_url, use_llm_judge=args.llm_judge)

    from eval.lib.metrics import aggregate_metrics
    base_agg = aggregate_metrics(base_results, "model")
    print(generate_summary(base_agg, "Base Model Evaluation"))
    save_report(base_results, base_agg, args.output_dir, "finetune_base")

    # Evaluate fine-tuned model (if provided)
    if args.adapter_url:
        print("\n--- Evaluating Fine-Tuned Model ---\n")
        ft_results = evaluate_model(examples, args.adapter_url, use_llm_judge=args.llm_judge)

        ft_agg = aggregate_metrics(ft_results, "model")
        print(generate_summary(ft_agg, "Fine-Tuned Model Evaluation"))
        save_report(ft_results, ft_agg, args.output_dir, "finetune_adapter")

        # Comparison
        print(compare_models(base_results, ft_results))

    print("\n" + "=" * 60)
    print("  Evaluation Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
