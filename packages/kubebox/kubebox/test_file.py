import socketio
import asyncio
import aiohttp

# Create a Socket.IO client
sio = socketio.AsyncClient()

# Event to wait for initialization
initialized_event = asyncio.Event()


# Define event handlers
@sio.event
async def connect():
    print("Connected to the server")


@sio.event
async def disconnect():
    print("Disconnected from the server")


@sio.on("initialized")
async def on_initialized(data):
    print("Initialization response:", data)
    initialized_event.set()  # Signal that initialization is complete


@sio.on("command_output")
async def on_command_output(data):
    print(f"Command output (Process ID: {data['process_id']}):", data["output"])


@sio.on("command_exit")
async def on_command_exit(data):
    print(
        f"Command exited with code {data['exit_code']} (Process ID: {data['process_id']})"
    )


@sio.on("command_result")
async def on_command_result(data):
    print("Command result:", data)


@sio.on("status")
async def on_status(data):
    print("Status:", data)


@sio.on("killed")
async def on_killed(data):
    print("Command killed:", data)


@sio.on("error")
async def on_error(data):
    print("Error:", data)


async def main():
    # Connect to the server
    await sio.connect("http://localhost:80", transports=["websocket"])

    # Initialize a session via HTTP request
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:80/initialize",
            json={"session_id": "your-session-id-here", "path": "/some/path"},
        ) as response:
            init_response = await response.json()
            session_id = init_response["session_id"]

    # Emit initialize event with session_id
    await sio.emit("initialize", {"session_id": session_id})

    # Wait for the initialized event
    await initialized_event.wait()

    # Run a command in STREAM mode
    await sio.emit(
        "run_command",
        {"command": "echo Hello, World!", "mode": "stream"},
    )

    # Wait a bit to receive output
    await asyncio.sleep(2)

    # Check the status of the command
    await sio.emit("check_status", {})

    # Wait a bit to receive status
    await asyncio.sleep(2)

    # Kill the command using Socket.IO
    await sio.emit("kill_command", {"process_id": "your-process-id-here"})

    # Wait a bit to receive kill confirmation
    await asyncio.sleep(2)

    # Disconnect from the server
    await sio.disconnect()


# Run the main function
asyncio.run(main())
