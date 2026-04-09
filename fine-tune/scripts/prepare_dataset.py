#!/usr/bin/env python3
"""
Prepare exported training data into MLX-compatible format for LoRA fine-tuning.
Splits data into train/valid/test sets.
"""

import json
import os
import random
import sys


def prepare_dataset(input_file: str, output_dir: str, train_ratio=0.8, valid_ratio=0.1):
    """Convert JSONL training data to MLX chat format."""
    with open(input_file) as f:
        examples = [json.loads(line) for line in f if line.strip()]

    if len(examples) < 10:
        print(f"Warning: Only {len(examples)} examples. Need at least 10 for meaningful fine-tuning.")

    # Convert to MLX chat format
    formatted = []
    for ex in examples:
        formatted.append({
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Kubernetes operations expert. Diagnose issues, suggest kubectl commands, and provide actionable fixes."
                },
                {"role": "user", "content": ex["prompt"]},
                {"role": "assistant", "content": ex["completion"]},
            ]
        })

    # Shuffle and split
    random.shuffle(formatted)
    n = len(formatted)
    train_end = int(n * train_ratio)
    valid_end = int(n * (train_ratio + valid_ratio))

    splits = {
        "train": formatted[:train_end],
        "valid": formatted[train_end:valid_end],
        "test": formatted[valid_end:],
    }

    os.makedirs(output_dir, exist_ok=True)
    for split_name, data in splits.items():
        output_file = os.path.join(output_dir, f"{split_name}.jsonl")
        with open(output_file, "w") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"  {split_name}: {len(data)} examples -> {output_file}")

    print(f"\nDataset prepared: {n} total examples")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prepare_dataset.py <input.jsonl> [output_dir]")
        sys.exit(1)
    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./data/dataset"
    prepare_dataset(input_file, output_dir)
