#!/usr/bin/env python3
"""Quick smoke test: verify Snowflake connectivity and AI SQL function access."""

import json
import sys
import snowflake.connector

CREDENTIAL_PATH = "credentials/snowflake_credential.json"

TESTS = [
    ("Basic connectivity", "SELECT 1 AS ok"),
    (
        "AI_CLASSIFY",
        "SELECT AI_CLASSIFY('I need help resetting my password', "
        "['technical_issue', 'billing', 'account_access']) AS result",
    ),
    (
        "AI_FILTER",
        "SELECT AI_FILTER('The sky is blue') AS result",
    ),
    (
        "AI_SENTIMENT",
        "SELECT AI_SENTIMENT('Snowflake is amazing!') AS result",
    ),
]


def main():
    try:
        with open(CREDENTIAL_PATH) as f:
            creds = json.load(f)
    except FileNotFoundError:
        print(f"FAIL: Credential file not found at {CREDENTIAL_PATH}")
        print(f"  Copy the example and fill in your credentials:")
        print(f"  cp credentials/snowflake_credential.example.json {CREDENTIAL_PATH}")
        sys.exit(1)

    print("Connecting to Snowflake...")
    try:
        conn = snowflake.connector.connect(**creds, login_timeout=30, network_timeout=60)
    except Exception as e:
        print(f"FAIL: Could not connect to Snowflake: {e}")
        sys.exit(1)
    print("Connected.\n")

    passed, failed = 0, 0
    for name, sql in TESTS:
        try:
            cur = conn.cursor()
            cur.execute(sql)
            row = cur.fetchone()
            print(f"  PASS  {name}")
            print(f"        -> {row[0]}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}")
            print(f"        -> {e}")
            failed += 1

    conn.close()
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
