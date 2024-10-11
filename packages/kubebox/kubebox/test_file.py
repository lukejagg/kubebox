import socketio
import asyncio
import aiohttp
from pydantic import BaseModel
from typing import Optional, AsyncIterator, Union

class CommandOutput(BaseModel):
    output: str
    process_id: Union[str, int]  # Accept both string and integer

class CommandExit(BaseModel):
    exit_code: int
    process_id: Union[str, int]  # Accept both string and integer

class CommandResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    finished: bool

class Status(BaseModel):
    running: bool

class CommandKilled(BaseModel):
    status: str
    exit_code: Optional[int] = None

class CommandError(BaseModel):
    error: str

class BackgroundProcess(BaseModel):
    process_id: Union[str, int]  # Accept both string and integer

class SessionManager:
    def __init__(self):
        self.sio = socketio.AsyncClient()
        self.sessions = {}
        self.initialized_event = asyncio.Event()
        self.stream_queue = asyncio.Queue()
        self.result_event = asyncio.Event()
        self.result_data = None

        # Register event handlers
        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on("initialized", self.on_initialized)
        self.sio.on("command_output", self.on_command_output)
        self.sio.on("command_exit", self.on_command_exit)
        self.sio.on("command_result", self.on_command_result)
        self.sio.on("status", self.on_status)
        self.sio.on("command_killed", self.on_killed)
        self.sio.on("command_error", self.on_error)

    async def on_connect(self):
        print("Connected to the server")

    async def on_disconnect(self):
        print("Disconnected from the server")

    async def on_initialized(self, data):
        print("Initialization response:", data)
        self.initialized_event.set()

    async def on_command_output(self, data):
        await self.stream_queue.put(CommandOutput(**data))

    async def on_command_exit(self, data):
        exit_info = CommandExit(**data)
        print(f"Command exited with code {exit_info.exit_code} (Process ID: {exit_info.process_id})")

    async def on_command_result(self, data):
        self.result_data = CommandResult(**data)
        self.result_event.set()

    async def on_status(self, data):
        status = Status(**data)
        print("Status:", status)

    async def on_killed(self, data):
        killed_info = CommandKilled(**data)
        print("Command killed:", killed_info)

    async def on_error(self, data):
        error_info = CommandError(**data)
        print("Error:", error_info)

    async def connect(self, url: str):
        await self.sio.connect(url, transports=["websocket"])

    async def initialize_session(self, session_id: str, path: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:80/initialize",
                json={"session_id": session_id, "path": path},
            ) as response:
                init_response = await response.json()
                self.sessions[session_id] = init_response["session_id"]

        await self.sio.emit("initialize", {"session_id": session_id})
        await self.initialized_event.wait()

    async def run_command(self, command: str, mode: str = "stream") -> Union[AsyncIterator[CommandOutput], CommandResult, BackgroundProcess]:
        await self.sio.emit("run_command", {"command": command, "mode": mode})

        if mode == "stream":
            return self._stream_output()
        elif mode == "wait":
            await self.result_event.wait()
            self.result_event.clear()
            return self.result_data
        elif mode == "background":
            process_info = await self.stream_queue.get()
            return BackgroundProcess(process_id=process_info.process_id)

    async def _stream_output(self) -> AsyncIterator[CommandOutput]:
        while True:
            output = await self.stream_queue.get()
            if output is None:  # End of stream
                break
            yield output

    async def check_status(self) -> Status:
        await self.sio.emit("check_status", {})
        # Assuming the status is returned immediately for simplicity
        return Status(running=True)  # Placeholder for actual status

    async def kill_command(self, process_id: str) -> CommandKilled:
        await self.sio.emit("kill_command", {"process_id": process_id})
        # Assuming the command killed response is returned immediately for simplicity
        return CommandKilled(status="killed")  # Placeholder for actual response

    async def disconnect(self):
        await self.sio.disconnect()

async def main():
    manager = SessionManager()
    await manager.connect("http://localhost:80")

    # Initialize a session
    await manager.initialize_session("your-session-id-here", "/some/path")

    # Run a command in STREAM mode
    async for output in await manager.run_command("echo Hello, World! && sleep 1 && echo Hi 1>&2 && sleep 1 && echo 2", mode="stream"):
        print("Streamed Output:", output)
        
    # Run a command in WAIT mode
    result = await manager.run_command("echo Hello, World!", mode="wait")
    print("Command Result:", result)

    # Run a command in BACKGROUND mode
    background_process = await manager.run_command("echo Hello, World!", mode="background")
    print("Background Process ID:", background_process.process_id)

    # Check the status of the command
    status = await manager.check_status()
    print("Status:", status)

    # Kill the command
    killed_info = await manager.kill_command("your-process-id-here")
    print("Killed Info:", killed_info)

    # Disconnect from the server
    await manager.disconnect()

# Run the main function
asyncio.run(main())