# Guide for coding agents

This file orients an agent working in this repository. It describes what each part is for,
which files to change for common tasks, and what to leave alone. The [README.md](README.md)
is the short human overview; this file is the detailed version.

## What this repo is

Spider2-AISQL is a benchmark for AI-Native Text-to-SQL. Each task is a natural-language
question over a Snowflake database whose answer requires at least one Cortex AISQL function
(`AI_CLASSIFY`, `AI_FILTER`, `AI_AGG`, `AI_EXTRACT`, `AI_SIMILARITY`, `AI_SENTIMENT`). A
solution is a single Snowflake SQL query. The benchmark is derived from Spider 2.0.

The repository has four parts that are largely independent:

1. **The dataset** is the shipped product.
2. **Generation** built the dataset from Spider 2.0 source SQL. It is reference code.
3. **Evaluation** scores predictions against gold SQL. It is reference code.
4. **Baseline** is an agent that reads the tasks and writes predictions.

Generation and evaluation both need the **gold SQL**, which is held out of this release.
You can read and run them on your own data, but you cannot reproduce or officially score
the shipped tasks without that gold.

## Repository map

```
data/spider2-aisql.jsonl     Part 1. The 393 tasks, one JSON object per line. Task only.
docs/                        One short guide per part (dataset, generation, evaluation, baseline).
DATA.md                      Attribution, terms, and how to obtain the resources.

scripts/                     Part 2 entry points (the generation pipeline).
  run_batch.py                 Stage 1: turn source SQL into AISQL tasks.
  run_determinism_check.py     Stage 2: verify a task returns stable results (run in rounds).
  build_dataset.py             Stage 3: assemble the verified tasks.
  setup_resources.py           Report which databases and knowledge docs are present or missing.
src/                         Library used by the generation scripts.
  agents/                      The generation agents (sql, multi_sql, determinism).
  core/                        SQL execution, result comparison, schema loading, LLM clients, prompts.
  pipelines/                   The determinism pipeline used by run_determinism_check.py.
  utils/                       File IO and logging helpers.

evaluation/evaluate.py       Part 3. Executes gold and predictions and scores the result (N=1 by default).

baseline/spider-agent-tc/    Part 4. The agent baseline.
  run_aisql.sh                 Main run script (Linux and macOS). Set model/endpoint via env; limits in script.
  run_aisql_openrouter.sh      Same agent pointed at OpenRouter.
  agent/                        The agent loop, LLM calls, prompt building, message parsing.
  servers/                      A local tool server (Snowflake SQL tool, bash tool, terminator).
  prompts/                      System prompt and the Cortex AI function reference.
  credentials/                  Snowflake credentials for the agent (example file only in git).
  extract_prediction_sql.py    Pull the final SQL out of the agent transcripts into one .sql per task.

resources/                   Not in git. Spider2-Snow databases and knowledge docs (see DATA.md).
gold/                        Not in git. Gold SQL, one {instance_id}.sql per task. You supply it.
```

## Credentials

There are two separate credential paths. Set up whichever the part you are using needs.

**Pipeline and evaluation** read environment variables, loaded from `.env`. Copy
`env.example` to `.env` and fill in:

- Snowflake: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`,
  `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_TOKEN`. The warehouse must have Cortex AISQL functions
  enabled.
- One LLM provider: use `LLM_PROVIDER=openai` for OpenAI or any OpenAI-compatible
  endpoint, then fill in `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
  Bedrock is optional through `LLM_PROVIDER=aws_bedrock`.

**The baseline agent** uses its own files, not `.env`:

- Snowflake: copy `baseline/spider-agent-tc/credentials/snowflake_credential.example.json`
  to `snowflake_credential.json` in the same folder and fill it in. The `password` field
  takes your Snowflake token.
- The agent's own LLM: configured with shell environment variables, not in `.env`. Export
  `OPENAI_API_BASE`, `OPENAI_API_KEY`, and `MODEL` before running `run_aisql.sh`.

Never commit a real `.env` or a real `snowflake_credential.json`. Only the `env.example`
and `*.example.json` templates belong in git.

## Resources

The tasks reference Spider2-Snow databases and external-knowledge documents by name. They
are not shipped, because they are access-controlled Spider 2.0 data. They belong at:

```
resources/databases/<DB_ID>/...
resources/knowledge/<doc>.md
```

Run `python scripts/setup_resources.py` to print the acquisition steps and to see which
databases and documents are present or missing. Details are in [DATA.md](DATA.md).

## Common tasks

**Run the baseline with a different model.** Export `MODEL`, `OPENAI_API_BASE`, and
`OPENAI_API_KEY` before running `baseline/spider-agent-tc/run_aisql.sh`. For an
OpenRouter-hosted model, use `run_aisql_openrouter.sh` and set `MODEL`. The run script and
environment variables are the intended knobs; do not edit the agent code in `agent/` for a
model swap. See [docs/baseline.md](docs/baseline.md).

**Score predictions.** The full benchmark gold is held out. If you have local gold, put one
`{instance_id}.sql` per task under a gold directory and run
`python evaluation/evaluate.py --pred-dir <dir> --gold-dir <gold_dir>`. This defaults to one
execution per query (`-n 1`); raise `-n` for multiple runs and pick `--match-mode majority`
(default) or `--match-mode any`. For public examples and the current submission format, see
[docs/evaluation.md](docs/evaluation.md).

**Turn baseline output into predictions.** After a run, the transcripts are in
`baseline/spider-agent-tc/results/<model>_<suffix>/`. Run
`python baseline/spider-agent-tc/extract_prediction_sql.py <results_dir> <out_dir>` to
write one `.sql` per task, then point the evaluator at `<out_dir>`.

**Generate AISQL tasks from your own SQL.** Provide a source JSONL in the format described in
[docs/generation.md](docs/generation.md), then run
`python scripts/run_batch.py --mode multi --input-file <your.jsonl> --output-dir outputs/run`.
This needs Snowflake and LLM credentials in `.env`.

**Inspect or filter the dataset.** `data/spider2-aisql.jsonl` is plain JSON lines. Read it
directly. Field meanings are in [docs/dataset.md](docs/dataset.md).

## What not to touch

- **Gold SQL.** The benchmark ships task-only. Do not add gold SQL or gold results to the
  repo, and keep the `gold/` directory out of version control.
- **Secrets.** Do not commit `.env` or `credentials/snowflake_credential.json`. Do not add
  Snowflake account names, tokens, or private endpoints to any file.
- **Resources.** Do not commit anything under `resources/`. It is external Spider 2.0 data.
- **The dataset file**, unless the task is specifically to change tasks. It is the shipped
  product, and evaluation and the baseline both read it directly.

## Terminology

The source queries from Spider 2.0 are **traditional SQL**. AISQL is inherently
non-deterministic, because a model runs inside the query. The determinism check exists to
make each task stable enough to score reliably. When writing docs or comments, describe the
source as "traditional SQL," not "deterministic SQL."

## Notes and gotchas

- Running AISQL over the Spider2-Snow databases is not free. Current Spider 2.0-provided
  accounts do not have Cortex AISQL enabled; the AISQL access path for those accounts is
  still pending. Start small (`--test` or `--instances`) before a full run.
- Prose style in this repo: plain and direct, and no em dashes.
