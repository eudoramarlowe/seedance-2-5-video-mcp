"""FastMCP tools for the asynchronous Seedance 2.5 video contract."""
import base64,json,os,re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
try:
 from mcp.server.fastmcp import FastMCP
except ImportError as exc:
 raise SystemExit("Install the official MCP Python SDK: python -m pip install mcp") from exc
mcp=FastMCP("seedance-2-5-video")
BASE=os.getenv("VIDEO_API_BASE_URL","https://argolink.io/v1").rstrip("/")
_ID=re.compile(r"^[A-Za-z0-9_-]+$")
def call(path,method="GET",body=None,binary=False):
 key=os.environ.get("VIDEO_API_KEY")
 if not key: raise RuntimeError("Set VIDEO_API_KEY in the MCP host environment")
 headers={"Authorization":f"Bearer {key}","User-Agent":"seedance-2-5-video-mcp/1.0"}
 data=None
 if body is not None: headers["Content-Type"]="application/json"; data=json.dumps(body).encode()
 req=Request(BASE+path,method=method,headers=headers,data=data)
 try:
  with urlopen(req,timeout=90) as r:
   raw=r.read(); return raw if binary else json.loads(raw)
 except HTTPError as e:
  raise RuntimeError(f"HTTP {e.code}: {e.read(500).decode(errors='replace')}") from e
def check_id(job_id):
 if not isinstance(job_id,str) or not _ID.fullmatch(job_id): raise ValueError("invalid request_id")
@mcp.tool()
def submit_video(prompt:str,duration:int=5,resolution:str="720p",aspect_ratio:str="16:9",generate_audio:bool=True,model:str="seedance-2.5")->dict:
 if model!="seedance-2.5": raise ValueError("This server is limited to seedance-2.5")
 if not 4<=duration<=30: raise ValueError("duration must be 4..30 seconds")
 if resolution not in {"480p","720p","1080p"}: raise ValueError("resolution must be 480p, 720p, or 1080p")
 return call("/videos/generations","POST",{"model":model,"prompt":prompt,"duration":duration,"resolution":resolution,"aspect_ratio":aspect_ratio,"generate_audio":generate_audio})
@mcp.tool()
def get_video_status(request_id:str)->dict:
 check_id(request_id); return call("/videos/"+request_id)
@mcp.tool()
def get_video_media(request_id:str,output_path:str="")->dict:
 check_id(request_id); status=get_video_status(request_id)
 if status.get("status")!="done": raise RuntimeError(f"job is {status.get('status')}; download only after done")
 raw=call("/videos/"+request_id+"/content",binary=True)
 if output_path:
  path=Path(output_path).expanduser(); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
  return {"request_id":request_id,"path":str(path),"bytes":len(raw)}
 return {"request_id":request_id,"mp4_base64":base64.b64encode(raw).decode(),"bytes":len(raw)}
if __name__=="__main__": mcp.run(transport="stdio")
