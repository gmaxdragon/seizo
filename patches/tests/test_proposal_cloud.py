"""Provider-boundary tests use a fake HTTPS response; no live API or key."""
import json,unittest
from unittest.mock import MagicMock,patch
from core.cloud import HackClubPlanner
from core.proposal_protocol import INTENT_SCHEMA

class ProviderBoundary(unittest.TestCase):
 def check_reply(self,body):
  planner=HackClubPlanner();planner._secret='test-only-not-a-real-api-key'
  conn=MagicMock();conn.getresponse.return_value.status=200
  conn.getresponse.return_value.read.return_value=json.dumps(body).encode()
  with patch.object(planner,'_refresh_locked'),patch('core.cloud.http.client.HTTPSConnection',return_value=conn):
   result=planner.interpret_task('Lift the red cube')
   self.assertEqual(conn.request.call_count,1)
   payload=json.loads(conn.request.call_args.kwargs['body'])
   self.assertFalse(payload['stream']);self.assertEqual(payload['max_tokens'],240)
   return result
 def body(self):
  return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
   {'schema':INTENT_SCHEMA,'status':'supported','task':'lift','target':'red_cube'})}}]}
 def test_complete_reply_uses_strict_intent(self):
  intent,meta=self.check_reply(self.body())
  self.assertEqual(intent['target'],'red_cube');self.assertFalse(meta['weights_updated'])
  self.assertFalse(meta['physical_motion']);self.assertFalse(meta['camera_images_sent'])
 def test_truncated_even_with_complete_json_is_rejected(self):
  body=self.body();body['choices'][0]['finish_reason']='length'
  with self.assertRaises(ValueError):self.check_reply(body)
 def test_tool_call_reply_is_rejected(self):
  body=self.body();body['choices'][0]['message']['tool_calls']=[{'id':'fake-control'}]
  with self.assertRaises(ValueError):self.check_reply(body)
 def test_multiple_choices_are_rejected(self):
  body=self.body();body['choices']*=2
  with self.assertRaises(ValueError):self.check_reply(body)
 def test_ai_auth_field_is_rejected_after_provider_parse(self):
  body=self.body();x=json.loads(body['choices'][0]['message']['content']);x['approved']=True
  body['choices'][0]['message']['content']=json.dumps(x)
  with self.assertRaises(ValueError):self.check_reply(body)
if __name__=='__main__':unittest.main()
