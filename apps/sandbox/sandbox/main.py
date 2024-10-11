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

from fastapi import FastAPI
from pydantic import BaseModel
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
        self.sio = socketio.AsyncServer(async_mode="asgi", max_http_buffer_size=10_000_000, cors_allowed_origins="*")
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
    path: str
    github_url: str | None = None
    from_scratch: bool | None = None


# Dictionary to track active processes
active_processes = {}


@sio.on("connect")
async def connect(sid, environ):
    print(f"Client {sid} connected")


@sio.on("initialize")
async def initialize(sid, data):
    init_type = InitType(**data)
    session_path = init_type.path or "/default/path"
    # Store session_path in a session store if needed
    await sio.emit("initialized", {"status": "success"}, room=sid)


@sio.on("run_command")
async def run_command(sid, data):
    command = data.get("command")
    streaming = data.get("streaming", False)
    timeout = data.get("timeout", 10)
    session_id = str(uuid.uuid4())  # Generate a unique session ID

    if streaming:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        active_processes[session_id] = process

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await sio.emit(
                "command_output",
                {"output": line.decode(), "session_id": session_id},
                room=sid,
            )

        await process.wait()
        del active_processes[session_id]
        await sio.emit(
            "command_exit",
            {"exit_code": process.returncode, "session_id": session_id},
            room=sid,
        )

    else:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            await sio.emit(
                "command_result",
                {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "finished": result.returncode == 0,
                    "session_id": session_id,
                },
                room=sid,
            )
        except subprocess.TimeoutExpired:
            await sio.emit(
                "command_error",
                {
                    "error": "Command timed out",
                    "finished": False,
                    "session_id": session_id,
                },
                room=sid,
            )


@sio.on("check_status")
async def check_status(sid, data):
    session_id = data.get("session_id")
    process = active_processes.get(session_id)

    if process:
        running = process.returncode is None
        await sio.emit(
            "status", {"running": running, "session_id": session_id}, room=sid
        )
    else:
        await sio.emit("status", {"running": False, "session_id": session_id}, room=sid)


@sio.on("kill_command")
async def kill_command(sid, data):
    session_id = data.get("session_id")
    process = active_processes.get(session_id)

    if process:
        process.terminate()
        await process.wait()
        del active_processes[session_id]
        await sio.emit(
            "killed",
            {"session_id": session_id, "exit_code": process.returncode},
            room=sid,
        )
    else:
        await sio.emit(
            "error", {"error": "No such session", "session_id": session_id}, room=sid
        )


@sio.on("disconnect")
async def disconnect(sid):
    print(f"Client {sid} disconnected")


@app.get("/")
async def read_root():
    return {"message": "Hello, World!"}


@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
