"""
Current Limitations:
1. Streaming only works for one command at a time.
2. It only streams stdout, not stderr.
3. It requires sending the session_id with every request. (This will change.)

Todo:
1. Make it stream stderr too...
"""

import socketio
import asyncio
import aiohttp
from pydantic import BaseModel
from typing import Literal, Optional, AsyncIterator, Union
from enum import Enum


class CommandMode(str, Enum):
    STREAM = "stream"
    WAIT = "wait"
    BACKGROUND = "background"


class CommandOutput(BaseModel):
    output: str
    type: Literal["stdout", "stderr"]
    process_id: Union[str, int]


class CommandExit(BaseModel):
    exit_code: int
    process_id: Union[str, int]


class CommandResult(BaseModel):
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    finished: bool


class Status(BaseModel):
    running: bool | None


class CommandKilled(BaseModel):
    status: str
    exit_code: Optional[int] = None


class CommandError(BaseModel):
    error: str


class BackgroundProcess(BaseModel):
    process_id: Union[str, int]


class StreamProcess:
    def __init__(self, process_id: int, stream_queue: asyncio.Queue):
        self.process_id = process_id
        self.stream_queue = stream_queue

    async def stream(self) -> AsyncIterator[CommandOutput]:
        while True:
            output = await self.stream_queue.get()
            if output is None:  # End of stream
                break
            yield output
            
    def __aiter__(self):
        return self.stream()


class SandboxClient:
    def __init__(self, url: str = "http://localhost:80"):
        self.url = url
        self.sio = socketio.AsyncClient()
        self.sessions = {}
        self.initialized_event = asyncio.Event()
        self.stream_queues: dict[int, asyncio.Queue] = {}
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
        data = CommandOutput(**data)
        await self.stream_queues[data.process_id].put(data)

    async def on_command_exit(self, data):
        exit_info = CommandExit(**data)
        print(
            f"Command exited with code {exit_info.exit_code} (Process ID: {exit_info.process_id})"
        )
        await self.stream_queues[exit_info.process_id].put(None)  # Signal the end of the stream

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

    async def connect(self):
        await self.sio.connect(self.url, transports=["websocket"])

    async def initialize_session(self, session_id: str, path: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/initialize",
                json={"session_id": session_id, "path": path},
            ) as response:
                init_response = await response.json()
                self.sessions[session_id] = init_response["session_id"]

        await self.sio.emit("initialize", {"session_id": session_id})
        await self.initialized_event.wait()

    async def run_command(
        self,
        session_id: str,
        command: str,
        mode: CommandMode = CommandMode.STREAM,
        path: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[CommandResult, BackgroundProcess, StreamProcess]:
        print(f"Running command: {command}, mode: {mode}, path: {path}, timeout: {timeout}")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/run_command",
                json={
                    "session_id": session_id,
                    "command": command,
                    "mode": mode,
                    "path": path,
                    "timeout": timeout,
                },
            ) as response:
                result = await response.json()

        if mode == CommandMode.STREAM:
            process_id = result["process_id"]
            self.stream_queues[process_id] = asyncio.Queue()
            await self.sio.emit(
                "start_command_stream",
                {"session_id": session_id, "process_id": process_id},
            )
            return StreamProcess(process_id, self.stream_queues[process_id])
        elif mode == CommandMode.WAIT:
            return CommandResult(**result)
        elif mode == CommandMode.BACKGROUND:
            return BackgroundProcess(process_id=result["process_id"])

    async def check_status(self, session_id: str, process_id: str) -> Status:
        # Create an event to wait for the status response
        status_event = asyncio.Event()
        status_data = {}

        async def on_status(data):
            nonlocal status_data
            status_data = data
            status_event.set()

        # Temporarily override the on_status handler
        self.sio.on("status", on_status)

        # Emit the check_status event with session_id and process_id
        await self.sio.emit(
            "check_status", {"session_id": session_id, "process_id": process_id}
        )

        # Wait for the status response
        await status_event.wait()

        # Restore the original on_status handler
        self.sio.on("status", self.on_status)

        return Status(**status_data)

    async def kill_command(self, session_id: str, process_id: str) -> CommandKilled:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/kill_command",
                json={"session_id": session_id, "process_id": process_id},
            ) as response:
                result = await response.json()

        # Ensure the result includes a status field
        if "status" not in result:
            result["status"] = "not found"

        return CommandKilled(**result)

    async def disconnect(self):
        await self.sio.disconnect()
        # Ensure all sessions are closed
        await self.sio.eio.disconnect()

    async def get_file(self, session_id: str, file_path: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.url}/read_file",
                params={"session_id": session_id, "file_path": file_path},
            ) as response:
                if response.status == 200:
                    return (await response.json())["content"]
                else:
                    raise Exception(f"Failed to get file: {response.status}")

    async def write_file(
        self, session_id: str, file_path: str, content: str, make_dirs: bool = False
    ):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/write_file",
                json={
                    "session_id": session_id,
                    "file_path": file_path,
                    "content": content,
                    "make_dirs": make_dirs,
                },
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to write file: {response.status}")

    async def make_dirs(self, session_id: str, file_path: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/make_dirs",
                json={"session_id": session_id, "file_path": file_path},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to make dirs: {response.status}")

    async def delete_file(self, session_id: str, file_path: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/delete_file",
                json={"session_id": session_id, "file_path": file_path},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to delete file: {response.status}")

    async def file_exists(self, session_id: str, file_path: str) -> bool:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.url}/file_exists",
                params={"session_id": session_id, "file_path": file_path},
            ) as response:
                if response.status == 200:
                    return await bool(response.json()["exists"])
                elif response.status == 404:
                    return False
                else:
                    raise Exception(
                        f"Failed to check if file exists: {response.status}"
                    )

    async def get_all_file_paths(self, session_id: str, regexes: list[str] = []) -> list[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.url}/get_all_file_paths",
                params={"session_id": session_id, "regexes": regexes},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to get file paths: {response.status}")


