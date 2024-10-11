"""
Features:
1. Establish a WebSocket connection using Socket.IO for automatic reconnection.
2. Initialize a session with an InitType containing:
   - path: str
   - github_url: str | None
   - from_scratch: bool | None
3. Execute shell commands with options for:
   - Streaming output: Stream command output line-by-line until completion.
   - Non-streaming: Execute with a timeout and return stdout, stderr, exit code, and completion status.
4. Assign a unique session ID to each terminal session.
5. Track and manage terminal sessions:
   - Check if a session is still running.
   - Terminate a session by its session ID.
6. Emit session-related events and results back to the client.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from enum import Enum
import socketio
import subprocess
import asyncio
import uuid

app = FastAPI()


class SocketManager:
    def __init__(self):
        self.sio: socketio.AsyncServer = None
        self.socket_app: socketio.ASGIApp = None
        self.app: FastAPI = None

    def initialize(self, app: FastAPI):
        self.sio = socketio.AsyncServer(
            async_mode="asgi", max_http_buffer_size=10_000_000, cors_allowed_origins="*"
        )
        self.socket_app = socketio.ASGIApp(socketio_server=self.sio)
        self.app = app
        self.app.mount("/socket.io", self.socket_app)

    def on(self, event: str):
        def wrapper(func):
            self.sio.on(event)(func)
            return func

        return wrapper

    async def emit(self, *args, **kwargs):
        # event: str, data: dict, to: str
        print(f"Emitting event {kwargs}")
        await self.sio.emit(*args, **kwargs)


sio = SocketManager()
sio.initialize(app)


class InitType(BaseModel):
    session_id: str
    path: str


class InitResponse(BaseModel):
    session_id: str


class ExecutionMode(str, Enum):
    WAIT = "wait"
    BACKGROUND = "background"
    STREAM = "stream"


class Process:
    def __init__(self, pid, process=None, stdout=None, stderr=None):
        self.pid = pid
        self.process = process  # Store the actual asyncio subprocess
        self.exit_code = None
        self._stdout = stdout
        self._stderr = stderr

    @property
    def outputs(self):
        return self._stdout

    @property
    def errors(self):
        return self._stderr

    def update_outputs(self, stdout, stderr):
        self._stdout = stdout
        self._stderr = stderr


class Session:
    def __init__(self, session_id, path, sid=None):
        self.session_id = session_id
        self.path = path
        self.sid = sid
        self.active_processes = {}

    def set_sid(self, sid):
        self.sid = sid

    def add_process(self, process):
        self.active_processes[process.pid] = process

    def remove_process(self, process):
        self.active_processes.pop(process.pid, None)

    def get_process(self, process_id):
        return self.active_processes.get(process_id)


class SessionManager:
    def __init__(self):
        self.sessions = {}

    def create_session(self, session_id, path):
        self.sessions[session_id] = Session(session_id, path)

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def add_process(self, session_id, process):
        session = self.get_session(session_id)
        if session:
            session.add_process(process)

    def remove_process(self, session_id, process):
        session = self.get_session(session_id)
        if session:
            session.remove_process(process)

    def get_process(self, session_id, process_id):
        session = self.get_session(session_id)
        if session:
            return session.get_process(process_id)

    def set_session_sid(self, session_id, sid):
        session = self.get_session(session_id)
        if session:
            session.set_sid(sid)

    def get_session_by_sid(self, sid):
        for session in self.sessions.values():
            if session.sid == sid:
                return session
        return None


session_manager = SessionManager()


@app.post("/initialize")
async def initialize(init_data: InitType):
    session_id = init_data.session_id
    session_path = init_data.path or "/default/path"
    session_manager.create_session(session_id, session_path)
    return InitResponse(session_id=session_id)


@app.post("/run_command")
async def run_command(data: dict):
    session_id = data.get("session_id")
    command = data.get("command")
    mode = data.get("mode", ExecutionMode.WAIT)
    timeout = data.get("timeout", 10)

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    if mode == ExecutionMode.STREAM:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        process_obj = Process(process.pid, process, process.stdout, process.stderr)
        session_manager.add_process(session_id, process_obj)
        return {"process_id": process.pid}

    elif mode == ExecutionMode.WAIT:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            # No need to create a Process object for WAIT mode
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "finished": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "error": "Command timed out",
                "finished": False,
            }

    elif mode == ExecutionMode.BACKGROUND:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        process_obj = Process(process.pid, process, process.stdout, process.stderr)
        session_manager.add_process(session_id, process_obj)
        return {"process_id": process.pid}


@sio.on("start_command_stream")
async def start_command_stream(sid, data):
    session_id = data.get("session_id")
    process_id = data.get("process_id")

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    process: Process = session.get_process(process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    async def stream_output():
        try:
            while True:
                line = await process._stdout.readline()
                if not line:
                    break
                await sio.emit(
                    "command_output",
                    {
                        "output": line.decode(),
                        "session_id": session_id,
                        "process_id": process_id,
                    },
                    room=session.sid,
                )
        except Exception as e:
            print(f"Error during streaming: {e}")
        finally:
            await process.process.wait()  # Ensure the process is waited on
            process.exit_code = process.process.returncode
            session_manager.remove_process(session_id, process)
            await sio.emit(
                "command_exit",
                {
                    "exit_code": process.exit_code,
                    "session_id": session_id,
                    "process_id": process_id,
                },
                room=session.sid,
            )

    asyncio.create_task(stream_output())


@app.post("/kill_command")
async def kill_command(data: dict):
    session_id = data.get("session_id")
    process_id = data.get("process_id")

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    process = session.get_process(process_id)
    if process:
        process.terminate()
        await process.wait()
        session.remove_process(process)
        return {
            "status": "killed",
            "exit_code": process.returncode,
        }
    else:
        raise HTTPException(status_code=404, detail="No such process")


@sio.on("connect")
async def connect(sid, environ):
    print(f"Client {sid} connected")


@sio.on("initialize")
async def sio_initialize(sid, data):
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID is required")

    session_manager.set_session_sid(session_id, sid)

    await sio.emit(
        "initialized", {"status": "success", "session_id": session_id}, room=sid
    )


@sio.on("check_status")
async def check_status(sid, data):
    process_id = data.get("process_id")
    session = session_manager.get_session_by_sid(sid)

    if session:
        process = session.get_process(process_id)
        running = process and process.returncode is None
        await sio.emit(
            "status", {"running": running, "session_id": session.session_id}, room=sid
        )
    else:
        await sio.emit("status", {"running": False, "session_id": None}, room=sid)


@sio.on("disconnect")
async def disconnect(sid):
    print(f"Client {sid} disconnected")


@app.get("/")
async def read_root():
    return {"message": "Hello, World!"}


@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
