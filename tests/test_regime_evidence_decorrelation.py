import unittest
from engine.regime_evidence_decorrelation import classify_families, directional_signal, evaluate

class DeCorrelationTests(unittest.TestCase):
    def test_correlated_range_votes_collapse(self):
        vote={'evidence_rows':[{'condition':'Below PDH (10)','regime_hint':'balance'},
                              {'condition':'Above PDL (5)','regime_hint':'balance'},
                              {'condition':'Inside value','regime_hint':'mean_reversion'},
                              {'condition':'Dealer gamma regime: MIXED','regime_hint':'balance'},
                              {'condition':'Inside expected move','regime_hint':'balance'}]}
        r=classify_families(vote)
        self.assertEqual(r['vote_counts']['Balanced Auction'],3)
        self.assertEqual(r['independent_family_count'],4)
    def test_missing_evidence_abstains(self):
        self.assertIsNone(classify_families(None)['selected'])
    def test_family_tie_abstains(self):
        r=classify_families({'evidence_rows':[{'condition':'Inside value','regime_hint':'mean_reversion'},
                  {'condition':'Dealer gamma regime: MIXED','regime_hint':'balance'}]})
        self.assertEqual(r['status'],'ABSTAIN_FAMILY_TIE')
    def test_directional_rows_must_be_verified_at_morning(self):
        self.assertIsNone(directional_signal({'evidence_rows':[{'direction':'BULLISH'}]})['direction'])
        self.assertEqual(directional_signal({'evidence_rows':[{'direction':'BULLISH','directional_evidence_verified':True,'as_of_morning':True}]})['direction'],'BULLISH')
    def test_empty_archive_abstains(self):
        r=evaluate([],{},min_train=2)
        self.assertEqual(r['walk_forward']['evaluated_sessions'],0)
        self.assertFalse(r['production_promotion'])
if __name__=='__main__': unittest.main()
