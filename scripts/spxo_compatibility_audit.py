"""Read-only SPXO compatibility audit for supplied contract/chain JSON arrays.
Usage: python -m scripts.spxo_compatibility_audit contracts.json
No DB changes, broker requests, or trading-authority changes.
"""
import argparse
import json
from pathlib import Path
from engine.options.spxo_contract_lifecycle import classify_contract, execution_blockers


def audit(records):
    result = {"schema": "apex.spxo_contract_compatibility.v1", "read_only": True,
              "execution_authority": False, "total": len(records), "by_class": {},
              "conflicts": 0, "blocked": 0, "contract_samples": []}
    for raw in records:
        if not isinstance(raw, dict):
            raw = {}
        info = classify_contract(raw)
        k = info["contract_class"]
        result["by_class"][k] = result["by_class"].get(k, 0) + 1
        result["conflicts"] += int(info["identity_conflict"])
        result["blocked"] += bool(execution_blockers(raw))
        if len(result["contract_samples"]) < 12:
            result["contract_samples"].append({"contract_class": k,
                "settlement_type": info["settlement_type"],
                "last_trading_timestamp": info["last_trading_timestamp"],
                "execution_blockers": execution_blockers(raw)})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    records = json.loads(args.json_file.read_text())
    if not isinstance(records, list):
        raise SystemExit("Input must be a JSON array of contract dictionaries")
    print(json.dumps(audit(records), indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
