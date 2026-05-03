from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import ROOT_DIR, settings


BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
LOG_DIR = ROOT_DIR / "logs"
BACKEND_URL = "http://127.0.0.1:8000/api/health"


@dataclass
class CheckResult:
    """统一记录每个交付检查步骤的结果。"""

    name: str
    status: str
    detail: str


def console_text(value: object) -> str:
    """兼容 Windows 终端编码，避免摘要输出出现异常。"""

    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="ignore").decode(encoding, errors="ignore")


def print_step(message: str) -> None:
    """输出统一的巡检进度信息。"""

    print(console_text(message), flush=True)


def run_command(name: str, command: list[str], cwd: Path) -> CheckResult:
    """执行命令并返回统一结果。"""

    print_step(f"[RUN] {name}")
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode == 0:
        return CheckResult(name=name, status="PASS", detail="命令执行成功")
    return CheckResult(name=name, status="FAIL", detail=f"退出码 {completed.returncode}")


def port_in_use(port: int) -> bool:
    """检查本地端口是否已被占用。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


async def wait_for_backend(timeout_seconds: float = 25.0) -> bool:
    """轮询健康接口，等待后端服务就绪。"""

    deadline = time.time() + timeout_seconds
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        while time.time() < deadline:
            try:
                response = await client.get(BACKEND_URL)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    return False


def should_run_deepseek() -> bool:
    """只有真实配置了大模型才执行 live 检查。"""

    return bool(settings.llm_api_key and settings.llm_model and settings.llm_base_url)


def should_run_amap() -> bool:
    """只有配置了高德 Key 才执行真实检查。"""

    return bool(settings.amap_api_key)


def should_run_web_search() -> bool:
    """联网搜索启用后才做连通性检查。"""

    return settings.web_search_enabled and settings.web_search_provider != "disabled"


def should_run_railway_live() -> bool:
    """12306 MCP 只有显式打开 live 才执行真实探活。"""

    return settings.mcp_12306_enabled and settings.mcp_12306_allow_live


def run_optional_check(
    name: str,
    command: list[str],
    cwd: Path,
    enabled: bool,
    skip_reason: str,
) -> CheckResult:
    """运行可选依赖检查，未启用则记为跳过。"""

    if not enabled:
        print_step(f"[SKIP] {name} - {skip_reason}")
        return CheckResult(name=name, status="SKIP", detail=skip_reason)
    return run_command(name, command, cwd)


async def run_backend_smokes(python_exe: Path) -> list[CheckResult]:
    """启动本地后端并执行核心烟测。"""

    LOG_DIR.mkdir(exist_ok=True)
    stdout_log = LOG_DIR / "check-all-backend.out.log"
    stderr_log = LOG_DIR / "check-all-backend.err.log"

    if port_in_use(8000):
        return [
            CheckResult(
                name="backend_server",
                status="SKIP",
                detail="检测到 8000 端口已占用，未重复启动后端",
            ),
            run_command(
                "backend_smoke_test",
                [str(python_exe), "-m", "app.scripts.smoke_test"],
                BACKEND_DIR,
            ),
            run_command(
                "workspace_user_flow_smoke",
                [str(python_exe), "-m", "app.scripts.smoke_workspace_user_flow"],
                BACKEND_DIR,
            ),
        ]

    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            [
                str(python_exe),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=BACKEND_DIR,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )

        try:
            print_step("[RUN] backend_server")
            ready = await wait_for_backend()
            if not ready:
                return [
                    CheckResult(
                        name="backend_server",
                        status="FAIL",
                        detail="后端启动超时，请检查 logs/check-all-backend.*.log",
                    )
                ]

            results = [CheckResult(name="backend_server", status="PASS", detail="健康接口已就绪")]
            results.append(
                run_command(
                    "backend_smoke_test",
                    [str(python_exe), "-m", "app.scripts.smoke_test"],
                    BACKEND_DIR,
                )
            )
            results.append(
                run_command(
                    "workspace_user_flow_smoke",
                    [str(python_exe), "-m", "app.scripts.smoke_workspace_user_flow"],
                    BACKEND_DIR,
                )
            )
            return results
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


async def main() -> int:
    """执行产品交付前的一键巡检。"""

    python_exe = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"

    if not python_exe.exists():
        print_step("未找到 backend/.venv，请先运行 start.bat 完成环境初始化。")
        return 1

    results: list[CheckResult] = []
    results.append(run_command("backend_pytest", [str(python_exe), "-m", "pytest", "-q"], ROOT_DIR))

    if not (FRONTEND_DIR / "node_modules").exists():
        results.append(
            CheckResult(
                name="frontend_build",
                status="FAIL",
                detail="未找到 frontend/node_modules，请先执行 npm install",
            )
        )
    else:
        results.append(run_command("frontend_build", ["cmd", "/c", "npm", "run", "build"], FRONTEND_DIR))

    results.extend(await run_backend_smokes(python_exe))

    results.append(
        run_optional_check(
            "deepseek_ping",
            [str(python_exe), "-m", "app.scripts.check_deepseek"],
            BACKEND_DIR,
            should_run_deepseek(),
            "未配置 DeepSeek API，当前按本地规则兜底运行",
        )
    )
    results.append(
        run_optional_check(
            "amap_ping",
            [str(python_exe), "-m", "app.scripts.check_amap"],
            BACKEND_DIR,
            should_run_amap(),
            "未配置高德 Key，当前按演示地图/天气兜底运行",
        )
    )
    results.append(
        run_optional_check(
            "web_search_ping",
            [str(python_exe), "-m", "app.scripts.check_web_search"],
            BACKEND_DIR,
            should_run_web_search(),
            "联网搜索未启用，当前不做外部检索连通性检查",
        )
    )
    results.append(
        run_optional_check(
            "railway_mcp_ping",
            [str(python_exe), "-m", "app.scripts.check_railway_mcp"],
            BACKEND_DIR,
            should_run_railway_live(),
            "12306 MCP live 未开启，当前不做真实 MCP 连通性检查",
        )
    )

    print_step("")
    print_step("TripSage 交付巡检摘要")
    failed = 0
    for item in results:
        print_step(f"- [{item.status}] {item.name}: {item.detail}")
        if item.status == "FAIL":
            failed += 1

    print_step("")
    if failed:
        print_step(f"交付巡检未通过，共 {failed} 项失败。")
        return 1

    print_step("交付巡检通过。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
