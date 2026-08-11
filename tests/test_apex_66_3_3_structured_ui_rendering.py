import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_display_normalizer_never_implicitly_stringifies_objects():
    js_path = ROOT / 'static/js/apex_display.js'
    script = f"""
const fs = require('fs');
global.window = {{}};
eval(fs.readFileSync({json.dumps(str(js_path))}, 'utf8'));
const d = window.APEXDisplay;
const cases = [
  [{{direction:'BEARISH', confidence:27}}, 'BEARISH'],
  [{{regime:'BALANCE', confidence:0.4}}, 'BALANCE'],
  [{{current_thesis:'Stand aside until acceptance confirms.'}}, 'Stand aside until acceptance confirms.'],
  [{{note:{{text:'Gamma wall rejected'}}}}, 'Gamma wall rejected'],
  [{{source:'market_structure', note:{{text:'Failed break reclaimed'}}}}, 'Failed break reclaimed'],
  [[{{reason:'Flow mixed'}}, {{reason:'Gamma neutral'}}], 'Flow mixed · Gamma neutral'],
  [{{foo:{{bar:1}}}}, '—']
];
for (const [value, expected] of cases) {{
  const actual = d.toText(value, '—');
  if (actual !== expected) throw new Error(JSON.stringify({{value, expected, actual}}));
  if (actual.includes('[object Object]')) throw new Error('object leak: ' + actual);
}}
const ev = d.evidence({{source:'auction_state', note:{{text:'Value accepted above POC'}}}}, '');
if (ev !== 'auction state: Value accepted above POC') throw new Error(ev);
if (d.escapeHtml({{direction:'BULLISH'}}, '').includes('[object Object]')) throw new Error('escape leak');
"""
    subprocess.run(['node', '-e', script], check=True, cwd=ROOT)


def test_command_center_loads_safe_display_before_page_renderer():
    text = (ROOT / 'templates/institutional_command_center.html').read_text(encoding='utf-8')
    assert text.index('js/apex_display.js') < text.index('js/apex42_command_center.js')
    js = (ROOT / 'static/js/apex42_command_center.js').read_text(encoding='utf-8')
    assert 'window.APEXDisplay' in js
    assert 'JSON.stringify(x)' not in js
    assert "textContent=v??f" not in js


def test_institutional_os_loads_safe_display_before_renderer_and_uses_it_for_dcc():
    text = (ROOT / 'templates/apex_os.html').read_text(encoding='utf-8')
    assert text.index("filename='js/apex_display.js'") < text.index("filename='js/apex_os.js'")
    js = (ROOT / 'static/js/apex_os.js').read_text(encoding='utf-8')
    assert 'const displayText' in js
    assert 'const displayToken' in js
    assert "const instBias     = displayToken" in js
    assert "const decision     = displayToken" in js
    assert "const label = evidenceText(ev" in js


def test_dashboard_rendering_sources_do_not_contain_literal_object_object_output():
    # The only acceptable handling is via the safe-display boundary; dashboard
    # sources must never intentionally render JavaScript's default object string.
    for rel in ['static/js/apex_display.js', 'static/js/apex42_command_center.js', 'static/js/apex_os.js']:
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert '[object Object]' not in text
