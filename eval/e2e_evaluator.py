#!/usr/bin/env python3
"""
End-to-End Evaluator - Tests the self-reinforcing feedback loop.

Measures whether ingesting a new diagnostic session actually improves
future retrieval and answer quality for similar questions.

Workflow:
1. Baseline: Run eval questions, record scores
2. Inject: Create a synthetic resolved session via the REST API
3. Post-feedback: Re-run the same questions, record scores
4. Compare: Measure improvement

Requires: backend running at http://localhost:8081

Usage:
    python e2e_evaluator.py [--base-url http://localhost:8081]
"""

import argparse
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.lib.metrics import compute_all_metrics
from eval.lib.report_generator import format_table, save_report


# A synthetic session that introduces NEW knowledge not in the original runbooks:
# A specific Java Spring Boot OOM pattern with jmap/jstack diagnosis
SYNTHETIC_SESSION = {
    "description": "Spring Boot app OOMKilled due to Hikari connection pool leak",
    "k8sContext": "production-cluster",
    "interactions": [
        {
            "type": "USER_QUERY",
            "content": "spring-boot-api pod in billing namespace keeps getting OOMKilled every 2 hours"
        },
        {
            "type": "KUBECTL_COMMAND",
            "content": "kubectl top pod spring-boot-api -n billing"
        },
        {
            "type": "KUBECTL_OUTPUT",
            "content": "NAME              CPU   MEMORY\nspring-boot-api   300m  1.9Gi"
        },
        {
            "type": "KUBECTL_COMMAND",
            "content": "kubectl exec spring-boot-api -n billing -- jmap -histo:live 1 | head -20"
        },
        {
            "type": "KUBECTL_OUTPUT",
            "content": "num   #instances  #bytes  class name\n1:    85000       68000000  com.zaxxer.hikari.pool.HikariProxyConnection\n2:    42000       33600000  com.zaxxer.hikari.pool.PoolEntry"
        },
        {
            "type": "LLM_RESPONSE",
            "content": "Root cause: Hikari connection pool leak. 85000 HikariProxyConnection instances indicate connections are not being closed properly. Resolution: 1) Set spring.datasource.hikari.leak-detection-threshold=60000 2) Set spring.datasource.hikari.maximum-pool-size=20 3) Review code for unclosed connections in try-finally blocks. 4) Add -XX:MaxRAMPercentage=75.0 to JVM flags."
        },
        {
            "type": "USER_ACTION",
            "content": "Added leak-detection-threshold and fixed unclosed connection in BillingRepository. Deployed new version."
        }
    ],
    "outcome": "RESOLVED",
    "notes": "Hikari connection pool leak caused by unclosed connections in BillingRepository.findOverdueInvoices(). Fixed by wrapping in try-with-resources. Added leak detection threshold for early warning."
}

# Questions that should benefit from the new knowledge
FEEDBACK_TEST_QUESTIONS = [
    {
        "id": "fb-001",
        "question": "Spring Boot pod keeps OOMKilled every few hours, memory slowly increases. How to diagnose?",
        "expected_keywords_before": ["OOMKilled", "memory limits", "kubectl top"],
        "expected_keywords_after": ["Hikari", "connection pool", "leak-detection", "jmap", "OOMKilled"],
        "category": "OOMKill",
    },
    {
        "id": "fb-002",
        "question": "How to detect a memory leak in a Java K8s pod?",
        "expected_keywords_before": ["memory", "OOMKilled", "kubectl top"],
        "expected_keywords_after": ["jmap", "histo", "connection pool", "leak", "OOMKilled"],
        "category": "OOMKill",
    },
    {
        "id": "fb-003",
        "question": "Hikari connection pool issues causing pod memory growth, what to do?",
        "expected_keywords_before": ["memory", "connection"],
        "expected_keywords_after": ["Hikari", "leak-detection-threshold", "maximum-pool-size", "try-with-resources"],
        "category": "OOMKill",
    },
]


def create_session(base_url: str, session_data: dict) -> str:
    """Create a diagnostic session via the REST API, return session ID."""
    # Start session
    # Note: We use the MCP tools through the REST controller or directly POST
    # For simplicity, create directly via the controller if available
    # Otherwise, we'll simulate by posting to the feedback process endpoint

    # Use the internal API to create session and interactions
    from eval.lib.metrics import keyword_recall  # just to trigger import

    # POST to create session (use backend internal APIs)
    resp = requests.post(
        f"{base_url}/api/eval/create-test-session",
        json=session_data,
        timeout=30,
    )
    if resp.status_code == 404:
        # Fallback: use the feedback process endpoint with pre-created data
        print("  Note: create-test-session endpoint not available, using direct feedback")
        return None
    resp.raise_for_status()
    return resp.json().get("sessionId")


