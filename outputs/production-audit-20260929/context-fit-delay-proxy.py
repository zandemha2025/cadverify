"""Loopback regression control; forward real uploads and delay fit replies."""
import asyncio
import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI()


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(request: Request, path: str):
    if request.method == "POST" and path != "api/v1/validate/fit":
        return Response(status_code=405)
    body = await request.body()
    if len(body) > 16 * 1024 * 1024:
        return Response(status_code=413)
    headers = {k: v for k, v in request.headers.items() if k not in ("host", "connection", "content-length", "transfer-encoding")}
    async with httpx.AsyncClient(timeout=120) as client:
        upstream = await client.request(request.method, "http://127.0.0.1:8017/" + path,
            params=request.query_params, headers=headers, content=body)
    if request.method == "POST":
        print({"fit_status": upstream.status_code, "held_seconds": 4}, flush=True)
        await asyncio.sleep(4)
        print({"fit_delivered": upstream.status_code}, flush=True)
    headers = {k: v for k, v in upstream.headers.items() if k not in ("content-length", "content-encoding", "transfer-encoding", "connection")}
    return Response(upstream.content, status_code=upstream.status_code, headers=headers)


uvicorn.run(app, host="127.0.0.1", port=8018, access_log=False)
