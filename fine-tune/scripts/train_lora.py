#!/usr/bin/env python3
"""
LoRA fine-tuning using MLX.
Trains a lightweight LoRA adapter on top of the base model.
"""

import os
import sys
import yaml

try:
    from mlx_lm import lora
except ImportError:
    print("ERROR: mlx-lm not installed. Run: pip install mlx-lm")
    sys.exit(1)


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def train(config_path: str = None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "..", "configs", "lora_config.yaml")

    config = load_config(config_path)

    print(f"Starting LoRA fine-tuning:")
    print(f"  Model: {config['model']}")
    print(f"  Dataset: {config['data_dir']}")
    print(f"  LoRA rank: {config['lora_rank']}")
    print(f"  Epochs: {config['num_epochs']}")
    print(f"  Output: {config['adapter_path']}")

    # Run LoRA training via mlx_lm CLI
    args = [
        "--model", config["model"],
        "--data", config["data_dir"],
        "--train",
        "--adapter-path", config["adapter_path"],
        "--iters", str(config.get("max_iters", 1000)),
        "--batch-size", str(config.get("batch_size", 4)),
        "--lora-layers", str(config.get("lora_layers", 16)),
        "--learning-rate", str(config.get("learning_rate", 1e-5)),
    ]

    # Use mlx_lm.lora module directly
    sys.argv = ["mlx_lm.lora"] + args
    lora.main()

    print(f"\nTraining complete! Adapter saved to: {config['adapter_path']}")
    print(f"To serve: mlx_lm.server --model {config['model']} --adapter-path {config['adapter_path']}")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    train(config_file)
