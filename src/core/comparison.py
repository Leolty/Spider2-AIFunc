"""
Result comparison utilities for AI SQL evaluation.

Adopted from Spider2's evaluation_suite/evaluate_utils.py with minimal changes.
This module provides the comparison logic used by evaluation/evaluate.py, including
the N-execution consistency check used to judge whether AI SQL results are stable.

Key concepts:
- ignore_order: If True, row order doesn't matter
- condition_cols: List of 0-based column indices to compare (empty = all columns)
- Float tolerance: 1.01e-2 for numeric comparisons
- Column matching: Gold columns must be found in pred (allows column reordering)
"""
import math
import datetime
from decimal import Decimal
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass


# =============================================================================
# Core Comparison Logic (from Spider2)
# =============================================================================

# Tolerance for numeric comparison. We want to tolerate differences of up to
# 0.01 (one unit in the second decimal place), but IEEE 754 float arithmetic
# can produce residuals slightly above 0.01 (e.g. abs(4.14-4.15) ≈ 0.01000000000000068).
# Adding a small epsilon avoids those false negatives.
FLOAT_TOLERANCE = 1.01e-2


def normalize_value(value):
    """Normalize value for comparison (handle NaN)."""
    if pd.isna(value):
        return 0
    return value


def _try_as_number(val):
    """Try to interpret val as a float for numeric comparison. Returns float or None."""
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float, Decimal)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            return float(s)
        except (ValueError, OverflowError):
            return None
    return None


def _try_as_datetime(val):
    """Try to interpret val as a datetime for date comparison. Returns datetime or None."""
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime().replace(tzinfo=None)
    if isinstance(val, datetime.datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
        return datetime.datetime(val.year, val.month, val.day)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y/%m/%d",
            "%m/%d/%Y",
        ):
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None
    return None


