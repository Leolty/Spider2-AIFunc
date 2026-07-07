# The dataset

The benchmark is a single JSONL file, `data/spider2-aifunc.jsonl`, with one task per line.
It is task-only: the gold SQL and gold results are held out (see [../DATA.md](../DATA.md)).

## Fields

```json
{
  "instance_id": "sf_bq003",
  "db_id": "GA360",
  "variant": "main",
  "instruction": "For sessions between April 1 and July 31, 2017, ...",
  "ai_functions": ["AI_CLASSIFY", "AI_FILTER"],
  "external_knowledge": "google_analytics_sample.ga_sessions.md",
  "eval_config": { "ignore_order": false, "condition_cols": [] }
}
```

| Field | Meaning |
|-------|---------|
| `instance_id` | Unique id. The prefix marks the Spider2-Snow source family (`sf_bq*` for BigQuery, `sf_ga*` for GA4, `sf_local*` for local). A `_div` suffix marks a diversity variant. |
| `db_id` | The Spider2-Snow database the query runs on. Obtain it with `scripts/setup_resources.py`. |
| `variant` | `main` or `diversity`. Diversity variants were added during generation to broaden function coverage; see [generation.md](generation.md). |
| `instruction` | The natural-language task. Solving it requires at least one Cortex AISQL function. |
| `ai_functions` | Dataset annotation for the intended Cortex AISQL function or functions. It is included for analysis and filtering, not as a reference input to the model. |
| `external_knowledge` | The filename of a knowledge document under `resources/knowledge/` that the task needs, or `null`. |
| `eval_config` | How scoring compares results: `ignore_order` (whether row order matters) and `condition_cols` (0-based column indices to compare; empty means all columns). |

A prediction is one Snowflake SQL query per `instance_id`. In the standard setting, methods
should not provide the `ai_functions` annotation to the model as input. If a method does use
it, report that setting explicitly; the baseline in this repo does not use it.

## Composition (393 tasks)

- **Variants:** 289 `main` and 104 `diversity` (`_div`).
- **Databases:** 117 distinct Spider2-Snow databases.
- **AI functions** (a task may use more than one; the average is 1.69 per task):

  | function | tasks |
  |----------|-------|
  | AI_CLASSIFY | 227 |
  | AI_SIMILARITY | 153 |
  | AI_FILTER | 148 |
  | AI_AGG | 66 |
  | AI_EXTRACT | 48 |
  | AI_SENTIMENT | 22 |

- 69 tasks reference an external-knowledge document.

## Generation note

The `main` and `diversity` variants come from the generation pipeline. The diversity pass
was used only to broaden coverage of under-represented AISQL functions, not to define a
different evaluation setting. Released tasks also passed determinism checks and
instruction-quality review. See [generation.md](generation.md) for the construction
process.
