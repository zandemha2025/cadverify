from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs
import time

class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        headers={k:v for k,v in self.headers.items() if k.lower() not in ("host","connection")}
        req=Request("http://127.0.0.1:8017"+self.path,headers=headers)
        try: response=urlopen(req,timeout=30)
        except HTTPError as error: response=error
        body=response.read()
        path=urlsplit(self.path)
        print({"path":path.path,"status":response.status,"encoding":response.headers.get("Content-Encoding"),"bytes":len(body)},flush=True)
        if path.path=="/api/v1/analyses" and parse_qs(path.query).get("verdict")==["issues"]:
            print("Holding Advisory response for four seconds",flush=True)
            time.sleep(4)
        self.send_response(response.status)
        for key,value in response.headers.items():
            if key.lower() not in ("content-length","transfer-encoding","connection"):
                self.send_header(key,value)
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        try:self.wfile.write(body)
        except BrokenPipeError:pass

ThreadingHTTPServer(("127.0.0.1",8018),Proxy).serve_forever()
