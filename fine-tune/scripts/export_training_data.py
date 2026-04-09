#!/usr/bin/env python3
"""
Export resolved diagnostic sessions from PostgreSQL into training data format.
Only exports sessions marked as RESOLVED with feedbackIngested=true.
"""

import json
import os
import sys
from datetime import datetime

import psycopg2
import yaml


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "ragdb"),
        user=os.getenv("DB_USER", "raguser"),
        password=os.getenv("DB_PASSWORD", "ragpass"),
    )


def export_sessions(output_dir: str, min_interactions: int = 3):
    """Export resolved sessions as training data."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Get resolved sessions
    cur.execute("""
        SELECT s.id, s.description, s.k8s_context, s.notes, s.started_at, s.resolved_at
        FROM diagnostic_sessions s
        WHERE s.outcome = 'RESOLVED'
        AND s.feedback_ingested = true
        ORDER BY s.started_at DESC
    """)
    sessions = cur.fetchall()

    training_data = []
    for session in sessions:
        session_id, description, k8s_context, notes, started_at, resolved_at = session

        # Get interactions for this session
        cur.execute("""
            SELECT type, content, metadata, timestamp
            FROM interactions
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """, (session_id,))
        interactions = cur.fetchall()

        if len(interactions) < min_interactions:
            continue

        # Build training example
        example = build_training_example(
            description, k8s_context, notes, interactions
        )
        if example:
            training_data.append(example)

    cur.close()
    conn.close()

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")

    with open(output_file, "w") as f:
        for example in training_data:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")

    print(f"Exported {len(training_data)} training examples to {output_file}")
    return output_file


def build_training_example(description, k8s_context, notes, interactions):
    """Convert a session into an instruction-tuning format example."""
    # Build the prompt (input)
    prompt_parts = [f"Diagnose and resolve: {description}"]
    if k8s_context:
        prompt_parts.append(f"Cluster: {k8s_context}")

    # Collect kubectl outputs as context
    kubectl_outputs = []
    for itype, content, metadata, timestamp in interactions:
        if itype in ("KUBECTL_COMMAND", "KUBECTL_OUTPUT"):
            kubectl_outputs.append(content)

    if kubectl_outputs:
        prompt_parts.append("\nkubectl output:\n" + "\n".join(kubectl_outputs[:5]))  # Limit to 5

    prompt = "\n".join(prompt_parts)

    # Build the completion (output) from LLM responses and resolution
    completion_parts = []
    for itype, content, metadata, timestamp in interactions:
        if itype == "LLM_RESPONSE":
            completion_parts.append(content)

    if notes:
        completion_parts.append(f"\nResolution: {notes}")

    if not completion_parts:
        return None

    completion = "\n\n".join(completion_parts)

    return {
        "prompt": prompt,
        "completion": completion,
    }


if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "./data/training"
    export_sessions(output_dir)
