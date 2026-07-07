#!/usr/bin/env python
"""
AI SQL Baseline Evaluation with N-Execution Majority Voting

Handles non-deterministic AI SQL by executing both gold and predicted SQL
multiple times, finding majority results via cluster-based comparison,
and comparing the majority DataFrames.

Usage:
    python evaluation/evaluate.py \
        --pred-dir predictions/my_model \
        --gold-dir gold \
        --output-dir evaluation/results/my_model

    # Specific instances, resume from previous run
    python evaluation/evaluate.py \
        --pred-dir ... --gold-dir ... --output-dir ... \
        --instances sf001 sf002 --resume
"""
import sys
import os
import json
import argparse
import time
import threading
import html
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from src.core.sql_executor import SnowflakeExecutor, ExecutionResult
from src.core.comparison import (
    compare_pandas_table,
    check_execution_consistency,
    ConsistencyResult,
)
from src.utils.file_io import read_jsonl, write_jsonl, read_text, CustomJSONEncoder


# ============================================================================
# Data Loading
# ============================================================================

def load_benchmark(
    tasks_path: Path,
    gold_dir: Path,
    instance_ids: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Load the benchmark: public tasks from a JSONL file + gold SQL from a
    (private) gold directory.

    Reads:
      - tasks_path : one JSON object per line (instance_id, db_id, eval_config, ...)
      - gold_dir   : one gold query per instance at <gold_dir>/<instance_id>.sql

    Gold is held out of the public release, so this evaluator is a reference
    implementation: point --gold-dir at your own gold to run it. Instances with
    no matching gold file are skipped.

    Returns dict keyed by instance_id with: instance_id, db_id, gold_sql,
    eval_config, instruction.
    """
    benchmark: Dict[str, Dict[str, Any]] = {}
    missing_gold: List[str] = []

    for row in read_jsonl(tasks_path):
        iid = row["instance_id"]
        if instance_ids and iid not in instance_ids:
            continue

        gold_path = gold_dir / f"{iid}.sql"
        if not gold_path.exists():
            missing_gold.append(iid)
            continue
        gold_sql = read_text(gold_path).strip()
        if not gold_sql:
            missing_gold.append(iid)
            continue

        benchmark[iid] = {
            "instance_id": iid,
            "db_id": row["db_id"],
            "gold_sql": gold_sql,
            "eval_config": row.get("eval_config", {"ignore_order": True, "condition_cols": []}),
            "instruction": row.get("instruction", ""),
        }

    if missing_gold:
        print(f"  WARNING: Skipped {len(missing_gold)} instances with no gold in {gold_dir}:", flush=True)
        for s in missing_gold[:10]:
            print(f"    {s}", flush=True)
        if len(missing_gold) > 10:
            print(f"    ... and {len(missing_gold) - 10} more", flush=True)
    return benchmark


def load_predictions(pred_dir: Path, instance_ids: Optional[List[str]] = None) -> Dict[str, str]:
    """Load predicted SQL from either {pred_dir}/{id}/final.sql or {pred_dir}/{id}.sql."""
    predictions = {}
    for entry in sorted(pred_dir.iterdir()):
        if entry.is_dir():
            instance_id = entry.name
            if instance_ids and instance_id not in instance_ids:
                continue
            sql_path = entry / "final.sql"
            if sql_path.exists():
                sql = html.unescape(read_text(sql_path).strip())
                if sql:
                    predictions[instance_id] = sql
        elif entry.is_file() and entry.suffix == ".sql":
            instance_id = entry.stem
            if instance_ids and instance_id not in instance_ids:
                continue
            sql = html.unescape(read_text(entry).strip())
            if sql:
                predictions[instance_id] = sql
    return predictions


# ============================================================================
# N-Execution Engine
# ============================================================================

@dataclass
class SingleExecution:
    """Record of one SQL execution attempt."""
    run: int
    status: str  # 'success' or 'error'
    num_rows: int = 0
    num_columns: int = 0
    exec_time: float = 0.0
    error: Optional[str] = None


TRANSIENT_ERROR_KEYWORDS = [
    "timeout", "timed out", "exceeded", "could not connect",
    "connection", "network", "unavailable", "too busy",
    "warehouse", "resource", "throttl", "capacity",
    "canceled",
    "internal error",
]
MAX_RETRIES_PER_RUN = 2
RETRY_WAIT_SECONDS = 15


def _is_transient_error(error_msg: str) -> bool:
    """Check if an error looks transient and worth retrying."""
    lower = error_msg.lower()
    return any(kw in lower for kw in TRANSIENT_ERROR_KEYWORDS)


def execute_sql_n_times(
    executor: SnowflakeExecutor,
    sql: str,
    db_id: str,
    n: int,
    timeout: int,
    label: str,
    instance_id: str,
) -> Tuple[List[SingleExecution], List[pd.DataFrame]]:
    """
    Execute a SQL query n times, collecting execution records and DataFrames.

    Returns:
        (execution_records, successful_dataframes)
        execution_records has exactly n entries.
        successful_dataframes contains only DataFrames from successful runs,
        in the same order as their corresponding records.
    """
    records: List[SingleExecution] = []
    dataframes: List[pd.DataFrame] = []

    for i in range(1, n + 1):
        result = None
        elapsed = 0.0

        for attempt in range(1, MAX_RETRIES_PER_RUN + 2):  # 1 initial + MAX_RETRIES retries
            executor.set_database(db_id)

            start = time.time()
            result = executor.execute(sql, timeout=timeout)
            elapsed = time.time() - start

            if result.status == "success":
                break

            error_msg = result.error or "Unknown error"
            if attempt <= MAX_RETRIES_PER_RUN and _is_transient_error(error_msg):
                print(
                    f"    [{instance_id}] {label} run {i}/{n}: "
                    f"TRANSIENT ERROR (attempt {attempt}), retrying in {RETRY_WAIT_SECONDS}s - {error_msg[:80]}",
                    flush=True,
                )
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                break

        if result.status == "success" and result.data:
            rec = SingleExecution(
                run=i, status="success",
                num_rows=result.num_rows,
                num_columns=result.num_columns,
                exec_time=round(elapsed, 3),
            )
            records.append(rec)
            dataframes.append(pd.DataFrame(result.data))
            print(
                f"    [{instance_id}] {label} run {i}/{n}: "
                f"{result.num_rows} rows, {elapsed:.1f}s",
                flush=True,
            )
        elif result.status == "success" and not result.data:
            rec = SingleExecution(
                run=i, status="success",
                num_rows=0, num_columns=0,
                exec_time=round(elapsed, 3),
            )
            records.append(rec)
            dataframes.append(pd.DataFrame())
            print(
                f"    [{instance_id}] {label} run {i}/{n}: "
                f"0 rows (empty), {elapsed:.1f}s",
                flush=True,
            )
        else:
            error_msg = result.error or "Unknown error"
            rec = SingleExecution(
                run=i, status="error",
                exec_time=round(elapsed, 3),
                error=error_msg[:500],
            )
            records.append(rec)
            print(
                f"    [{instance_id}] {label} run {i}/{n}: "
                f"ERROR - {error_msg[:80]}",
                flush=True,
            )

    return records, dataframes


# ============================================================================
# Majority Finding
# ============================================================================

def find_majority_dataframe(
    dataframes: List[pd.DataFrame],
    ignore_order: bool,
    condition_cols: List[int],
) -> Tuple[Optional[pd.DataFrame], int]:
    """
    Find the majority DataFrame from a list of execution results.

    Returns:
        (majority_df, majority_size)
        majority_df is None if dataframes is empty.
    """
    if not dataframes:
        return None, 0

    if len(dataframes) == 1:
        return dataframes[0], 1

    consistency = check_execution_consistency(
        dataframes,
        ignore_order=ignore_order,
        condition_cols=condition_cols,
    )

    majority_size = consistency.consistent_count
    inconsistent_set = set(consistency.inconsistent_executions)

    # Pick the first DataFrame that belongs to the majority cluster (1-indexed)
    for idx in range(len(dataframes)):
        if (idx + 1) not in inconsistent_set:
            return dataframes[idx], majority_size

    # Fallback (shouldn't happen)
    return dataframes[0], majority_size


# ============================================================================
# Per-Instance Evaluation
# ============================================================================

@dataclass
class InstanceEvalResult:
    instance_id: str
    db_id: str = ""
    instruction: str = ""
    score: int = 0
    status: str = ""  # match | mismatch | gold_execution_failed | gold_insufficient | gold_unreliable_match | gold_unreliable_mismatch | pred_execution_failed | error
    num_executions: int = 0
    gold_majority_size: int = 0
    gold_majority_ratio: str = ""  # e.g. "8/10"
    pred_majority_size: int = 0
    pred_majority_ratio: str = ""  # e.g. "10/10"
    gold_successes: int = 0
    gold_failures: int = 0
    pred_successes: int = 0
    pred_failures: int = 0
    gold_total_time: float = 0.0
    pred_total_time: float = 0.0
    eval_config: Dict[str, Any] = field(default_factory=dict)
    error_info: Optional[str] = None


def evaluate_single_instance(
    instance_id: str,
    gold_sql: str,
    pred_sql: str,
    db_id: str,
    eval_config: Dict[str, Any],
    instruction: str,
    executor: SnowflakeExecutor,
    num_executions: int,
    majority_threshold: int,
    timeout: int,
    output_instance_dir: Optional[Path],
    match_mode: str = "majority",
) -> InstanceEvalResult:
    """
    Evaluate one instance: execute gold & pred N times, then score.

    match_mode controls scoring:
    - "majority": take the majority result on each side and compare them (default).
    - "any": accept if any successful pred result matches any successful gold result.
    Writes per-execution logs, per-run CSVs, and majority CSVs to output_instance_dir.
    """
    ignore_order = eval_config.get("ignore_order", True)
    condition_cols = eval_config.get("condition_cols", []) or []

    result = InstanceEvalResult(
        instance_id=instance_id,
        db_id=db_id,
        instruction=instruction,
        num_executions=num_executions,
        eval_config=eval_config,
    )

    # ---- Execute gold SQL N times ----
    print(f"  [{instance_id}] Executing gold SQL {num_executions} times...", flush=True)
    gold_records, gold_dfs = execute_sql_n_times(
        executor, gold_sql, db_id, num_executions, timeout, "gold", instance_id,
    )
    result.gold_successes = sum(1 for r in gold_records if r.status == "success")
    result.gold_failures = sum(1 for r in gold_records if r.status == "error")
    result.gold_total_time = round(sum(r.exec_time for r in gold_records), 3)

    # ---- Execute pred SQL N times ----
    print(f"  [{instance_id}] Executing pred SQL {num_executions} times...", flush=True)
    pred_records, pred_dfs = execute_sql_n_times(
        executor, pred_sql, db_id, num_executions, timeout, "pred", instance_id,
    )
    result.pred_successes = sum(1 for r in pred_records if r.status == "success")
    result.pred_failures = sum(1 for r in pred_records if r.status == "error")
    result.pred_total_time = round(sum(r.exec_time for r in pred_records), 3)

    # ---- Save execution logs and per-run CSVs ----
    is_single = (num_executions == 1)

    if output_instance_dir:
        output_instance_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl([asdict(r) for r in gold_records], output_instance_dir / "gold_executions.jsonl")
        write_jsonl([asdict(r) for r in pred_records], output_instance_dir / "pred_executions.jsonl")

        if is_single:
            if gold_dfs:
                gold_dfs[0].to_csv(output_instance_dir / "gold.csv", index=False)
            if pred_dfs:
                pred_dfs[0].to_csv(output_instance_dir / "pred.csv", index=False)
        else:
            runs_dir = output_instance_dir / "runs"
            runs_dir.mkdir(exist_ok=True)
            df_idx = 0
            for rec in gold_records:
                if rec.status == "success":
                    gold_dfs[df_idx].to_csv(runs_dir / f"gold_run_{rec.run}.csv", index=False)
                    df_idx += 1
            df_idx = 0
            for rec in pred_records:
                if rec.status == "success":
                    pred_dfs[df_idx].to_csv(runs_dir / f"pred_run_{rec.run}.csv", index=False)
                    df_idx += 1

    # ---- Check gold execution viability ----
    if result.gold_successes == 0:
        result.status = "gold_execution_failed"
        result.score = 0
        result.error_info = "All gold SQL executions failed"
        _save_instance_result(result, output_instance_dir)
        print(f"  [{instance_id}] GOLD FAILED (0/{num_executions} succeeded)", flush=True)
        return result

    # ---- Check pred execution viability ----
    if result.pred_successes == 0:
        result.status = "pred_execution_failed"
        result.score = 0
        result.error_info = "All pred SQL executions failed"
        first_err = next((r.error for r in pred_records if r.error), "Unknown")
        result.error_info += f": {first_err[:200]}"
        _save_instance_result(result, output_instance_dir)
        print(f"  [{instance_id}] PRED FAILED (0/{num_executions} succeeded)", flush=True)
        return result

    # ---- "any" match mode: accept if any successful pred matches any successful gold ----
    if match_mode == "any":
        score = 0
        for pdf in pred_dfs:
            if any(
                compare_pandas_table(
                    pdf, gdf,
                    condition_cols if condition_cols else None,
                    ignore_order=ignore_order,
                ) == 1
                for gdf in gold_dfs
            ):
                score = 1
                break
        result.score = score
        result.status = "match" if score == 1 else "mismatch"
        result.gold_majority_ratio = f"-/{result.gold_successes}"
        result.pred_majority_ratio = f"-/{result.pred_successes}"
        _save_instance_result(result, output_instance_dir)
        print(
            f"  [{instance_id}] {'MATCH' if score == 1 else 'MISMATCH'} [any] "
            f"(gold_ok={result.gold_successes}, pred_ok={result.pred_successes})",
            flush=True,
        )
        return result

    # ---- Find gold majority ----
    gold_majority_df, gold_maj_size = find_majority_dataframe(gold_dfs, ignore_order, condition_cols)
    result.gold_majority_size = gold_maj_size
    result.gold_majority_ratio = f"{gold_maj_size}/{result.gold_successes}"

    gold_reliable = gold_maj_size >= majority_threshold

    if gold_maj_size == 0:
        result.status = "gold_insufficient"
        result.score = 0
        result.error_info = f"Gold majority size 0 (successes={result.gold_successes})"
        _save_instance_result(result, output_instance_dir)
        print(f"  [{instance_id}] GOLD INSUFFICIENT (majority=0)", flush=True)
        return result

    # ---- Find pred majority ----
    pred_majority_df, pred_maj_size = find_majority_dataframe(pred_dfs, ignore_order, condition_cols)
    result.pred_majority_size = pred_maj_size
    result.pred_majority_ratio = f"{pred_maj_size}/{result.pred_successes}"

    # ---- Save majority CSVs (only when n>1; n=1 already saved as gold.csv/pred.csv) ----
    if output_instance_dir and not is_single:
        if gold_majority_df is not None and not gold_majority_df.empty:
            gold_majority_df.to_csv(output_instance_dir / "gold_majority.csv", index=False)
        if pred_majority_df is not None and not pred_majority_df.empty:
            pred_majority_df.to_csv(output_instance_dir / "pred_majority.csv", index=False)

    # ---- Compare ----
    if pred_majority_df is None:
        result.score = 0
        result.status = "pred_execution_failed"
        result.error_info = "No valid pred majority DataFrame"
        _save_instance_result(result, output_instance_dir)
        return result

    try:
        score = compare_pandas_table(
            pred_majority_df, gold_majority_df,
            condition_cols if condition_cols else None,
            ignore_order=ignore_order,
        )
        result.score = score
    except Exception as e:
        result.score = 0
        result.status = "error"
        result.error_info = f"Comparison error: {str(e)[:300]}"
        _save_instance_result(result, output_instance_dir)
        print(f"  [{instance_id}] COMPARISON ERROR: {e}", flush=True)
        return result

    # ---- Assign status ----
    if gold_reliable:
        result.status = "match" if score == 1 else "mismatch"
    else:
        result.status = "gold_unreliable_match" if score == 1 else "gold_unreliable_mismatch"

    icon = "MATCH" if score == 1 else "MISMATCH"
    reliability = "" if gold_reliable else " [gold_unreliable]"
    print(
        f"  [{instance_id}] {icon}{reliability} "
        f"(gold_maj={gold_maj_size}, pred_maj={pred_maj_size})",
        flush=True,
    )

    _save_instance_result(result, output_instance_dir)
    return result


def _save_instance_result(result: InstanceEvalResult, output_dir: Optional[Path]):
    """Save eval_result.json for a single instance."""
    if not output_dir:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    result_dict = asdict(result)
    with open(output_dir / "eval_result.json", "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False, cls=CustomJSONEncoder)


# ============================================================================
# Main Pipeline
# ============================================================================

def _evaluate_worker(
    instance_id: str,
    benchmark: Dict[str, Dict[str, Any]],
    predictions: Dict[str, str],
    instances_dir: Path,
    num_executions: int,
    majority_threshold: int,
    timeout: int,
    executor: SnowflakeExecutor,
    match_mode: str = "majority",
) -> InstanceEvalResult:
    """Worker function: evaluate a single instance using a given executor."""
    bench = benchmark[instance_id]
    instance_output = instances_dir / instance_id
    try:
        return evaluate_single_instance(
            instance_id=instance_id,
            gold_sql=bench["gold_sql"],
            pred_sql=predictions[instance_id],
            db_id=bench["db_id"],
            eval_config=bench["eval_config"],
            instruction=bench.get("instruction", ""),
            executor=executor,
            num_executions=num_executions,
            majority_threshold=majority_threshold,
            timeout=timeout,
            output_instance_dir=instance_output,
            match_mode=match_mode,
        )
    except Exception as e:
        print(f"  [{instance_id}] EXCEPTION: {e}", flush=True)
        r = InstanceEvalResult(
            instance_id=instance_id,
            db_id=bench["db_id"],
            status="error",
            error_info=str(e)[:500],
            eval_config=bench["eval_config"],
        )
        _save_instance_result(r, instance_output)
        return r


def run_evaluation(
    benchmark: Dict[str, Dict[str, Any]],
    predictions: Dict[str, str],
    output_dir: Path,
    num_executions: int = 10,
    majority_threshold: int = 6,
    timeout: int = 240,
    resume: bool = False,
    workers: int = 1,
    match_mode: str = "majority",
) -> List[InstanceEvalResult]:
    """Run evaluation on all matched instances, optionally in parallel."""
    eval_ids = sorted(set(benchmark.keys()) & set(predictions.keys()))

    if not eval_ids:
        print("No matching instances between benchmark and predictions!")
        return []

    missing = sorted(set(benchmark.keys()) - set(predictions.keys()))

    print(f"Evaluation Configuration:")
    print(f"  Benchmark instances: {len(benchmark)}")
    print(f"  Predictions available: {len(predictions)}")
    print(f"  To evaluate: {len(eval_ids)}")
    if missing:
        print(f"  Missing predictions: {len(missing)}")
    print(f"  N executions: {num_executions}")
    print(f"  Majority threshold: {majority_threshold}")
    print(f"  Timeout: {timeout}s")
    print(f"  Resume: {resume}")
    print(f"  Workers: {workers}")
    print()

    instances_dir = output_dir / "instances"
    instances_dir.mkdir(parents=True, exist_ok=True)

    results: List[InstanceEvalResult] = []
    todo_ids: List[str] = []
    skipped = 0

    for instance_id in eval_ids:
        instance_output = instances_dir / instance_id
        if resume and (instance_output / "eval_result.json").exists():
            try:
                with open(instance_output / "eval_result.json") as f:
                    existing = json.load(f)
                r = InstanceEvalResult(**{
                    k: existing[k] for k in InstanceEvalResult.__dataclass_fields__
                    if k in existing
                })
                results.append(r)
                skipped += 1
                continue
            except (json.JSONDecodeError, TypeError):
                pass
        todo_ids.append(instance_id)

    if skipped:
        print(f"Resumed {skipped} previously completed instances.")

    if not todo_ids:
        print("All instances already completed.")
        return results

    print(f"Instances to run: {len(todo_ids)}")
    print()

    if workers <= 1:
        executor = SnowflakeExecutor()
        executor.connect()
        try:
            for instance_id in tqdm(todo_ids, desc="Evaluating"):
                r = _evaluate_worker(
                    instance_id, benchmark, predictions, instances_dir,
                    num_executions, majority_threshold, timeout, executor,
                    match_mode=match_mode,
                )
                results.append(r)
        finally:
            executor.disconnect()
    else:
        print(f"Starting {workers} parallel workers with independent Snowflake connections...")
        executors: List[SnowflakeExecutor] = []
        for i in range(workers):
            ex = SnowflakeExecutor()
            ex.connect()
            executors.append(ex)
            print(f"  Worker {i+1}/{workers} connected.", flush=True)

        executor_lock = threading.Lock()
        executor_pool = list(executors)

        def acquire_executor() -> SnowflakeExecutor:
            while True:
                with executor_lock:
                    if executor_pool:
                        return executor_pool.pop()
                time.sleep(0.1)

        def release_executor(ex: SnowflakeExecutor):
            with executor_lock:
                executor_pool.append(ex)

        pbar = tqdm(total=len(todo_ids), desc="Evaluating")

        def worker_fn(iid: str) -> InstanceEvalResult:
            ex = acquire_executor()
            try:
                return _evaluate_worker(
                    iid, benchmark, predictions, instances_dir,
                    num_executions, majority_threshold, timeout, ex,
                    match_mode=match_mode,
                )
            finally:
                release_executor(ex)

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(worker_fn, iid): iid for iid in todo_ids}
                for future in as_completed(futures):
                    iid = futures[future]
                    try:
                        r = future.result()
                        results.append(r)
                    except Exception as e:
                        print(f"  [{iid}] WORKER EXCEPTION: {e}", flush=True)
                        bench = benchmark[iid]
                        r = InstanceEvalResult(
                            instance_id=iid,
                            db_id=bench["db_id"],
                            status="error",
                            error_info=str(e)[:500],
                            eval_config=bench["eval_config"],
                        )
                        results.append(r)
                        _save_instance_result(r, instances_dir / iid)
                    pbar.update(1)
        finally:
            pbar.close()
            for ex in executors:
                try:
                    ex.disconnect()
                except Exception:
                    pass

    return results


# ============================================================================
# Reporting
# ============================================================================

def generate_reports(
    results: List[InstanceEvalResult],
    output_dir: Path,
    benchmark_size: int,
    num_executions: int,
    majority_threshold: int,
    timeout: int,
):
    """Generate eval_details.jsonl, eval_summary.json, and helper text files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- eval_details.jsonl ----
    details = [asdict(r) for r in sorted(results, key=lambda x: x.instance_id)]
    write_jsonl(details, output_dir / "eval_details.jsonl")

    # ---- Categorize ----
    reliable_match = [r for r in results if r.status == "match"]
    reliable_mismatch = [r for r in results if r.status == "mismatch"]
    unreliable_match = [r for r in results if r.status == "gold_unreliable_match"]
    unreliable_mismatch = [r for r in results if r.status == "gold_unreliable_mismatch"]
    gold_failed = [r for r in results if r.status == "gold_execution_failed"]
    gold_insufficient = [r for r in results if r.status == "gold_insufficient"]
    pred_failed = [r for r in results if r.status == "pred_execution_failed"]
    errors = [r for r in results if r.status == "error"]

    reliable_results = reliable_match + reliable_mismatch
    unreliable_results = unreliable_match + unreliable_mismatch

    reliable_correct = len(reliable_match)
    reliable_count = len(reliable_results)
    unreliable_correct = len(unreliable_match)
    unreliable_count = len(unreliable_results)

    total_correct = reliable_correct + unreliable_correct
    total_evaluated = len(results)
    total_scoreable = reliable_count + unreliable_count

    primary_accuracy = reliable_correct / reliable_count if reliable_count > 0 else 0.0
    full_accuracy = total_correct / total_scoreable if total_scoreable > 0 else 0.0

    # ---- eval_summary.json ----
    summary = {
        "timestamp": datetime.now().isoformat(),
        "primary_accuracy": round(primary_accuracy, 4),
        "primary_accuracy_pct": f"{primary_accuracy * 100:.1f}%",
        "primary_correct": reliable_correct,
        "primary_total": reliable_count,
        "full_accuracy": round(full_accuracy, 4),
        "full_accuracy_pct": f"{full_accuracy * 100:.1f}%",
        "full_correct": total_correct,
        "full_total": total_scoreable,
        "total_benchmark": benchmark_size,
        "total_evaluated": total_evaluated,
        "missing_predictions": benchmark_size - total_evaluated,
        "breakdown": {
            "match": len(reliable_match),
            "mismatch": len(reliable_mismatch),
            "gold_unreliable_match": len(unreliable_match),
            "gold_unreliable_mismatch": len(unreliable_mismatch),
            "gold_execution_failed": len(gold_failed),
            "gold_insufficient": len(gold_insufficient),
            "pred_execution_failed": len(pred_failed),
            "error": len(errors),
        },
        "unreliable_instances": sorted([r.instance_id for r in unreliable_results]),
        "gold_failed_instances": sorted([r.instance_id for r in gold_failed + gold_insufficient]),
        "pred_failed_instances": sorted([r.instance_id for r in pred_failed]),
        "error_instances": sorted([r.instance_id for r in errors]),
        "execution_config": {
            "num_executions": num_executions,
            "majority_threshold": majority_threshold,
            "timeout": timeout,
        },
    }

    with open(output_dir / "eval_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ---- Helper text files ----
    _write_id_list(output_dir / "gold_unreliable.txt", [r.instance_id for r in unreliable_results])
    _write_id_list(output_dir / "gold_failed.txt", [r.instance_id for r in gold_failed + gold_insufficient])
    _write_id_list(output_dir / "pred_failed.txt", [r.instance_id for r in pred_failed])
    _write_id_list(output_dir / "correct.txt", [r.instance_id for r in reliable_match + unreliable_match])

    # ---- Print summary to console ----
    print()
    print("=" * 64)
    print("EVALUATION RESULTS")
    print("=" * 64)
    print()
    print(f"  Primary Accuracy (reliable gold only): {reliable_correct}/{reliable_count} = {primary_accuracy * 100:.1f}%")
    print(f"  Full Accuracy (all scoreable):          {total_correct}/{total_scoreable} = {full_accuracy * 100:.1f}%")
    print()
    print(f"  Breakdown:")
    print(f"    Match (reliable):           {len(reliable_match)}")
    print(f"    Mismatch (reliable):         {len(reliable_mismatch)}")
    print(f"    Match (gold unreliable):     {len(unreliable_match)}")
    print(f"    Mismatch (gold unreliable):  {len(unreliable_mismatch)}")
    print(f"    Gold execution failed:       {len(gold_failed)}")
    print(f"    Gold insufficient:           {len(gold_insufficient)}")
    print(f"    Pred execution failed:       {len(pred_failed)}")
    print(f"    Error:                       {len(errors)}")
    print()

    if unreliable_results:
        print(f"  Gold unreliable instances ({len(unreliable_results)}):")
        for r in sorted(unreliable_results, key=lambda x: x.instance_id)[:20]:
            print(f"    {r.instance_id}  majority={r.gold_majority_size}  score={r.score}")
        if len(unreliable_results) > 20:
            print(f"    ... and {len(unreliable_results) - 20} more (see gold_unreliable.txt)")
        print()

    if gold_failed or gold_insufficient:
        print(f"  Gold failed/insufficient instances ({len(gold_failed) + len(gold_insufficient)}):")
        for r in sorted(gold_failed + gold_insufficient, key=lambda x: x.instance_id)[:10]:
            print(f"    {r.instance_id}  status={r.status}")
        if len(gold_failed) + len(gold_insufficient) > 10:
            print(f"    ... and {len(gold_failed) + len(gold_insufficient) - 10} more (see gold_failed.txt)")
        print()

    total_gold_time = sum(r.gold_total_time for r in results)
    total_pred_time = sum(r.pred_total_time for r in results)
    print(f"  Total execution time:")
    print(f"    Gold SQL: {total_gold_time:.0f}s ({total_gold_time / 60:.1f} min)")
    print(f"    Pred SQL: {total_pred_time:.0f}s ({total_pred_time / 60:.1f} min)")
    print()
    print(f"  Results saved to: {output_dir}")
    print("=" * 64)


def _write_id_list(path: Path, ids: List[str]):
    """Write a sorted list of instance IDs to a text file."""
    with open(path, "w") as f:
        for iid in sorted(ids):
            f.write(iid + "\n")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate AI SQL baseline with N-execution majority voting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Gold is held out of the public release; point --gold-dir at your own gold SQL.
  python evaluation/evaluate.py \\
      --pred-dir predictions/my_model \\
      --gold-dir gold \\
      --output-dir evaluation/results/my_model -n 10

  python evaluation/evaluate.py \\
      --pred-dir ... --gold-dir ... --output-dir ... \\
      --instances sf_bq003 sf_bq004 -n 5 --resume
        """,
    )
    parser.add_argument(
        "--pred-dir", "-p", type=str, required=True,
        help="Directory with predicted SQL: {pred-dir}/{id}/final.sql",
    )
    parser.add_argument(
        "--output-dir", "-o", type=str, required=True,
        help="Output directory for evaluation results",
    )
    parser.add_argument(
        "--tasks", "-t", type=str, default=None,
        help="Tasks JSONL (default: data/spider2-aifunc.jsonl)",
    )
    parser.add_argument(
        "--gold-dir", "-g", type=str, default=None,
        help="Directory of gold SQL: {gold-dir}/{id}.sql (default: gold/). "
             "Gold is held out of the public release; supply your own to run.",
    )
    parser.add_argument(
        "--num-executions", "-n", type=int, default=1,
        help="Number of times to execute each SQL (default: 1)",
    )
    parser.add_argument(
        "--majority-threshold", type=int, default=None,
        help="Minimum majority size for gold to be 'reliable' (default: N//2+1)",
    )
    parser.add_argument(
        "--match-mode", choices=["majority", "any"], default="majority",
        help="How to score across the N runs: 'majority' compares the majority result on "
             "each side (default); 'any' accepts if any pred run matches any gold run.",
    )
    parser.add_argument(
        "--timeout", type=int, default=240,
        help="SQL execution timeout in seconds (default: 240)",
    )
    parser.add_argument(
        "--instances", nargs="+", default=None,
        help="Specific instance IDs to evaluate (default: all)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip instances that already have eval_result.json in output-dir",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=1,
        help="Number of parallel workers, each with its own Snowflake connection (default: 1)",
    )

    args = parser.parse_args()

    # Load env
    load_dotenv(PROJECT_ROOT / ".env")

    # Resolve paths
    pred_dir = Path(args.pred_dir)
    if not pred_dir.is_absolute():
        pred_dir = PROJECT_ROOT / pred_dir

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    tasks_path = Path(args.tasks) if args.tasks else PROJECT_ROOT / "data" / "spider2-aifunc.jsonl"
    if not tasks_path.is_absolute():
        tasks_path = PROJECT_ROOT / tasks_path

    gold_dir = Path(args.gold_dir) if args.gold_dir else PROJECT_ROOT / "gold"
    if not gold_dir.is_absolute():
        gold_dir = PROJECT_ROOT / gold_dir

    majority_threshold = args.majority_threshold
    if majority_threshold is None:
        majority_threshold = args.num_executions // 2 + 1

    # Validate
    if not pred_dir.exists():
        print(f"Error: Prediction directory does not exist: {pred_dir}")
        sys.exit(1)
    if not tasks_path.exists():
        print(f"Error: Tasks file does not exist: {tasks_path}")
        sys.exit(1)
    if not gold_dir.exists():
        print(f"Error: Gold directory does not exist: {gold_dir}")
        print("Gold is held out of the public release. "
              "Point --gold-dir at your own gold SQL ({id}.sql) to run.")
        sys.exit(1)

    print("=" * 64)
    if args.match_mode == "any":
        mode_label = f"{args.num_executions}-Execution Any-Match"
    elif args.num_executions == 1:
        mode_label = "Single-Execution"
    else:
        mode_label = f"{args.num_executions}-Execution Majority Voting"
    print(f"AI SQL Baseline Evaluation ({mode_label})")
    print("=" * 64)
    print(f"  Pred dir:      {pred_dir}")
    print(f"  Output dir:    {output_dir}")
    print(f"  Tasks:         {tasks_path}")
    print(f"  Gold dir:      {gold_dir}")
    print(f"  N executions:  {args.num_executions}")
    print(f"  Majority threshold: {majority_threshold}")
    print(f"  Timeout:       {args.timeout}s")
    print(f"  Workers:       {args.workers}")
    if args.instances:
        print(f"  Instances:     {args.instances}")
    print(f"  Resume:        {args.resume}")
    print()

    # Load data
    print("Loading benchmark data...", flush=True)
    benchmark = load_benchmark(tasks_path, gold_dir, args.instances)
    print(f"  Loaded {len(benchmark)} benchmark instances", flush=True)

    print("Loading predictions...", flush=True)
    predictions = load_predictions(pred_dir, args.instances)
    print(f"  Loaded {len(predictions)} predictions", flush=True)
    print()

    # Run
    results = run_evaluation(
        benchmark=benchmark,
        predictions=predictions,
        output_dir=output_dir,
        num_executions=args.num_executions,
        majority_threshold=majority_threshold,
        timeout=args.timeout,
        resume=args.resume,
        workers=args.workers,
        match_mode=args.match_mode,
    )

    # Report
    if results:
        generate_reports(
            results=results,
            output_dir=output_dir,
            benchmark_size=len(benchmark),
            num_executions=args.num_executions,
            majority_threshold=majority_threshold,
            timeout=args.timeout,
        )


if __name__ == "__main__":
    main()