def _try_as_bool(val):
    """Try to interpret val as a boolean. Returns bool or None."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        lower = val.strip().lower()
        if lower in ("true", "yes"):
            return True
        if lower in ("false", "no"):
            return False
    return None


def _values_match(a, b, tolerance=FLOAT_TOLERANCE):
    """
    Compare two values with cross-type coercion for SQL result comparison.

    Handles type mismatches common in SQL execution results:
    - numeric types <-> numeric strings (e.g., 42 vs "42")
    - date/datetime/timestamp <-> date strings (e.g., date(2000,1,1) vs "2000-01-01")
    - booleans <-> bool strings (e.g., True vs "true")
    - booleans <-> integers (e.g., True vs 1)
    """
    try:
        if a == b:
            return True
    except (TypeError, ValueError):
        pass

    try:
        if pd.isna(a) and pd.isna(b):
            return True
    except (TypeError, ValueError):
        pass

    a_num = _try_as_number(a)
    b_num = _try_as_number(b)
    if a_num is not None and b_num is not None:
        if math.isnan(a_num) and math.isnan(b_num):
            return True
        if math.isnan(a_num) or math.isnan(b_num):
            return False
        return math.isclose(a_num, b_num, abs_tol=tolerance)

    a_dt = _try_as_datetime(a)
    b_dt = _try_as_datetime(b)
    if a_dt is not None and b_dt is not None:
        return a_dt == b_dt

    a_bool = _try_as_bool(a)
    b_bool = _try_as_bool(b)
    if a_bool is not None and b_bool is not None:
        return a_bool == b_bool

    return False


def vectors_match(v1: List, v2: List, tolerance: float = FLOAT_TOLERANCE, ignore_order: bool = False) -> bool:
    """
    Compare two vectors (column values) for equality.
    
    Args:
        v1: First vector
        v2: Second vector  
        tolerance: Float comparison tolerance
        ignore_order: If True, sort before comparing
        
    Returns:
        True if vectors match
    """
    v1 = [normalize_value(x) for x in v1]
    v2 = [normalize_value(x) for x in v2]
    
    if ignore_order:
        v1 = sorted(v1, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
        v2 = sorted(v2, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
    
    if len(v1) != len(v2):
        return False
    
    for a, b in zip(v1, v2):
        if not _values_match(a, b, tolerance):
            return False
    
    return True


def compare_pandas_table(
    pred: pd.DataFrame, 
    gold: pd.DataFrame, 
    condition_cols: List[int] = None, 
    ignore_order: bool = False
) -> int:
    """
    Compare predicted DataFrame against gold DataFrame.
    
    This is the core comparison function from Spider2.
    
    Logic:
    - For each column in gold (or condition_cols subset), find a matching column in pred
    - Columns match if all values match (with tolerance for floats)
    - If ignore_order=True, row order doesn't matter
    
    Args:
        pred: Predicted result DataFrame
        gold: Gold result DataFrame
        condition_cols: Column indices to compare (None/[] = all columns)
        ignore_order: Whether to ignore row order
        
    Returns:
        1 if match, 0 if not match
    """
    # Both empty = match; one empty one not = mismatch
    gold_empty = gold is None or gold.empty
    pred_empty = pred is None or pred.empty
    if gold_empty and pred_empty:
        return 1
    if gold_empty or pred_empty:
        return 0

    # Handle condition_cols
    if condition_cols is not None and condition_cols != []:
        if not isinstance(condition_cols, (list, tuple)):
            condition_cols = [condition_cols]
        valid_cols = [c for c in condition_cols if c < len(gold.columns)]
        if not valid_cols:
            return 0
        gold_cols = gold.iloc[:, valid_cols]
    else:
        gold_cols = gold
    pred_cols = pred
    
    # Transpose: each row becomes a column's values
    t_gold_list = gold_cols.transpose().values.tolist()
    t_pred_list = pred_cols.transpose().values.tolist()
    
    # For each gold column, find a matching pred column
    score = 1
    for gold_col in t_gold_list:
        if not any(vectors_match(gold_col, pred_col, ignore_order=ignore_order) 
                   for pred_col in t_pred_list):
            score = 0
            break
    
    return score


def compare_multi_pandas_table(
    pred: pd.DataFrame, 
    multi_gold: List[pd.DataFrame], 
    multi_condition_cols: List = None, 
    multi_ignore_order: bool = False
) -> int:
    """
    Compare pred against multiple possible gold DataFrames.
    
    Returns 1 if pred matches ANY of the gold options.
    
    Args:
        pred: Predicted DataFrame
        multi_gold: List of acceptable gold DataFrames
        multi_condition_cols: Condition cols for each gold (or shared)
        multi_ignore_order: Whether to ignore order
        
    Returns:
        1 if matches any gold, 0 otherwise
    """
    if multi_condition_cols is None or multi_condition_cols == [] or multi_condition_cols == [[]]:
        multi_condition_cols = [[] for _ in range(len(multi_gold))]
    elif len(multi_gold) > 1 and not all(isinstance(sublist, list) for sublist in multi_condition_cols):
        multi_condition_cols = [multi_condition_cols for _ in range(len(multi_gold))]
    
    for i, gold in enumerate(multi_gold):
        if compare_pandas_table(pred, gold, multi_condition_cols[i], multi_ignore_order):
            return 1
    return 0


# =============================================================================
# Consistency Checking (for Determinism Agent)
# =============================================================================

@dataclass
class ConsistencyResult:
    """Result of checking consistency across N executions."""
    is_consistent: bool           # True only if 100% match
    execution_count: int          # Number of successful executions used for comparison
    consistent_count: int = 0     # How many match the majority
    inconsistent_executions: List[int] = None  # Which execution numbers differ (1-indexed)
    failure_count: int = 0        # Number of failed executions (timeout, error, etc.)
    
    def __post_init__(self):
        if self.inconsistent_executions is None:
            self.inconsistent_executions = []


def check_execution_consistency(
    dataframes: List[pd.DataFrame],
    ignore_order: bool = False,
    condition_cols: List[int] = None
) -> ConsistencyResult:
    """
    Check if N execution results are consistent using cluster-based comparison.
    
    Uses the same comparison rules as evaluation:
    - Respects ignore_order
    - Respects condition_cols
    - Uses float tolerance
    
    Finds the largest cluster of matching results (majority) and reports
    which executions differ from the majority.
    
    Args:
        dataframes: List of DataFrames from N executions
        ignore_order: From eval_config
        condition_cols: From eval_config
        
    Returns:
        ConsistencyResult with detailed consistency info
    """
    n = len(dataframes)
    
    if n < 2:
        return ConsistencyResult(
            is_consistent=True, 
            execution_count=n,
            consistent_count=n,
            inconsistent_executions=[]
        )
    
    # Check row counts first - if they differ, group by row count
    row_counts = [len(df) for df in dataframes]
    if len(set(row_counts)) > 1:
        # Find the most common row count
        from collections import Counter
        count_freq = Counter(row_counts)
        most_common_count = count_freq.most_common(1)[0][0]
        
        # Find which executions have different row counts
        inconsistent = [i + 1 for i, count in enumerate(row_counts) if count != most_common_count]
        consistent_count = n - len(inconsistent)
        
        return ConsistencyResult(
            is_consistent=False,
            execution_count=n,
            consistent_count=consistent_count,
            inconsistent_executions=inconsistent
        )
    
    # Build a match matrix: match[i][j] = True if execution i matches execution j
    match_matrix = [[False] * n for _ in range(n)]
    for i in range(n):
        match_matrix[i][i] = True
        for j in range(i + 1, n):
            matches = compare_pandas_table(dataframes[i], dataframes[j], condition_cols, ignore_order=ignore_order)
            match_matrix[i][j] = (matches == 1)
            match_matrix[j][i] = (matches == 1)
    
    # Find clusters using union-find
    parent = list(range(n))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    for i in range(n):
        for j in range(i + 1, n):
            if match_matrix[i][j]:
                union(i, j)
    
    # Group executions by cluster
    from collections import defaultdict
    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i + 1)  # 1-indexed
    
    # Find the largest cluster (majority)
    largest_cluster = max(clusters.values(), key=len)
    majority_size = len(largest_cluster)
    
    # Find executions not in the majority
    majority_set = set(largest_cluster)
    inconsistent = [i for i in range(1, n + 1) if i not in majority_set]
    
    return ConsistencyResult(
        is_consistent=(majority_size == n),
        execution_count=n,
        consistent_count=majority_size,
        inconsistent_executions=inconsistent
    )


# =============================================================================
# Eval Config Helpers
# =============================================================================

@dataclass  
class EvalConfig:
    """Evaluation configuration."""
    ignore_order: bool = True
    condition_cols: List[int] = None
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EvalConfig':
        """Create from dictionary (e.g., from metadata.json)."""
        return cls(
            ignore_order=d.get('ignore_order', True),
            condition_cols=d.get('condition_cols', []) or []
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'ignore_order': self.ignore_order,
            'condition_cols': self.condition_cols or []
        }
    
    def describe(self) -> str:
        """Human-readable description for prompts."""
        parts = []
        if self.ignore_order:
            parts.append("Row order does NOT matter (results can be in any order)")
        else:
            parts.append("Row order MATTERS (results must be in exact order)")
        
        if self.condition_cols:
            parts.append(f"Only columns at indices {self.condition_cols} are compared")
        else:
            parts.append("All columns are compared")
        
        parts.append("Float values are compared with tolerance of 1.01e-2")
        parts.append("Columns can be reordered (matching by content, not position)")
        
        return "\n".join(f"- {p}" for p in parts)


# =============================================================================
# Utility: DataFrame from ExecutionResult
# =============================================================================

def execution_result_to_dataframe(data: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    """
    Convert execution result data to DataFrame.
    
    Args:
        data: List of row dictionaries from SQL execution
        
    Returns:
        DataFrame or None if empty
    """
    if not data:
        return None
    return pd.DataFrame(data)
