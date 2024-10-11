import socketio
import time

# Create a Socket.IO client
sio = socketio.Client()

# Define event handlers
@sio.event
def connect():
    print("Connected to the server")

@sio.event
def disconnect():
    print("Disconnected from the server")

@sio.on('initialized')
def on_initialized(data):
    print("Initialization response:", data)

@sio.on('command_output')
def on_command_output(data):
    print("Command output:", data)

@sio.on('command_exit')
def on_command_exit(data):
    print("Command exited with code:", data)

@sio.on('command_result')
def on_command_result(data):
    print("Command result:", data)

@sio.on('status')
def on_status(data):
    print("Status:", data)

@sio.on('killed')
def on_killed(data):
    print("Command killed:", data)

@sio.on('error')
def on_error(data):
    print("Error:", data)

# Connect to the server
sio.connect('http://localhost:80')

# Initialize a session
sio.emit('initialize', {
    'path': '/some/path',
    'github_url': None,
    'from_scratch': False
})

# Run a command
sio.emit('run_command', {
    'command': 'echo Hello, World!',
    'streaming': True
})

# Wait a bit to receive output
time.sleep(2)

# Check the status of the command
sio.emit('check_status', {
    'session_id': 'your-session-id-here'  # Replace with actual session ID
})

# Wait a bit to receive status
time.sleep(2)

# Kill the command
sio.emit('kill_command', {
    'session_id': 'your-session-id-here'  # Replace with actual session ID
})

# Wait a bit to receive kill confirmation
time.sleep(2)

# Disconnect from the server
sio.disconnect()