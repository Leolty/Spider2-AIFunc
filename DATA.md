# Data, attribution, and terms

## Attribution

Spider2-AIFunc is derived from [Spider 2.0](https://github.com/xlang-ai/Spider2) (ICLR
2025), which is released under the MIT License, Copyright (c) 2024 bird_sql. We reuse the
Spider2-Snow database environments and build AI-Native Text-to-SQL tasks on top of a
subset of its queries. The MIT license notice is kept in `third_party/SPIDER2_LICENSE`.

## What this repo includes

- **The task set** (`data/spider2-aifunc.jsonl`, one task per line): 393 AISQL tasks. Each
  task carries our natural-language instruction, the target `ai_functions`, the Snowflake
  database it runs on, and an evaluation config. It is task-only, with no gold SQL and no
  gold results.
- **The evaluation code** (`evaluation/`): the exact method we use to score, published so
  the method is transparent. Because scoring executes held-out gold, it is a reference
  implementation. See [docs/evaluation.md](docs/evaluation.md).

## What is not included

- **Full gold SQL and gold results.** These are held out, the same way Spider 2.0 holds out
  its own gold. The repo includes only a small set of illustrative evaluation examples under
  `examples/`.
- **Database schemas and sample data** (`resources/databases/`). This is Spider2-Snow data
  and is access-controlled. You obtain it from Spider 2.0, not from this repo.
- **Intermediate generation artifacts and traces.** These are not released.

## Getting the resources (required to run anything)

The 393 tasks reference 117 Spider2-Snow databases and 42 external-knowledge documents by
name. Both come from Spider 2.0, and the databases are access-controlled Snowflake data. To
set them up:

1. Request Snowflake access and configure your credentials by following Spider 2.0's
   [Snowflake guideline](https://github.com/xlang-ai/Spider2/blob/main/assets/Snowflake_Guideline.md),
   then fill in `.env` (see `env.example`). Current Spider 2.0-provided accounts do not
   have Cortex AISQL enabled; the AISQL access path for those accounts is still pending.
2. Clone Spider 2.0 and run its setup, which materializes the schema files and knowledge
   documents locally:
   ```bash
   git clone https://github.com/xlang-ai/Spider2.git
   cd Spider2/methods/spider-agent-snow && python spider_agent_setup_snow.py
   ```
3. Point this repo at them, either by symlinking or by copying:
   ```bash
   mkdir -p resources
   ln -s /path/to/Spider2/spider2-snow/resources/databases resources/databases
   ln -s /path/to/Spider2/spider2-snow/resources/knowledge  resources/knowledge
   ```

Running `python scripts/setup_resources.py` prints these steps and reports which databases
and documents are present and which are missing.

> Note: Spider 2.0 recommends not using released gold SQL for fine-tuning.
