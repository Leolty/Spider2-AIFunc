# Running a baseline

`baseline/spider-agent-tc/` is a lightly adapted version of Spider 2.0's
`spider-agent-tc`. It keeps the same round-based tool-calling loop: an LLM inspects schema
files, runs Snowflake SQL through a tool, and terminates with a final SQL query. For
Spider2-AIFunc, we mainly add Cortex AISQL guidance to the prompt and make minor runtime
adjustments for AISQL workloads, which can take longer, return larger intermediate outputs,
and expose small differences in tool-call formats across models.

Run `--test` first. The baseline executes generated SQL against Snowflake, and each Cortex
AISQL function call can add cost. Running released tasks also requires access to the
Spider2-Snow databases and a warehouse with Cortex AISQL enabled. Current Spider 2.0-provided
accounts do not have Cortex AISQL enabled; the AISQL access path for those accounts is still
pending.

Security note: this baseline exposes a local bash tool to the model. The tool is useful for
schema inspection, but it executes shell commands on your machine. Run it only in a trusted
workspace with credentials and files you are comfortable making available to the agent.

## Prerequisites

Install the dependencies and check that the Spider2-Snow resources are present:

```bash
python scripts/setup_resources.py
```

The baseline has its own configuration and does not read the repo-level `.env`.

**Snowflake credential for SQL execution.** Copy
`baseline/spider-agent-tc/credentials/snowflake_credential.example.json` to
`baseline/spider-agent-tc/credentials/snowflake_credential.json` and fill it in. The
`password` field is your Snowflake token. This is the Snowflake account used by the
`execute_snowflake_sql` tool.

**LLM credential for the agent.** Set an OpenAI-compatible chat-completions endpoint, its
API key, and the model id:

```bash
export OPENAI_API_BASE=https://api.openai.com/v1
export OPENAI_API_KEY=...
export MODEL=<model-id>
```

## 1. Run the agent

`run_aisql.sh` runs the baseline on Linux or macOS.

```bash
bash baseline/spider-agent-tc/run_aisql.sh                    # all 393 tasks
bash baseline/spider-agent-tc/run_aisql.sh --test sf_bq003    # one task
```

The raw per-task transcripts are written to
`baseline/spider-agent-tc/results/<model>_<suffix>/`.

For OpenRouter, use `run_aisql_openrouter.sh` and set `MODEL` to an OpenRouter model id.

## 2. Extract predicted SQL

The evaluator reads one SQL file per task. Extract final SQL from the raw transcripts with:

```bash
python baseline/spider-agent-tc/extract_prediction_sql.py \
    baseline/spider-agent-tc/results/<model>_<suffix> \
    baseline/spider-agent-tc/parsed_sql/<model>_<suffix>
```

The output directory contains files named `{instance_id}.sql`.

## 3. Evaluate or submit predictions

Full benchmark gold SQL is not included in the public release, so the full benchmark is not
self-scoring from this repo alone. To check the evaluator layout, run the small examples in
[evaluation.md](evaluation.md). The official submission process is still pending; that page
also describes the current interim format for sending extracted SQL predictions.
