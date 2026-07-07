#!/bin/bash
# Run spider-agent-tc baseline on AISQL benchmark. Works on Linux and macOS.
# Usage:
#   bash baseline/spider-agent-tc/run_aisql.sh                    # run all 393 instances
#   bash baseline/spider-agent-tc/run_aisql.sh --test sf_bq003    # test single instance
#
# Configure the agent's LLM via env vars:
#   OPENAI_API_BASE  the OpenAI-compatible endpoint
#   OPENAI_API_KEY   the key for that endpoint (required)
#   MODEL            the model id served by that endpoint

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ---- LLM Configuration ----
export OPENAI_API_BASE="${OPENAI_API_BASE:?Set OPENAI_API_BASE, e.g. https://api.openai.com/v1 or your Snowflake Cortex endpoint}"
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY before running}"

if [[ "$OPENAI_API_BASE" == *"<your-account>"* ]]; then
    echo "ERROR: OPENAI_API_BASE still contains the <your-account> placeholder."
    echo "Set it to a real OpenAI-compatible endpoint before running."
    exit 1
fi

# ---- Paths ----
INPUT_FILE="$PROJECT_ROOT/data/spider2-aifunc.jsonl"   # the agent reads the task JSONL directly
SYSTEM_PROMPT="$SCRIPT_DIR/prompts/spider_agent.txt"
DATABASES_PATH="$PROJECT_ROOT/resources/databases"
DOCUMENTS_PATH="$PROJECT_ROOT/resources/knowledge"

if [[ ! -d "$DATABASES_PATH" || ! -d "$DOCUMENTS_PATH" ]]; then
    echo "ERROR: Spider2-Snow resources are missing."
    echo "Run python scripts/setup_resources.py, then link or copy resources/databases and resources/knowledge."
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/credentials/snowflake_credential.json" ]]; then
    echo "ERROR: Snowflake credential file not found."
    echo "Copy baseline/spider-agent-tc/credentials/snowflake_credential.example.json to snowflake_credential.json and fill it in."
    exit 1
fi

# ---- Model Settings ----
MODEL="${MODEL:?Set MODEL to a model served by OPENAI_API_BASE}"
TEMPERATURE=1
TOP_P=0.9
MAX_NEW_TOKENS=16000
MAX_ROUNDS=50
NUM_THREADS=4
ROLLOUT_NUMBER=1
EXPERIMENT_SUFFIX="aisql_v2"

# ---- Reasoning Settings ----
export REASONING_EFFORT="medium"  # low / medium / high / empty to disable

# ---- Timeout & Display Settings ----
export QUERY_TIMEOUT=120       # Snowflake SQL + HTTP timeout (seconds)
export BASH_TIMEOUT=60         # Bash command timeout (seconds)
export MAX_CSV_CHARS=8000      # Max chars for SQL result display

# ---- Handle --test flag for single instance testing ----
if [[ "$1" == "--test" && -n "$2" ]]; then
    INSTANCE_IDS="$2"
    # Create a temp input file with just the requested instance(s)
    TEMP_INPUT=$(mktemp)
    python3 -c '
import json, sys
input_file, ids_arg = sys.argv[1], sys.argv[2]
ids = set(ids_arg.split(","))
with open(input_file) as f:
    for line in f:
        rec = json.loads(line)
        if rec["instance_id"] in ids:
            print(line.strip())
' "$INPUT_FILE" "$INSTANCE_IDS" > "$TEMP_INPUT"
    num_lines=$(wc -l < "$TEMP_INPUT")
    if [[ "$num_lines" -eq 0 ]]; then
        echo "ERROR: no matching instance_id found for: $INSTANCE_IDS"
        rm -f "$TEMP_INPUT"
        exit 1
    fi
    echo "Test mode: running $num_lines instance(s): $INSTANCE_IDS"
    INPUT_FILE="$TEMP_INPUT"
    EXPERIMENT_SUFFIX="test"
    NUM_THREADS=1
fi

OUTPUT_FOLDER="$SCRIPT_DIR/results/${MODEL}_${EXPERIMENT_SUFFIX}"

echo "========================================"
echo "AISQL Baseline Runner"
echo "========================================"
echo "Model:      $MODEL"
echo "Input:      $INPUT_FILE"
echo "Output:     $OUTPUT_FOLDER"
echo "Databases:  $DATABASES_PATH"
echo "Documents:  $DOCUMENTS_PATH"
echo "Threads:    $NUM_THREADS"
echo "Max rounds: $MAX_ROUNDS"
echo "========================================"

mkdir -p "$SCRIPT_DIR/results"

# ---- Start tool server (local; loopback works on Linux and macOS) ----
host="127.0.0.1"
port=$((30000 + RANDOM % 1001))
echo "Starting tool server at $host:$port ..."

cd "$SCRIPT_DIR"
python3 -m servers.serve --workers_per_tool 32 --host "$host" --port "$port" &
server_pid=$!

cleanup() {
    echo "Shutting down tool server (pid=$server_pid)..."
    kill $server_pid 2>/dev/null || true
    # Clean up temp file if created
    [[ -n "${TEMP_INPUT:-}" ]] && rm -f "$TEMP_INPUT"
}
trap cleanup EXIT

sleep 3

# Verify server is up
if ! kill -0 $server_pid 2>/dev/null; then
    echo "ERROR: Tool server failed to start"
    exit 1
fi
echo "Tool server running (pid=$server_pid)"

# ---- Run agent ----
python3 agent/main.py \
    --input_file "$INPUT_FILE" \
    --output_folder "$OUTPUT_FOLDER" \
    --system_prompt_path "$SYSTEM_PROMPT" \
    --databases_path "$DATABASES_PATH" \
    --documents_path "$DOCUMENTS_PATH" \
    --model "$MODEL" \
    --temperature "$TEMPERATURE" \
    --top_p "$TOP_P" \
    --max_new_tokens "$MAX_NEW_TOKENS" \
    --api_host "$host" \
    --api_port "$port" \
    --max_rounds "$MAX_ROUNDS" \
    --num_threads "$NUM_THREADS" \
    --rollout_number "$ROLLOUT_NUMBER"

echo ""
echo "Done! Results saved to: $OUTPUT_FOLDER"