if __name__ == "__main__":

    async def main():
        client = SandboxClient(url="http://4.156.80.55:80")
        await client.connect()

        # Initialize a session
        await client.initialize_session("your-session-id-here", "test_path")

        result = await client.run_command(
            "your-session-id-here",
            "git clone https://github.com/lukejagg/ichi-site.git test_path",
            mode=CommandMode.WAIT,
        )
        print("Result:", result)

        result = await client.run_command(
            "your-session-id-here", "ls -la", mode=CommandMode.WAIT, path="test_path"
        )
        print(result.stdout)

        result = await client.file_exists("your-session-id-here", "test_path/LICENSE")
        print(result)

        result = await client.get_file("your-session-id-here", "test_path/LICENSE")
        print(result)

        result = await client.write_file(
            "your-session-id-here", "test_path/LICENSE", "Hello, World!"
        )
        print(result)

        result = await client.read_file("your-session-id-here", "test_path/LICENSE")
        print(result)

        result = await client.run_command(
            "your-session-id-here",
            "npm install",
            mode=CommandMode.STREAM,
            path="test_path",
        )
        async for output in result:
            print(output.output)

        result = await client.run_command(
            "your-session-id-here",
            "npm run start",
            mode=CommandMode.STREAM,
            path="test_path",
            # timeout=200,
        )
        async for output in result:
            print(output.output)

        return

        # Run a command in STREAM mode
        async for output in await client.run_command(
            "your-session-id-here", "echo Hello, World!", mode=CommandMode.STREAM
        ):
            print("Streamed Output:", output)

        # Run a command in WAIT mode
        for i in range(10):
            result = await client.run_command(
                "your-session-id-here", "echo HELLO WORLD!", mode=CommandMode.WAIT
            )
            print("Command Result:", result)

        # Run a command in BACKGROUND mode
        background_process = await client.run_command(
            "your-session-id-here",
            "echo Hello, World! && sleep 10",
            mode=CommandMode.BACKGROUND,
        )
        print("Background Process ID:", background_process.process_id)

        # Check the status of the command
        status = await client.check_status(
            "your-session-id-here", background_process.process_id
        )
        print("Status:", status)

        # Kill the command
        killed_info = await client.kill_command(
            "your-session-id-here", background_process.process_id
        )
        print("Killed Info:", killed_info)

        # Example usage of get_file
        try:
            file_content = await client.get_file("your-session-id-here", "LICENSE")
            print("File Content:", file_content)
        except Exception as e:
            print(e)

        # Example usage of get_all_file_paths
        try:
            file_paths = await client.get_all_file_paths("your-session-id-here")
            print("File Paths:", file_paths)
        except Exception as e:
            print(e)

        # Disconnect from the server
        await client.disconnect()

    # Run the main function
    asyncio.run(main())
