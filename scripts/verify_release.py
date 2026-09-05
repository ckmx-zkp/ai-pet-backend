"""只读检查三个应用容器使用同一提交及镜像，验证 API / MCP 协议。"""

import json
import subprocess
import sys
import time


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    expected = sys.argv[1] if len(sys.argv) > 1 else command("git", "rev-parse", "HEAD")
    images: set[str] = set()
    for service in ("web-api", "memory-mcp", "agent-worker"):
        container = command("docker", "compose", "ps", "-q", service)
        if not container:
            raise RuntimeError(f"{service}: 未运行")
        # 仅输出版本与镜像字段，不输出容器环境变量。
        revision = command("docker", "exec", container, "cat", "/app-revision")
        image = command("docker", "inspect", "--format", "{{.Image}}", container)
        if revision != expected:
            raise RuntimeError(f"{service}: 版本不一致 {revision}")
        images.add(image)
        print(f"{service}: {revision} {image}")
    if len(images) != 1:
        raise RuntimeError("三个应用服务未使用同一镜像")

    # 令牌只在容器内部读取与使用，不作为命令参数传输或输出。
    probe = '''
import os, httpx
with httpx.Client(timeout=5) as client:
    assert client.get("http://127.0.0.1:8000/healthz").status_code == 200
    url = "http://memory-mcp:8000/mcp"
    assert client.post(url, json={}).status_code == 401
    headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"],
               "Accept": "application/json, text/event-stream"}
    body = {"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{
        "protocolVersion":"2024-11-05", "capabilities":{},
        "clientInfo":{"name":"release-check","version":"1"}}}
    response = client.post(url, headers=headers, json=body)
    response.raise_for_status()
    assert "result" in response.json()
    response = client.post(url, headers=headers,
        json={"jsonrpc":"2.0", "id":2, "method":"tools/list", "params":{}})
    response.raise_for_status()
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == {"memory.search", "memory.add", "memory.forget"}, names
print("API 200 / MCP 401 / initialize / tools-list: 通过")
'''
    container = command("docker", "compose", "ps", "-q", "web-api")
    for _attempt in range(12):
        result = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-"],
            input=probe, text=True, capture_output=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
            print(json.dumps({"revision": expected, "verified": True}))
            return
        time.sleep(2)
    # 不输出 HTTP 异常体，避免意外回显运行配置。
    raise RuntimeError("API/MCP 启动探测未通过，请检查服务状态")


if __name__ == "__main__":
    main()
