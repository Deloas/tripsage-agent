import shutil
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def command_version(command: str) -> str:
    """读取命令版本；命令不存在时返回未找到。"""
    executable = shutil.which(command)
    if not executable:
        return "未找到"
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return (result.stdout or result.stderr).strip() or "可用"
    except Exception as exc:  # noqa: BLE001
        return f"检测失败：{exc}"


def port_free(port: int) -> bool:
    """检测本地端口是否空闲，避免启动时端口冲突。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def file_status(path: str) -> str:
    """检测关键文件是否存在。"""
    return "存在" if (ROOT / path).exists() else "缺失"


def main() -> int:
    """运行前自检，不安装依赖、不修改文件。"""
    checks = {
        "Python": sys.version.split()[0],
        "Node": command_version("node"),
        "npm": command_version("npm"),
        "backend/.env.example": file_status("backend/.env.example"),
        "frontend/.env.example": file_status("frontend/.env.example"),
        "mcp_servers.example.json": file_status("mcp_servers.example.json"),
        "start.bat": file_status("start.bat"),
        "后端端口 8000": "空闲" if port_free(8000) else "已占用",
        "前端端口 5173": "空闲" if port_free(5173) else "已占用",
    }

    print("TripSage Agent 运行前自检")
    print("=" * 36)
    for name, value in checks.items():
        print(f"{name}: {value}")

    failed = [
        name
        for name, value in checks.items()
        if value in {"未找到", "缺失", "已占用"} or str(value).startswith("检测失败")
    ]
    if failed:
        print("\n需要处理的项目：")
        for item in failed:
            print(f"- {item}")
        return 1

    print("\n自检通过，可以继续运行 start.bat。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

