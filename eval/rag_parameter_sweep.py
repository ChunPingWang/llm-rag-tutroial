#!/usr/bin/env python3
"""
RAG Parameter Sweep - Tests different similarity thresholds and topK values
to find the optimal operating point.

Requires: backend running at http://localhost:8081 with /api/ask/parameterized endpoint

Usage:
    python rag_parameter_sweep.py [--base-url http://localhost:8081]
"""

import argparse
import json
import os
import sys
import time
from itertools import product

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.lib.metrics import compute_all_metrics, aggregate_metrics
from eval.lib.report_generator import format_table, save_report


THRESHOLDS = [0.1, 0.2, 0.3, 0.4, 0.5]
TOP_K_VALUES = [3, 5, 8, 10]


def call_parameterized(base_url: str, question: str, threshold: float, top_k: int, category: str = None) -> dict:
    resp = requests.post(
        f"{base_url}/api/ask/parameterized",
        json={
            "question": question,
            "similarityThreshold": threshold,
            "topK": top_k,
            "category": category,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def run_sweep(base_url: str, dataset: list[dict], sample_size: int = 10) -> list[dict]:
    """Run parameter sweep on a sample of the dataset."""
    # Use a representative sample to keep runtime reasonable
    sample = dataset[:sample_size]
    results = []
    total_configs = len(THRESHOLDS) * len(TOP_K_VALUES)
    config_idx = 0

    for threshold, top_k in product(THRESHOLDS, TOP_K_VALUES):
        config_idx += 1
        config_key = f"t={threshold}_k={top_k}"
        print(f"  [{config_idx}/{total_configs}] threshold={threshold}, topK={top_k}")

        config_results = []
        for case in sample:
            try:
                resp = call_parameterized(base_url, case["question"], threshold, top_k)
                answer = resp.get("answer", "")
                metrics = compute_all_metrics(answer, case)
                config_results.append(metrics)
            except Exception as e:
                print(f"    ERROR on {case['id']}: {e}")
            time.sleep(0.3)

        # Aggregate for this configuration
        if config_results:
            avg_metrics = {}
            for key in config_results[0]:
                vals = [m[key] for m in config_results]
                avg_metrics[key] = sum(vals) / len(vals)

            results.append({
                "threshold": threshold,
                "topK": top_k,
                "config": config_key,
                "sample_size": len(config_results),
                "metrics": avg_metrics,
            })

    return results


def run_filter_comparison(base_url: str, dataset: list[dict], sample_size: int = 10) -> list[dict]:
    """Compare results with and without category filtering."""
    sample = [c for c in dataset if c.get("category") not in ("Cross",)][:sample_size]
    results = []

    for mode in ["no_filter", "correct_filter"]:
        print(f"\n  Filter mode: {mode}")
        mode_results = []

        for case in sample:
            try:
                category = case["category"] if mode == "correct_filter" else None
                resp = call_parameterized(base_url, case["question"], 0.3, 5, category)
                answer = resp.get("answer", "")
                metrics = compute_all_metrics(answer, case)
                mode_results.append({"id": case["id"], "metrics": metrics})
            except Exception as e:
                print(f"    ERROR: {e}")
            time.sleep(0.3)

        if mode_results:
            avg = {}
            for key in mode_results[0]["metrics"]:
                vals = [m["metrics"][key] for m in mode_results]
                avg[key] = sum(vals) / len(vals)
            results.append({"mode": mode, "avg_metrics": avg, "count": len(mode_results)})

    return results


def print_sweep_results(results: list[dict]):
    """Print parameter sweep results as a formatted table."""
    print("\n--- Parameter Sweep Results ---\n")

    headers = ["Threshold", "TopK", "Retrieval", "Answer", "Commands", "Halluc.", "Structure"]
    rows = []
    best_score = 0
    best_config = ""

    for r in results:
        m = r["metrics"]
        composite = (
            m.get("retrieval_keyword_recall", 0) * 0.25
            + m.get("answer_keyword_coverage", 0) * 0.30
            + m.get("command_recall", 0) * 0.20
            + m.get("hallucination_score", 0) * 0.15
            + m.get("structure_score", 0) * 0.10
        )
        if composite > best_score:
            best_score = composite
            best_config = r["config"]

        rows.append([
            str(r["threshold"]),
            str(r["topK"]),
            f"{m.get('retrieval_keyword_recall', 0):.3f}",
            f"{m.get('answer_keyword_coverage', 0):.3f}",
            f"{m.get('command_recall', 0):.3f}",
            f"{m.get('hallucination_score', 0):.3f}",
            f"{m.get('structure_score', 0):.3f}",
        ])

    print(format_table(headers, rows, [12, 8, 12, 10, 10, 10, 12]))
    print(f"\n  Best Configuration: {best_config} (composite score: {best_score:.3f})")


def print_filter_results(results: list[dict]):
    """Print filter comparison results."""
    print("\n--- Category Filter Comparison ---\n")

    headers = ["Mode", "Retrieval", "Answer", "Commands"]
    rows = []
    for r in results:
        m = r["avg_metrics"]
        rows.append([
            r["mode"],
            f"{m.get('retrieval_keyword_recall', 0):.3f}",
            f"{m.get('answer_keyword_coverage', 0):.3f}",
            f"{m.get('command_recall', 0):.3f}",
        ])

    print(format_table(headers, rows, [18, 12, 10, 10]))

    if len(results) == 2:
        lift = results[1]["avg_metrics"].get("answer_keyword_coverage", 0) - results[0]["avg_metrics"].get("answer_keyword_coverage", 0)
        print(f"\n  Filter Lift: {lift:+.3f}")
        print(f"  Verdict: {'FILTERING HELPS' if lift > 0 else 'FILTERING NOT HELPFUL'}")


def main():
    parser = argparse.ArgumentParser(description="RAG Parameter Sweep")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--sample-size", type=int, default=10, help="Number of test cases per configuration")
    parser.add_argument("--output-dir", default="eval/reports")
    args = parser.parse_args()

    print("=" * 60)
    print("  RAG Parameter Sweep")
    print("=" * 60)

    dataset_path = "eval/datasets/k8s_eval_dataset.json"
    with open(dataset_path) as f:
        dataset = json.load(f)

    # Parameter sweep
    print(f"\n--- Running Parameter Sweep (sample={args.sample_size}) ---\n")
    sweep_results = run_sweep(args.base_url, dataset, args.sample_size)
    print_sweep_results(sweep_results)

    # Filter comparison
    print(f"\n--- Running Filter Comparison ---")
    filter_results = run_filter_comparison(args.base_url, dataset, args.sample_size)
    print_filter_results(filter_results)

    # Save results
    save_report(
        sweep_results + filter_results,
        {"sweep": sweep_results, "filter": filter_results},
        args.output_dir,
        "parameter_sweep",
    )

    print("\n" + "=" * 60)
    print("  Parameter Sweep Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
