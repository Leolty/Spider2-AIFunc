# Evaluation

`evaluation/evaluate.py` is the reference scorer. It shows exactly how a prediction is
compared against gold, and you can run it on your own gold SQL.

## How scoring works

For each task, the evaluator runs your prediction and the gold query on Snowflake, then
compares the result tables, generally following Spider 2.0's execution-result comparison.
For each selected gold column, the evaluator looks for a prediction column with matching
values; column names and column order do not have to match, and extra prediction columns are
allowed. The task's `eval_config` then controls the details: row order is ignored when
`ignore_order` is set, only the columns listed in `condition_cols` are selected from the
gold table (all columns when the list is empty), and numeric values match within an absolute
tolerance of `1.01e-2`.

There are two other tolerances to be aware of:

- **Transient execution errors:** each scheduled execution gets up to two retries for
  transient errors such as timeouts or connection failures. The default SQL timeout is 240
  seconds.
- **Multi-run stability:** with `-n N`, the default majority threshold is `N//2 + 1`. In
  `majority` mode, gold runs below that threshold are reported under a separate status
  instead of being treated as a normal mismatch.

Because running these queries is not cheap (see "Submitting results" below), the default is
one execution per query (`-n 1`). The benchmark was verified for determinism when it was
built, so a single execution is enough for most purposes.

You can also run each query several times (`-n N`) and choose how the runs are scored:

- `--match-mode majority` (default): compare the majority result on each side. This guards
  against occasional variation from the model inside a query.
- `--match-mode any`: accept the task if any of the prediction's runs matches any of the
  gold's runs. This is a more lenient reading.

The tool prints overall accuracy with a breakdown by status (matches, mismatches, execution
failures, and so on) and writes per-instance results under the output directory.

## Running it

Put predictions in `--pred-dir` (as `{id}/final.sql` or `{id}.sql`) and gold in `--gold-dir`
(as `{id}.sql`).

```bash
python evaluation/evaluate.py \
    --pred-dir   predictions/my_model \
    --gold-dir   gold \
    --tasks      data/spider2-aifunc.jsonl \
    --output-dir evaluation/results/my_model \
    -n 1 --workers 4
```

To run several executions and score them leniently, add, for example, `-n 5 --match-mode any`.

Evaluation needs Snowflake credentials in `.env` (see [../env.example](../env.example)) with
Cortex AISQL functions enabled. The evaluator itself does not call a separate LLM API.

The repo includes two small examples under `examples/` that use the same layout as a normal
evaluation run. `example_tasks.jsonl` has one task per line with the `db_id` and
`eval_config` that the evaluator needs. `gold_sql/` and `predictions/` each contain one
`{instance_id}.sql` file per task.

```bash
python evaluation/evaluate.py \
    --pred-dir   examples/predictions \
    --gold-dir   examples/gold_sql \
    --tasks      examples/example_tasks.jsonl \
    --output-dir examples/results \
    -n 1 --workers 1
```

## Submitting results

Running AISQL over the Spider2-Snow databases is not cheap. The databases are large, and
every AI function call invokes a model, so evaluating all 393 tasks once already adds up, and
running each query several times multiplies that. Start with a few instances (the evaluator's
`--instances`, or the baseline's `--test`) to confirm your setup works end to end, then scale
up.

Snowflake accounts obtained through the Spider 2.0 access process do not currently have
Cortex AISQL enabled; the AISQL access path for those accounts is still pending.

Because the gold SQL is held out, scoring is not self-service. The official submission process
is still being finalized; for now, send us your predictions and we will score them by hand.
Email [til040@ucsd.edu](mailto:til040@ucsd.edu) a JSONL file with one line per task, each an
object with at least:

- `id`: the task's `instance_id`.
- `pred_sql`: your predicted Snowflake SQL for that task.

Including the `model` or system name helps with attribution. We may ask for a few more fields
as the process takes shape, but `id` and `pred_sql` are enough for us to score a run.
