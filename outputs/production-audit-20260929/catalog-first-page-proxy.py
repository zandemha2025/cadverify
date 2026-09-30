from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs, urlencode
import sys

class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        headers={k:v for k,v in self.headers.items() if k.lower() not in ("host","connection")}
        path=urlsplit(self.path)
        query=parse_qs(path.query)
        if path.path=="/api/v1/catalog":
            query["page_size"]=["1"]
            if query.get("part_key") and "--missing-selection" in sys.argv:
                query["part_key"]=["0"*64]
        target=path.path+("?"+urlencode(query,doseq=True) if query else "")
        req=Request("http://127.0.0.1:8017"+target,headers=headers)
        try: response=urlopen(req,timeout=30)
        except HTTPError as error: response=error
        body=response.read()
        path=urlsplit(self.path)
        print({"path":path.path,"status":response.status,"encoding":response.headers.get("Content-Encoding"),"bytes":len(body)},flush=True)
        self.send_response(response.status)
        for key,value in response.headers.items():
            if key.lower() not in ("content-length","transfer-encoding","connection"):
                self.send_header(key,value)
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        try:self.wfile.write(body)
        except BrokenPipeError:pass

ThreadingHTTPServer(("127.0.0.1",8018),Proxy).serve_forever()
