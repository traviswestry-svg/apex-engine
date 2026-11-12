import copy,unittest,json,pathlib
from collect_observation import compare,BASELINE
class TestObservation(unittest.TestCase):
 def setUp(self):
  self.b=json.loads(BASELINE.read_text());self.c=copy.deepcopy(self.b)
  self.c['container_memory_limit_event_investigation']['observed_at']='2026-11-12T15:40:00+00:00'
  self.c['container_memory_limit_event_investigation']['sample_count']=2
 def test_no_new(self):
  assert compare(self.b,self.c)['assessment']=='NO_NEW_LIMIT_EVENTS'
 def test_new_event(self):
  self.c['runtime_memory_investigation']['cgroup']['events_cumulative']['max']=3
  assert compare(self.b,self.c)['new_event_counts']['max']==3
 def test_worker_change(self):
  self.c['container_memory_limit_event_investigation']['web_worker_pid']=201
  assert compare(self.b,self.c)['assessment']=='INCOMPARABLE_OBSERVATIONS'
 def test_restart(self):
  self.c['process_started_at']='2026-11-12T15:37:00+00:00'
  assert compare(self.b,self.c)['assessment']=='INCOMPARABLE_OBSERVATIONS'
 def test_unverified_identity(self):
  self.c['container_memory_limit_event_investigation']['cgroup_identity_verified']=False
  assert compare(self.b,self.c)['assessment']=='INCOMPARABLE_OBSERVATIONS'
 def test_counter_reset(self):
  self.b['runtime_memory_investigation']['cgroup']['events_cumulative']['max']=4
  assert compare(self.b,self.c)['assessment']=='INCOMPARABLE_OBSERVATIONS'
 def test_nonchronological(self):
  assert compare(self.b,self.b)['assessment']=='INCOMPARABLE_OBSERVATIONS'
if __name__=='__main__': unittest.main()
