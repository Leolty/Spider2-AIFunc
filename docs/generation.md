# How the benchmark was generated (reference)

This explains how Spider2-AISQL was built by turning Spider 2.0's traditional SQL queries
into AISQL tasks. It is provided for reference. The generation pipeline requires source
gold SQL and execution results as input. In our build, these came from Spider 2.0 gold
files, which are access-controlled and not redistributed here (see [../DATA.md](../DATA.md)).
You can read how the tasks were made and run the pipeline on your own SQL and execution
results, but you cannot regenerate our tasks from the public release alone.

To run it on your own data you need the Spider2-Snow databases in `resources/` (see
[../DATA.md](../DATA.md)) and Snowflake and LLM credentials in `.env`.

## Input format

Each line of the generation input JSONL describes one source task, a traditional SQL query
that the agent will rewrite into an AISQL task. For public use, prepare a file like this:

```json
{
  "instance_id": "ex1",
  "db_id": "GA360",
  "instruction": "For each marketing channel, count the sessions in July 2017.",
  "gold_sqls": [
    "SELECT channelGrouping, COUNT(*) FROM GA360.PUBLIC.ga_sessions GROUP BY 1"
  ],
  "external_knowledge": "google_analytics_sample.ga_sessions.md",
  "execution_results": [
    {
      "status": "success",
      "num_rows": 12,
      "num_columns": 2,
      "data": [{"CHANNELGROUPING": "Organic Search", "COUNT(*)": 8123}]
    }
  ]
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `instance_id` | yes | Unique id. |
| `db_id` | yes | The Snowflake database the query runs on. |
| `instruction` | yes | The original natural-language question. |
| `gold_sqls` | yes | One or more traditional SQL gold queries. `--mode multi` uses all of them to resolve ambiguity; single mode uses the first. |
| `external_knowledge` | no | The filename of a document under `resources/knowledge/`, or omitted. |
| `execution_results` | no | The gold execution output, used as evidence during generation. If omitted, the agent sees only the SQL and schema. |

A companion gold-tables JSONL maps each `instance_id` to the fully-qualified tables its
query touches:

```json
{"instance_id": "ex1", "gold_tables": ["GA360.PUBLIC.ga_sessions"]}
```

Pass it with `--gold-tables-file my_gold_tables.jsonl`. This file is optional. If it is
omitted, `run_batch.py` still runs and includes schema information without prioritizing the
source tables. In our build, these inputs were derived from the Spider 2.0 gold files, which
are not public.

## Stage 1: generate

`scripts/run_batch.py` runs the generation agent over the source tasks. The first pass
produces the `main` tasks. We then run a second pass with `--diversity`: this uses the same
generation pipeline, but adds a prompt hint asking the agent to prefer under-represented
AISQL functions when the source query can support them. Its purpose is to improve function
coverage. The accepted outputs from this pass are marked as `diversity` tasks with the
`_div` suffix and use the same evaluation setting as the main tasks.

```bash
# Main set. --mode multi lets the agent see all gold SQLs for one instruction and resolve
# ambiguity (multi-gold). Public runs should always pass --input-file.
python scripts/run_batch.py --mode multi \
    --input-file my_source_sql.jsonl \
    --gold-tables-file my_gold_tables.jsonl \
    --output-dir outputs/main

# Diversity set. --diversity asks the agent to look for valid uses of under-represented
# AISQL functions (AI_SENTIMENT, AI_EXTRACT, AI_AGG). Accepted outputs become _div variants.
python scripts/run_batch.py --mode multi --diversity \
    --input-file my_source_sql.jsonl \
    --gold-tables-file my_gold_tables.jsonl \
    --output-dir outputs/diversity
```

## Stage 2: verify determinism (multiple rounds)

AISQL is inherently non-deterministic, because a model runs inside the query. For the
benchmark to be reliably scoreable, each task must still return a stable result across runs.
This stage makes the final set deterministic enough to evaluate.
`scripts/run_determinism_check.py` is one pass: for each instance it executes the query `-n`
times, and if the result is unstable the agent fixes the SQL or the instruction.

One pass is not enough, because a fix must itself be re-verified. So you chain passes,
feeding each output into the next, with an increasing execution budget. Cheap early passes
catch the easy cases, and stricter later passes reduce the remaining unstable cases:

```bash
python scripts/run_determinism_check.py -i outputs/main    -o outputs/main_r1 -n 3
python scripts/run_determinism_check.py -i outputs/main_r1 -o outputs/main_r2 -n 5
python scripts/run_determinism_check.py -i outputs/main_r2 -o outputs/main_r3 -n 10
# Stop when the remaining unstable or failed cases are within your chosen tolerance.
# Repeat the chain for the diversity set.
```

## Stage 3: assemble

`scripts/build_dataset.py` keeps only the instances that pass in the final round and
assembles the internal benchmark. You do not need this script to use the public task file;
it is included to document the release-building process and to support users building a
similar benchmark from their own gold SQL. In our release build, we first assembled the
verified `main` outputs, then appended verified `diversity` outputs. The diversity append
uses the main verified directory as a deduplication reference, so variants already covered
by the main set are not added again.

```bash
# Main set.
python scripts/build_dataset.py \
    --original-data my_source_sql.jsonl \
    --generation-dir outputs/main --verified-dir outputs/main_r3

# Diversity set, appended to the same assembled dataset.
python scripts/build_dataset.py \
    --original-data my_source_sql.jsonl \
    --generation-dir outputs/diversity --verified-dir outputs/diversity_r3 \
    --variant diversity --suffix _div --append \
    --dedup-verified-dir outputs/main_r3
```

`build_dataset` produces the internal benchmark, one directory per instance, with gold. The
public file `data/spider2-aisql.jsonl` is a gold-stripped export of the selected instances:
the same tasks with the gold removed.

## Additional quality validation

After the pipeline, we ran an additional round of instruction-quality validation, a
combination of AI-assisted and human review, to raise the quality of the final benchmark:

- **Instruction-clarity review:** we checked that each instruction is unambiguous and fully
  specifies the expected result, and refined or dropped the ones that were not.
- **Decorative-AI audit:** we kept only tasks where an AI function is essential, and removed
  any whose result a traditional SQL query could reproduce on its own.
