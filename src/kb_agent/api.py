import asyncio
import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import AgentRunner
from .corpus import ROOT
from .models import LiveModel, MockModel, ModelConfig, ModelError
from .scenarios import EXAMPLES, faults_for, scenario_corpus
from .schemas import AskRequest

app = FastAPI(title="知据 · 企业知识助手", version="0.1.0", description="本地合成资料演示。Mock 只验证流程；真实模型必须显式配置。")
app.state.tasks = set()


@app.get("/api/health")
def health():
    error = None
    try:
        configured = ModelConfig.from_env().configured
    except ModelError as exc:
        configured = False
        error = str(exc)
    return {"status": "ok", "model_configured": configured, "available_modes": ["mock", "live"] if configured else ["mock"], "default_mode": "mock", **({"configuration_error": error} if error else {})}


@app.get("/api/examples")
def examples():
    return {"examples": EXAMPLES}


@app.post("/api/ask", response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}, "description": "SSE: run_started/action/tool_result/validation_error/final. Each data is an Event; final.payload.output is Output."}})
async def ask(body: AskRequest, request: Request):
    try:
        corpus = scenario_corpus(body.scenario_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    try:
        config = ModelConfig.from_env() if body.mode == "live" else None
    except ModelError as exc:
        raise HTTPException(503, str(exc)) from None
    if config is not None and not config.configured:
        raise HTTPException(503, "真实模型未配置；请填写 config.local.toml、设置服务端环境变量，或显式选择离线演示。")
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    cancel = threading.Event()

    def publish(event):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            cancel.set()

    try:
        # Explicit Mock-only pacing makes streaming/cancellation observable.
        # CLI and evaluation keep the fixture immediate; live calls are untouched.
        runner = AgentRunner(body, corpus, model=MockModel(delay=0.25) if body.mode == "mock" else LiveModel(config), faults=faults_for(body.scenario_id), cancel=cancel, on_event=publish)
    except ModelError as exc:
        raise HTTPException(503, str(exc)) from None
    runner.output_dir = Path(os.environ.get("KB_RUNS_DIR", str(ROOT / ".runtime/runs"))) / runner.run_id

    async def stream():
        task = asyncio.create_task(asyncio.to_thread(runner.run))
        app.state.tasks.add(task)

        def finished(completed):
            app.state.tasks.discard(completed)
            # Retrieve exceptions (e.g. a failed local trace write), avoiding an
            # unobserved background exception; run final events remain truthful.
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    if task.done():
                        break
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {item['event']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item["event"] == "final":
                    break
        finally:
            cancel.set()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "web/index.html")


app.mount("/assets", StaticFiles(directory=ROOT / "web/static", check_dir=False), name="assets")
