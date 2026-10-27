"""Read-only snapshot and narrative consistency diagnostics; no forecast authority."""
from __future__ import annotations
import hashlib
import json
import re

VERSION = '69.10.48-snapshot-integrity-v1'
FIELDS = {'developing_poc': ('developing poc', 'developing point-of-control'),
          'vah': ('value area high', 'vah'), 'call_wall': ('call wall',)}

def snapshot_identity(structured, target_date, mode):
    """Stable identity of the exact structured inputs used to build the prompt."""
    payload = {'target_session_date': target_date, 'brief_mode': mode, 'structured': structured}
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()

def _levels(structured):
    values = {}
    for item in structured.get('levels', []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or item.get('label') or item.get('key') or '').lower()
        price = item.get('price', item.get('value'))
        for field, aliases in FIELDS.items():
            if any(alias in name for alias in aliases):
                try:
                    values[field] = float(price)
                except (ValueError, TypeError):
                    pass
    return values

def narrative_consistency(narrative, structured):
    """Detect explicit numerical disagreements; no claim of full semantic verification."""
    levels = _levels(structured)
    mismatches = []
    checked = []
    for field, aliases in FIELDS.items():
        expected = levels.get(field)
        if expected is None:
            continue
        for alias in aliases:
            pattern = r'(?i)\b' + re.escape(alias) + r'\b[^\n\d]{0,35}(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d{4,5}(?:\.\d+)?)'
            match = re.search(pattern, narrative or '')
            if match:
                stated = float(match.group(1).replace(',', ''))
                checked.append(field)
                if abs(stated - expected) > .011:
                    mismatches.append({'field': field, 'narrative': stated, 'structured': expected})
                break
    return {'version': VERSION, 'status': 'MISMATCH' if mismatches else ('PARTIALLY_CHECKED' if checked else 'NOT_VERIFIABLE'),
            'checked_fields': checked, 'mismatches': mismatches,
            'note': 'Explicit numeric checks only; unmentioned or paraphrased levels cannot be certified.'}

def quality_dimensions(*, narrative_status, snapshot_check, calendar_supplied=False):
    return {'market_data_completeness': 'SEE_EXISTING_DATA_QUALITY_SCORE',
            'calendar_coverage': 'PROVIDED' if calendar_supplied else 'NOT_VERIFIED',
            'snapshot_consistency': snapshot_check.get('status', 'NOT_VERIFIABLE'),
            'forecast_confidence': 'NOT_HISTORICALLY_CALIBRATED',
            'narrative_status': narrative_status}