def evaluate_questions(base_url: str, questions: list[dict], keyword_field: str) -> list[dict]:
    """Evaluate a set of questions, return results with metrics."""
    results = []
    for q in questions:
        try:
            resp = requests.post(
                f"{base_url}/api/ask",
                json={"question": q["question"]},
                timeout=120,
            )
            answer = resp.json().get("answer", "")
            expected = q.get(keyword_field, [])

            from eval.lib.metrics import keyword_recall, command_recall, hallucination_score
            results.append({
                "id": q["id"],
                "keyword_coverage": keyword_recall(answer, expected),
                "hallucination_score": hallucination_score(answer),
                "answer_preview": answer[:300],
            })
        except Exception as e:
            results.append({"id": q["id"], "error": str(e)})
        time.sleep(0.5)
    return results


def main():
    parser = argparse.ArgumentParser(description="E2E Feedback Loop Evaluation")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--output-dir", default="eval/reports")
    args = parser.parse_args()

    print("=" * 60)
    print("  End-to-End Feedback Loop Evaluation")
    print("=" * 60)

    # Step 1: Baseline evaluation
    print("\n--- Step 1: Baseline Evaluation (before feedback) ---\n")
    baseline_results = evaluate_questions(args.base_url, FEEDBACK_TEST_QUESTIONS, "expected_keywords_before")

    for r in baseline_results:
        if "error" not in r:
            print(f"  {r['id']}: keyword_coverage={r['keyword_coverage']:.3f}")

    # Step 2: Inject synthetic session
    print("\n--- Step 2: Injecting Synthetic Resolved Session ---\n")
    session_id = create_session(args.base_url, SYNTHETIC_SESSION)

    if session_id:
        print(f"  Created session: {session_id}")
        # Trigger feedback processing
        resp = requests.post(f"{args.base_url}/api/feedback/process", timeout=30)
        processed = resp.json().get("processed", 0)
        print(f"  Feedback processed: {processed} sessions")
    else:
        print("  Skipping session creation (endpoint not available)")
        print("  To test feedback loop, manually create sessions via the Web UI or MCP tools")

    # Step 3: Post-feedback evaluation
    print("\n--- Step 3: Post-Feedback Evaluation ---\n")
    time.sleep(2)  # Wait for vector store to update
    post_results = evaluate_questions(args.base_url, FEEDBACK_TEST_QUESTIONS, "expected_keywords_after")

    for r in post_results:
        if "error" not in r:
            print(f"  {r['id']}: keyword_coverage={r['keyword_coverage']:.3f}")

    # Step 4: Compare
    print("\n--- Step 4: Feedback Loop Impact ---\n")
    headers = ["Question", "Before", "After", "Delta", "Improved?"]
    rows = []
    for b, a in zip(baseline_results, post_results):
        if "error" in b or "error" in a:
            continue
        before = b["keyword_coverage"]
        after = a["keyword_coverage"]
        delta = after - before
        rows.append([
            b["id"],
            f"{before:.3f}",
            f"{after:.3f}",
            f"{delta:+.3f}",
            "YES" if delta > 0 else ("NO" if delta < 0 else "SAME"),
        ])

    print(format_table(headers, rows, [12, 10, 10, 10, 10]))

    if rows:
        avg_delta = sum(float(r[3]) for r in rows) / len(rows)
        improved = sum(1 for r in rows if r[4] == "YES")
        print(f"\n  Average Delta: {avg_delta:+.3f}")
        print(f"  Improved: {improved}/{len(rows)}")
        print(f"  Verdict: {'FEEDBACK LOOP WORKS' if avg_delta > 0 else 'FEEDBACK LOOP NEEDS TUNING'}")

    # Save report
    save_report(
        {"baseline": baseline_results, "post_feedback": post_results},
        {"avg_delta": avg_delta if rows else 0},
        args.output_dir,
        "e2e_feedback",
    )

    print("\n" + "=" * 60)
    print("  E2E Evaluation Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
