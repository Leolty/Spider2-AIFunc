#!/usr/bin/env python
"""
Determinism Check Script

Runs determinism checks on generated AI SQL from a previous run.

Usage:
    python scripts/run_determinism_check.py -i outputs/run_xxx -o outputs/run_xxx_verified
    python scripts/run_determinism_check.py -i outputs/run_xxx -o outputs/run_xxx_verified --num-executions 5
    python scripts/run_determinism_check.py -i outputs/run_xxx -o outputs/run_xxx_verified --instances sf_bq033 sf_bq091
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run determinism checks on generated AI SQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "-i", "--input-dir",
        type=str,
        required=True,
        help="Input directory containing generated outputs"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        required=True,
        help="Output directory for verified results (will be created)"
    )
    parser.add_argument(
        "-n", "--num-executions",
        type=int,
        default=5,
        help="Number of times to execute each SQL for empirical check (default: 5)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=10,
        help="Maximum rounds for verification (default: 10)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="SQL execution timeout in seconds (default: 240)"
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=2,
        help="Max execution failures tolerated per N-run check (default: 2)"
    )
    parser.add_argument(
        "--skip-passed",
        action="store_true",
        help="Skip instances that already passed in the input directory (for chaining rounds)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume interrupted run: skip instances already completed in the output directory"
    )
    parser.add_argument(
        "--instances",
        nargs='+',
        help="Specific instance IDs to check (default: all)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=True,
        help="Verbose output (default: True)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode (no verbose output)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Load environment
    load_dotenv(PROJECT_ROOT / '.env')
    
    # Resolve paths
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = PROJECT_ROOT / input_dir
    
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    
    # Validate
    if not input_dir.exists():
        print(f"❌ Input directory not found: {input_dir}")
        sys.exit(1)
    
    verbose = not args.quiet
    
    print("=" * 60)
    print("🔍 Determinism Check Script")
    print("=" * 60)
    print(f"📊 Configuration:")
    print(f"   Input directory: {input_dir}")
    print(f"   Output directory: {output_dir}")
    print(f"   Executions per SQL: {args.num_executions}")
    print(f"   Max rounds: {args.max_rounds}")
    print(f"   SQL timeout: {args.timeout}s")
    print(f"   Max failures tolerated: {args.max_failures}")
    print(f"   Skip passed: {args.skip_passed}")
    print(f"   Resume: {args.resume}")
    print(f"   Verbose: {verbose}")
    if args.instances:
        print(f"   Instances filter: {args.instances}")
    print()
    
    # Run the pipeline
    from src.pipelines.run_determinism_pipeline import run_pipeline
    run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        num_executions=args.num_executions,
        max_rounds=args.max_rounds,
        instances=args.instances,
        verbose=verbose,
        timeout=args.timeout,
        max_failures=args.max_failures,
        skip_passed=args.skip_passed,
        resume=args.resume
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
