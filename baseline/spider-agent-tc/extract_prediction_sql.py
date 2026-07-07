"""
Extract each instance's predicted SQL from the agent's raw run transcripts.

The agent writes one JSON transcript per instance to results/<run>/{id}.json; the
final answer is the SQL it terminated with. This pulls that SQL out and writes one
{id}.sql per instance, which is what evaluation/evaluate.py reads as --pred-dir.

Usage:
    python extract_prediction_sql.py <results/run_dir> <parsed_sql/out_dir>
"""
import json
import re
import argparse
import random
from pathlib import Path


def _extract_xml_terminate_sql(content):
    """Extract SQL from GLM-5 style XML terminate in content. Handles variants:
      - <parameter="answer">SQL</parameter>
      - <answer>SQL</parameter>  (mismatched closing tag)
      - <answer>SQL</answer>
    """
    if not content or 'terminate' not in content:
        return None
    # Try <parameter="answer"> or <parameter name="answer"> style
    match = re.search(r'<parameter[^>]*answer[^>]*>(.*?)</parameter>', content, re.DOTALL)
    if match:
        sql = match.group(1).strip()
        return sql if sql else None
    # Try <answer>SQL</parameter> or <answer>SQL</answer> or <answer>SQL</function>
    match = re.search(r'<answer>(.*?)(?:</parameter>|</answer>|</function>)', content, re.DOTALL)
    if match:
        sql = match.group(1).strip()
        return sql if sql else None
    return None


def _extract_xml_execute_sql(content):
    """Extract SQL from GLM-5 style XML in content: <tool_call>execute_snowflake_sql><parameter="sql">SQL</parameter>"""
    if not content or 'execute_snowflake_sql' not in content:
        return None
    match = re.search(r'<tool_call>execute_snowflake_sql[^>]*>.*?<parameter[^>]*sql[^>]*>(.*?)</parameter>', content, re.DOTALL)
    if match:
        sql = match.group(1).strip()
        return sql if sql else None
    return None


def _fallback_extract_sql(data):
    """
    Fallback when primary terminate extraction fails.
    1. Scan all conversations for XML-style terminate in content (e.g. GLM-5 format).
    2. Fall back to the last execute_snowflake_sql query found (structured or XML in content).
    Returns (sql, method) or (None, None).
    """
    xml_sql = None
    last_execute_sql = None

    for record in data:
        # Scan both conversation and final_messages (GLM-5 stores raw XML in final_messages)
        for msg_list_key in ('conversation', 'final_messages'):
            for item in record.get(msg_list_key, []):
                if item.get('role') != 'assistant':
                    continue
                content = item.get('content') or ''
                # Check content for XML-style terminate
                sql = _extract_xml_terminate_sql(content)
                if sql:
                    xml_sql = sql  # keep updating to get the last occurrence
                # Track last execute_snowflake_sql, structured tool_calls
                for tc in (item.get('tool_calls') or []):
                    if tc.get('name') == 'execute_snowflake_sql':
                        args = tc.get('arguments', {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                continue
                        query = args.get('sql') or args.get('query') or ''
                        if query:
                            last_execute_sql = query
                # Track last execute_snowflake_sql, XML in content (GLM-5 style)
                sql = _extract_xml_execute_sql(content)
                if sql:
                    last_execute_sql = sql

    if xml_sql:
        return xml_sql, 'xml_terminate'
    if last_execute_sql:
        return last_execute_sql, 'last_execute_sql'
    return None, None


def extract_sql_answers(input_dir, output_folder):
    """
    Extract SQL answers from terminated records in JSON files.
    Falls back to XML-terminate or last execute_snowflake_sql if primary extraction fails.
    """
    input_path = Path(input_dir)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = list(input_path.glob("*.json"))

    processed_count = 0
    skipped_count = 0
    fallback_count = 0

    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                skipped_count += 1
                continue

            # --- Primary extraction ---
            answer = None
            instance_id = None
            method = 'terminate'

            terminated_records = [r for r in data if r.get('terminated', False)]
            if terminated_records:
                selected_record = random.choice(terminated_records)
                instance_id = selected_record.get('instance_id') or selected_record.get('id')
                conversation = selected_record.get('conversation') or []
                if conversation:
                    last_item = conversation[-1]
                    tool_calls = last_item.get('tool_calls') or []
                    if tool_calls and tool_calls[0].get('name') == 'terminate':
                        arguments = tool_calls[0].get('arguments', {})
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        answer = arguments.get('answer') or None

            # --- Fallback extraction ---
            if not answer:
                # Try to get instance_id from any record if not yet found
                if not instance_id:
                    for record in data:
                        instance_id = record.get('instance_id') or record.get('id')
                        if instance_id:
                            break
                if not instance_id:
                    instance_id = json_file.stem  # use filename as last resort
                answer, method = _fallback_extract_sql(data)
                if answer:
                    fallback_count += 1

            if not instance_id or not answer:
                skipped_count += 1
                continue

            # Save to SQL file
            sql_file = output_path / f"{instance_id}.sql"
            with open(sql_file, 'w', encoding='utf-8') as f:
                f.write(answer)

            processed_count += 1
            print(f"Extracted SQL ({method}) from {json_file.name} -> {instance_id}.sql")

        except Exception as e:
            print(f"Error processing {json_file.name}: {e}")
            skipped_count += 1

    print(f"\nProcessed: {processed_count} files  (fallback used: {fallback_count})")
    print(f"Skipped:   {skipped_count} files")

def main():
    parser = argparse.ArgumentParser(description='Extract SQL answers from terminated JSON records')
    parser.add_argument('input_dir', help='Input JSON directory path')
    parser.add_argument('output_folder', help='Output folder for SQL files')
    
    args = parser.parse_args()
    
    input_path = Path(args.input_dir)
    if not input_path.exists() or not input_path.is_dir():
        print(f"Error: Invalid input directory: {args.input_dir}")
        return 1
    
    try:
        extract_sql_answers(args.input_dir, args.output_folder)
        return 0
    except Exception as e:
        print(f"Processing error: {e}")
        return 1

if __name__ == '__main__':
    exit(main())