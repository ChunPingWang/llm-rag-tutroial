#!/usr/bin/env python3
"""
RAG Evaluator - Measures retrieval quality, answer correctness, and RAG lift.

Requires: backend running at http://localhost:8081
Optional: oMLX running at http://127.0.0.1:8000 (for LLM-as-Judge)

Usage:
    python rag_evaluator.py [--base-url http://localhost:8081] [--llm-judge] [--output-dir ./reports]
"""

import argparse
import json
import os
import sys
import time

import requests

# Add parent dir to path for lib imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.lib.metrics import compute_all_metrics, aggregate_metrics, aggregate_by_category
from eval.lib.llm_judge import batch_judge
from eval.lib.report_generator import (
    generate_summary,
    generate_category_summary,
    generate_rag_lift_summary,
    generate_llm_judge_summary,
    save_report,
)


def load_dataset(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def call_rag(base_url: str, question: str) -> dict:
    """Call the RAG endpoint."""
    resp = requests.post(
        f"{base_url}/api/ask",
        json={"question": question},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def call_simple(base_url: str, question: str) -> dict:
    """Call the non-RAG endpoint."""
    resp = requests.post(
        f"{base_url}/api/ask/simple",
        json={"question": question},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def call_diagnose(base_url: str, symptom: str, kubectl_output: str) -> dict:
    """Call the diagnose endpoint."""
    resp = requests.post(
        f"{base_url}/api/diagnose",
        json={"symptom": symptom, "kubectlOutput": kubectl_output},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def evaluate_rag_dataset(base_url: str, dataset: list[dict], use_llm_judge: bool = False) -> list[dict]:
    """Evaluate all test cases in the RAG dataset."""
    results = []
    total = len(dataset)

    for i, case in enumerate(dataset):
        print(f"  [{i+1}/{total}] {case['id']}: {case['question'][:60]}...")

        try:
            # Call RAG endpoint
            rag_resp = call_rag(base_url, case["question"])
            rag_answer = rag_resp.get("answer", "")
            rag_sources = rag_resp.get("sources", [])

            # Call non-RAG endpoint
            simple_resp = call_simple(base_url, case["question"])
            simple_answer = simple_resp.get("answer", "")

            # Compute metrics
            rag_metrics = compute_all_metrics(rag_answer, case)
            simple_metrics = compute_all_metrics(simple_answer, case)

            result = {
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "difficulty": case.get("difficulty", "unknown"),
                "rag_answer": rag_answer[:500],
                "simple_answer": simple_answer[:500],
                "rag_sources": rag_sources,
                "rag": rag_metrics,
                "simple": simple_metrics,
                "rag_lift": rag_metrics["answer_keyword_coverage"] - simple_metrics["answer_keyword_coverage"],
                "expected_answer_keywords": case.get("expected_answer_keywords", []),
            }
            results.append(result)

        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "id": case["id"],
                "category": case["category"],
                "error": str(e),
            })

        time.sleep(0.5)  # Rate limiting

    # Optional LLM-as-Judge scoring
    if use_llm_judge:
        print("\n  Running LLM-as-Judge scoring...")
        batch_judge(results)

    return results


def evaluate_diagnose_dataset(base_url: str, dataset: list[dict]) -> list[dict]:
    """Evaluate diagnose endpoint test cases."""
    from eval.lib.metrics import compute_diagnose_metrics

    results = []
    total = len(dataset)

    for i, case in enumerate(dataset):
        print(f"  [{i+1}/{total}] {case['id']}: {case['symptom'][:60]}...")

        try:
            resp = call_diagnose(base_url, case["symptom"], case.get("kubectlOutput", ""))
            diagnosis = resp.get("diagnosis", "")

            metrics = compute_diagnose_metrics(diagnosis, case)

            results.append({
                "id": case["id"],
                "category": case["category"],
                "symptom": case["symptom"],
                "diagnosis_preview": diagnosis[:500],
                "diagnose": metrics,
            })
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"id": case["id"], "error": str(e)})

        time.sleep(0.5)

    return results


def main():
    parser = argparse.ArgumentParser(description="RAG Evaluation Framework")
    parser.add_argument("--base-url", default="http://localhost:8081", help="Backend API URL")
    parser.add_argument("--llm-judge", action="store_true", help="Enable LLM-as-Judge scoring")
    parser.add_argument("--output-dir", default="eval/reports", help="Output directory for reports")
    parser.add_argument("--dataset-dir", default="eval/datasets", help="Dataset directory")
    args = parser.parse_args()

    print("=" * 60)
    print("  RAG Evaluation Framework")
    print("=" * 60)

    # Check backend is running
    try:
        requests.get(f"{args.base_url}/api/documents", timeout=5)
    except requests.ConnectionError:
        print(f"\n  ERROR: Backend not reachable at {args.base_url}")
        print("  Start the backend first: cd backend && mvn spring-boot:run")
        sys.exit(1)

    # --- RAG Dataset Evaluation ---
    rag_dataset_path = os.path.join(args.dataset_dir, "k8s_eval_dataset.json")
    if os.path.exists(rag_dataset_path):
        print(f"\n--- Evaluating RAG Dataset ({rag_dataset_path}) ---\n")
        rag_dataset = load_dataset(rag_dataset_path)
        rag_results = evaluate_rag_dataset(args.base_url, rag_dataset, args.llm_judge)

        # Aggregate and report
        rag_agg = aggregate_metrics(rag_results, "rag")
        print(generate_summary(rag_agg, "RAG Evaluation"))

        cat_metrics = aggregate_by_category(rag_results, "rag")
        print(generate_category_summary(cat_metrics))
        print(generate_rag_lift_summary(rag_results))

        if args.llm_judge:
            print(generate_llm_judge_summary(rag_results))

        save_report(rag_results, rag_agg, args.output_dir, "rag")
    else:
        print(f"\n  WARNING: RAG dataset not found at {rag_dataset_path}")

    # --- Diagnose Dataset Evaluation ---
    diag_dataset_path = os.path.join(args.dataset_dir, "k8s_diagnose_dataset.json")
    if os.path.exists(diag_dataset_path):
        print(f"\n--- Evaluating Diagnose Dataset ({diag_dataset_path}) ---\n")
        diag_dataset = load_dataset(diag_dataset_path)
        diag_results = evaluate_diagnose_dataset(args.base_url, diag_dataset)

        diag_agg = aggregate_metrics(diag_results, "diagnose")
        print(generate_summary(diag_agg, "Diagnose Evaluation"))
        save_report(diag_results, diag_agg, args.output_dir, "diagnose")

    print("\n" + "=" * 60)
    print("  Evaluation Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
