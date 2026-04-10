#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=============================================="
echo "  K8s RAG + Fine-Tune Evaluation Suite"
echo "=============================================="
echo ""

BACKEND_URL="${BACKEND_URL:-http://localhost:8081}"
LLM_URL="${LLM_URL:-http://127.0.0.1:8000}"
REPORTS_DIR="eval/reports"

mkdir -p "$REPORTS_DIR"

# Check prerequisites
echo "--- Checking Prerequisites ---"
echo ""

if ! curl -s "$BACKEND_URL/api/documents" > /dev/null 2>&1; then
    echo "  ERROR: Backend not reachable at $BACKEND_URL"
    echo "  Start it: cd backend && mvn spring-boot:run"
    exit 1
fi
echo "  Backend: OK ($BACKEND_URL)"

LLM_AVAILABLE=false
if curl -s "$LLM_URL/v1/models" > /dev/null 2>&1; then
    echo "  oMLX: OK ($LLM_URL)"
    LLM_AVAILABLE=true
else
    echo "  oMLX: NOT AVAILABLE (LLM-as-Judge and Fine-Tune eval will be skipped)"
fi

echo ""

# 1. RAG Evaluation
echo "=============================================="
echo "  1/4  RAG Evaluation"
echo "=============================================="
python eval/rag_evaluator.py --base-url "$BACKEND_URL" --output-dir "$REPORTS_DIR"

# 2. RAG Parameter Sweep
echo ""
echo "=============================================="
echo "  2/4  RAG Parameter Sweep"
echo "=============================================="
python eval/rag_parameter_sweep.py --base-url "$BACKEND_URL" --sample-size 8 --output-dir "$REPORTS_DIR"

# 3. Fine-Tune Evaluation (requires oMLX)
if [ "$LLM_AVAILABLE" = true ]; then
    echo ""
    echo "=============================================="
    echo "  3/4  Fine-Tune Base Model Evaluation"
    echo "=============================================="
    python eval/finetune_evaluator.py --base-url "$LLM_URL" --output-dir "$REPORTS_DIR"
else
    echo ""
    echo "  3/4  Fine-Tune Evaluation: SKIPPED (oMLX not available)"
fi

# 4. E2E Feedback Loop
echo ""
echo "=============================================="
echo "  4/4  E2E Feedback Loop Evaluation"
echo "=============================================="
python eval/e2e_evaluator.py --base-url "$BACKEND_URL" --output-dir "$REPORTS_DIR"

echo ""
echo "=============================================="
echo "  All evaluations complete!"
echo "  Reports saved to: $REPORTS_DIR/"
echo "=============================================="
ls -la "$REPORTS_DIR"/*.json 2>/dev/null || echo "  (no JSON reports generated)"
