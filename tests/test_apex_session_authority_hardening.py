"""Deterministic, broker-free regression tests for APEX session safety."""
import datetime as dt
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from engine.canonical_market_calendar import classify, rth_open, session_schedule
from engine.execution.trade_risk_guard import (
    RiskLimits, entry_window_policy_snapshot, validate_entry, validate_complex_entry,
)

ET = ZoneInfo('America/New_York')


def when(day, time):
    return dt.datetime.fromisoformat(f'{day}T{time}:00').replace(tzinfo=ET)


class TestSessionAuthorityHardening(unittest.TestCase):
    def test_early_close_boundary(self):
        self.assertTrue(rth_open(when('2026-11-27', '12:59')))
        self.assertFalse(rth_open(when('2026-11-27', '13:00')))
        self.assertFalse(rth_open(when('2026-11-27', '15:28')))
        self.assertEqual(session_schedule(when('2026-11-27', '15:28'))['close_et'], '13:00')
        self.assertEqual(classify(when('2026-11-27','15:28'))['reason'], 'EARLY_CLOSE')

    def test_normal_day_and_holidays(self):
        self.assertTrue(rth_open(when('2026-11-30','10:00')))
        self.assertTrue(rth_open(when('2026-11-30','15:59')))
        self.assertFalse(rth_open(when('2026-11-30','16:00')))
        self.assertFalse(rth_open(when('2026-11-26','10:00')))
        self.assertFalse(rth_open(when('2026-11-28','10:00')))
        self.assertFalse(rth_open(when('2028-11-27','10:00')))
        self.assertFalse(rth_open('not a timestamp'))

    def test_new_entry_forged_market_open_refused(self):
        params = dict(contract={'symbol':'SPX','side':'CALL','bid':2.0,'ask':2.1},
                      quantity=1,entry_premium=2.0,stop_premium=1.0)
        decision = validate_entry(**params, session_state='MARKET_OPEN',
                                  now=when('2026-11-27','13:00'))
        self.assertFalse(decision.allow)
        self.assertIn('Exchange calendar', ' '.join(decision.reasons))
        normal = validate_entry(**params, session_state='MARKET_OPEN',
                                now=when('2026-11-30','10:00'))
        self.assertTrue(normal.allow)
        missing = validate_entry(**params, now=when('2026-11-30','10:00'))
        self.assertFalse(missing.allow)

    def test_entry_policy_snapshot_requires_real_calendar(self):
        x = entry_window_policy_snapshot(now=when('2026-11-27','13:00'),
                                         session_state='MARKET_OPEN')
        self.assertFalse(x['calendar_authorized'])
        self.assertFalse(x['entry_window_authorized'])

    def test_complex_strategy_forged_market_open_refused(self):
        class Intent:
            symbol='SPX'
            quantity=1
            legs=()
        d=validate_complex_entry(intent=Intent(), economics={'max_loss':100},
                                 session_state='MARKET_OPEN',
                                 now=when('2026-11-27','13:00'))
        self.assertFalse(d.allow)
        self.assertIn('Exchange calendar', ' '.join(d.reasons))

    def test_app_session_classifier_uses_actual_early_close(self):
        import ast
        from pathlib import Path
        app = Path(__file__).resolve().parents[1] / 'app.py'
        tree = ast.parse(app.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'session_status')
        env = {'dt':dt, 'now_et':lambda:when('2026-11-27','15:28'),
               'is_market_holiday':lambda n:False}
        exec(compile(ast.Module(body=[node],type_ignores=[]), str(app), 'exec'), env)
        self.assertEqual(env['session_status'](), 'AFTER_HOURS')
        env['now_et'] = lambda:when('2026-11-27','12:59')
        self.assertEqual(env['session_status'](), 'MARKET_OPEN')
        env['now_et'] = lambda:when('2026-11-27','13:00')
        self.assertEqual(env['session_status'](), 'AFTER_HOURS')

    def test_server_state_cannot_be_supplied_by_request(self):
        from pathlib import Path
        p=Path(__file__).resolve().parents[1]/'engine/execution/trade_routes.py'
        s=p.read_text()
        self.assertNotIn('body.get("session_state", "MARKET_OPEN")', s)
        self.assertIn('def _server_spx_session()', s)

    def test_read_only_no_routing_mutation(self):
        from pathlib import Path
        p=Path(__file__).resolve().parents[1]/'engine/execution/trade_routes.py'
        s=p.read_text()
        self.assertIn('APEX_LIVE_ORDER_ROUTING_ENABLED', s)
        self.assertIn('execute_single_leg(', s)
        self.assertIn('execute_complex(', s)

if __name__ == '__main__':
    unittest.main()
