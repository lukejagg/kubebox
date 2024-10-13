import os
from dotenv import load_dotenv
from kubebox import Kubebox, SandboxClient, CommandMode

load_dotenv()
KUBEBOX_CONFIG = os.getenv("KUBEBOX_CONFIG")


async def main():
    kubebox = Kubebox(KUBEBOX_CONFIG)
    pod = kubebox.create_pod("test-pod", username="test-user")
    service = kubebox.create_service("test-pod", username="test-user", ports=[3000])
    await pod.wait_until_ready()
    await service.wait_until_ready()
    ip = await service.get_external_ip()
    print(f"http://{ip}")

    client = SandboxClient(f"http://{ip}")
    await client.connect()
    await client.initialize_session("test-session", "test_path")
    result = await client.run_command(
        "test-session",
        "git clone https://github.com/lukejagg/ichi-site.git test_path",
        mode=CommandMode.WAIT,
    )
    print("Result:", result)

    result = await client.run_command(
        "test-session", "ls -la", mode=CommandMode.WAIT, path="test_path"
    )
    print(result.stdout)

    result = await client.run_command(
        "test-session",
        "npm install",
        mode=CommandMode.STREAM,
        path="test_path",
    )
    async for output in result:
        print(output.output)

    result = await client.run_command(
        "test-session",
        "npm run start",
        mode=CommandMode.STREAM,
        path="test_path",
    )
    async for output in result:
        print(output.output)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
