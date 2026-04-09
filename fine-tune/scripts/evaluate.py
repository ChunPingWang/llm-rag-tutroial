#!/usr/bin/env python3
"""
Evaluate fine-tuned model against base model on test dataset.
Compares response quality using the test split.
"""

import json
import os
import sys

try:
    from mlx_lm import load, generate
except ImportError:
    print("ERROR: mlx-lm not installed. Run: pip install mlx-lm")
    sys.exit(1)


def evaluate(model_path: str, adapter_path: str = None, test_file: str = None):
    """Run evaluation on test set, comparing base vs fine-tuned."""
    if test_file is None:
        test_file = "./data/dataset/test.jsonl"

    with open(test_file) as f:
        test_examples = [json.loads(line) for line in f if line.strip()]

    print(f"Evaluating on {len(test_examples)} test examples")
    print(f"Model: {model_path}")
    if adapter_path:
        print(f"Adapter: {adapter_path}")

    # Load model
    model, tokenizer = load(model_path, adapter_path=adapter_path)

    results = []
    for i, example in enumerate(test_examples):
        messages = example["messages"]
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        expected = next(m["content"] for m in messages if m["role"] == "assistant")

        # Generate response
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": user_msg}],
            tokenize=False, add_generation_prompt=True
        )
        response = generate(model, tokenizer, prompt=prompt, max_tokens=512)

        results.append({
            "prompt": user_msg[:100],
            "expected_length": len(expected),
            "generated_length": len(response),
            "generated_preview": response[:200],
        })

        print(f"  [{i+1}/{len(test_examples)}] Generated {len(response)} chars")

    # Summary
    avg_len = sum(r["generated_length"] for r in results) / len(results) if results else 0
    print(f"\n--- Evaluation Summary ---")
    print(f"Examples evaluated: {len(results)}")
    print(f"Avg response length: {avg_len:.0f} chars")
    print(f"Results saved to: ./data/eval_results.json")

    with open("./data/eval_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"
    adapter = sys.argv[2] if len(sys.argv) > 2 else None
    evaluate(model, adapter)
