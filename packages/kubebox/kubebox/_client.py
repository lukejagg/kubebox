"""
Current Limitations:
1. Streaming only works for one command at a time.
2. It only streams stdout, not stderr.
"""

import socketio
import asyncio
import aiohttp
from pydantic import BaseModel
from typing import Optional, AsyncIterator, Union
from enum import Enum


class CommandMode(str, Enum):
    STREAM = "stream"
    WAIT = "wait"
    BACKGROUND = "background"


class CommandOutput(BaseModel):
    output: str
    process_id: Union[str, int]


class CommandExit(BaseModel):
    exit_code: int
    process_id: Union[str, int]


class CommandResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
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


class SandboxClient:
    def __init__(self, url: str = "http://localhost:80"):
        self.url = url
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
        print(
            f"Command exited with code {exit_info.exit_code} (Process ID: {exit_info.process_id})"
        )
        await self.stream_queue.put(None)  # Signal the end of the stream

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
        self, session_id: str, command: str, mode: CommandMode = CommandMode.STREAM
    ) -> Union[AsyncIterator[CommandOutput], CommandResult, BackgroundProcess]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/run_command",
                json={"session_id": session_id, "command": command, "mode": mode},
            ) as response:
                result = await response.json()

        if mode == CommandMode.STREAM:
            process_id = result["process_id"]
            await self.sio.emit(
                "start_command_stream",
                {"session_id": session_id, "process_id": process_id},
            )
            return self._stream_output()
        elif mode == CommandMode.WAIT:
            return CommandResult(**result)
        elif mode == CommandMode.BACKGROUND:
            return BackgroundProcess(process_id=result["process_id"])

    async def _stream_output(self) -> AsyncIterator[CommandOutput]:
        while True:
            output = await self.stream_queue.get()
            if output is None:  # End of stream
                break
            yield output

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

    async def get_file(self, file_path: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/get_file", params={"file_path": file_path}) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    raise Exception(f"Failed to get file: {response.status}")

    async def get_all_file_paths(self) -> list[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/get_all_file_paths") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to get file paths: {response.status}")


if __name__ == "__main__":

    async def main():
        client = SandboxClient(url="http://localhost:80")
        await client.connect()

        # Initialize a session
        await client.initialize_session("your-session-id-here", "/some/path")

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

        # Disconnect from the server
        await client.disconnect()

        # Example usage of get_file
        try:
            file_content = await client.get_file("path/to/your/file.txt")
            print("File Content:", file_content)
        except Exception as e:
            print(e)

        # Example usage of get_all_file_paths
        try:
            file_paths = await client.get_all_file_paths()
            print("File Paths:", file_paths)
        except Exception as e:
            print(e)

    # Run the main function
    asyncio.run(main())
