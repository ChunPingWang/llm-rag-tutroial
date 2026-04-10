"""Generate evaluation reports in terminal and JSON format."""

import json
import os
from datetime import datetime


TARGETS = {
    "retrieval_keyword_recall": 0.7,
    "answer_keyword_coverage": 0.6,
    "command_recall": 0.5,
    "hallucination_score": 0.95,
    "structure_score": 0.6,
}


def format_table(headers: list[str], rows: list[list], col_widths: list[int] = None) -> str:
    """Format a simple ASCII table."""
    if not col_widths:
        col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) + 2
                      for i, h in enumerate(headers)]

    sep = "+" + "+".join("-" * w for w in col_widths) + "+"
    header_row = "|" + "|".join(str(h).center(w) for h, w in zip(headers, col_widths)) + "|"

    lines = [sep, header_row, sep]
    for row in rows:
        line = "|" + "|".join(str(cell).center(w) for cell, w in zip(row, col_widths)) + "|"
        lines.append(line)
    lines.append(sep)
    return "\n".join(lines)


def pass_fail(value: float, target: float) -> str:
    """Return PASS/FAIL indicator."""
    return "PASS" if value >= target else "FAIL"


def generate_summary(aggregated: dict, title: str = "RAG Evaluation") -> str:
    """Generate terminal-friendly summary."""
    lines = [
        f"\n{'='*60}",
        f"  {title}",
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"{'='*60}\n",
    ]

    headers = ["Metric", "Mean", "Min", "Max", "Target", "Status"]
    rows = []
    for metric, stats in aggregated.items():
        target = TARGETS.get(metric, None)
        mean_val = stats["mean"]
        status = pass_fail(mean_val, target) if target else "N/A"
        target_str = f">={target}" if target else "-"
        rows.append([
            metric,
            f"{mean_val:.3f}",
            f"{stats['min']:.3f}",
            f"{stats['max']:.3f}",
            target_str,
            status,
        ])

    lines.append(format_table(headers, rows, [30, 8, 8, 8, 10, 8]))

    # Overall pass/fail
    total = len(rows)
    passed = sum(1 for r in rows if r[5] == "PASS")
    failed = sum(1 for r in rows if r[5] == "FAIL")
    lines.append(f"\n  Metrics: {passed} PASS / {failed} FAIL / {total - passed - failed} N/A")

    return "\n".join(lines)


def generate_category_summary(category_metrics: dict) -> str:
    """Generate per-category breakdown."""
    lines = ["\n--- Per-Category Breakdown ---\n"]

    headers = ["Category", "Retrieval", "Answer", "Commands", "Halluc.", "Structure"]
    rows = []
    for cat, metrics in sorted(category_metrics.items()):
        rows.append([
            cat,
            f"{metrics.get('retrieval_keyword_recall', {}).get('mean', 0):.2f}",
            f"{metrics.get('answer_keyword_coverage', {}).get('mean', 0):.2f}",
            f"{metrics.get('command_recall', {}).get('mean', 0):.2f}",
            f"{metrics.get('hallucination_score', {}).get('mean', 0):.2f}",
            f"{metrics.get('structure_score', {}).get('mean', 0):.2f}",
        ])

    lines.append(format_table(headers, rows, [20, 12, 10, 10, 10, 12]))
    return "\n".join(lines)


def generate_rag_lift_summary(results: list[dict]) -> str:
    """Generate RAG lift (RAG vs no-RAG) comparison."""
    lines = ["\n--- RAG Lift Analysis ---\n"]

    lifts = [r.get("rag_lift", 0) for r in results if "rag_lift" in r]
    if not lifts:
        return "\n  No RAG lift data available.\n"

    positive = sum(1 for l in lifts if l > 0)
    negative = sum(1 for l in lifts if l < 0)
    neutral = sum(1 for l in lifts if l == 0)
    avg_lift = sum(lifts) / len(lifts)

    lines.append(f"  Average RAG Lift: {avg_lift:+.3f}")
    lines.append(f"  RAG Better: {positive}/{len(lifts)} ({100*positive/len(lifts):.0f}%)")
    lines.append(f"  RAG Worse:  {negative}/{len(lifts)} ({100*negative/len(lifts):.0f}%)")
    lines.append(f"  Equal:      {neutral}/{len(lifts)} ({100*neutral/len(lifts):.0f}%)")
    lines.append(f"  Verdict:    {'RAG IS HELPING' if avg_lift > 0 else 'RAG NEEDS IMPROVEMENT'}")

    return "\n".join(lines)


def generate_llm_judge_summary(results: list[dict]) -> str:
    """Generate LLM-as-Judge score summary."""
    judged = [r for r in results if "llm_judge" in r and "error" not in r.get("llm_judge", {})]
    if not judged:
        return "\n  No LLM Judge data available.\n"

    lines = ["\n--- LLM-as-Judge Scores (1-5) ---\n"]

    dims = ["correctness", "completeness", "safety", "actionability", "average"]
    headers = ["Dimension", "RAG Mean", "No-RAG Mean", "Lift"]
    rows = []
    for dim in dims:
        rag_scores = [r["llm_judge"][dim] for r in judged if dim in r.get("llm_judge", {})]
        simple_scores = [r["llm_judge_simple"][dim] for r in judged
                         if "llm_judge_simple" in r and dim in r.get("llm_judge_simple", {})]
        rag_mean = sum(rag_scores) / len(rag_scores) if rag_scores else 0
        simple_mean = sum(simple_scores) / len(simple_scores) if simple_scores else 0
        lift = rag_mean - simple_mean if simple_mean else 0
        rows.append([dim.capitalize(), f"{rag_mean:.2f}", f"{simple_mean:.2f}", f"{lift:+.2f}"])

    lines.append(format_table(headers, rows, [16, 12, 14, 8]))
    return "\n".join(lines)


def save_report(results: list[dict], aggregated: dict, output_dir: str, prefix: str = "rag"):
    """Save full JSON report and terminal summary."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON report
    report = {
        "timestamp": timestamp,
        "type": prefix,
        "aggregated_metrics": aggregated,
        "results": results,
    }
    json_path = os.path.join(output_dir, f"{prefix}_report_{timestamp}.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"  Report saved: {json_path}")
    return json_path
