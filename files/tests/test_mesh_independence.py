"""Independent-evidence damping in the intelligence-mesh consensus calc.

A flow source that is really one continuing burst reports
independent_evidence_factor < 1.0. The mesh must scale that node's contribution
by it so a single burst cannot multiply conviction in its own direction.
"""
from engine.institutional_intelligence_mesh import build_intelligence_mesh


def _snap(ief):
    return {
        "gamma": {"direction": "CALL", "confidence": 70},
        "auction": {"direction": "CALL", "confidence": 65},
        "order_flow": {"direction": "CALL", "confidence": 85, "independent_evidence_factor": ief},
    }


def _of(mesh):
    return next(n for n in mesh["nodes"] if n["engine"] == "order_flow")


def test_node_exposes_independence():
    m = build_intelligence_mesh(_snap(0.25), now=0)
    assert _of(m)["independence"] == 0.25


def test_redundant_burst_contribution_is_discounted():
    redundant = _of(build_intelligence_mesh(_snap(0.25), now=0))
    independent = _of(build_intelligence_mesh(_snap(1.0), now=0))
    # ~0.25x the independent contribution
    assert abs(redundant["contribution"]) < abs(independent["contribution"])
    assert abs(abs(redundant["contribution"]) - 0.25 * abs(independent["contribution"])) < 1e-6


def test_redundant_call_burst_reduces_call_conviction():
    # Conflicted picture where a CALL flow burst is the tie-breaker.
    def snap(ief):
        return {
            "gamma": {"direction": "CALL", "confidence": 70},
            "auction": {"direction": "PUT", "confidence": 68},
            "market_structure": {"direction": "PUT", "confidence": 66},
            "order_flow": {"direction": "CALL", "confidence": 85, "independent_evidence_factor": ief},
        }
    independent = build_intelligence_mesh(snap(1.0), now=0)
    redundant = build_intelligence_mesh(snap(0.25), now=0)
    # Discounting the redundant CALL burst moves net_score away from CALL.
    assert redundant["net_score"] < independent["net_score"]


def test_absent_factor_defaults_to_no_penalty():
    m = build_intelligence_mesh({
        "gamma": {"direction": "CALL", "confidence": 70},
        "order_flow": {"direction": "CALL", "confidence": 80},  # no factor
    }, now=0)
    assert _of(m)["independence"] == 1.0


def test_nested_flow_excitation_factor_is_read():
    m = build_intelligence_mesh({
        "gamma": {"direction": "CALL", "confidence": 70},
        "order_flow": {"direction": "CALL", "confidence": 80,
                       "flow_excitation": {"independent_evidence_factor": 0.3}},
    }, now=0)
    assert _of(m)["independence"] == 0.3
