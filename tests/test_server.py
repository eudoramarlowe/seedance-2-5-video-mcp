import ast,pathlib,unittest
class T(unittest.TestCase):
 def test_contract(self):
  s=pathlib.Path("server.py").read_text(); ast.parse(s)
  for x in ("User-Agent","submit_video","get_video_status","get_video_media"): self.assertIn(x,s)
if __name__=="__main__": unittest.main()
