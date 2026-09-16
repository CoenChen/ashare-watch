"""守护启动脚本的格式约束。

每条规则都来自真实故障，不是假想的洁癖：

1. **CRLF 换行。** cmd.exe 解析 LF 换行的批处理时，多行 ``if (...)`` 块会出错
   并直接退出，表现为「双击后窗口一闪而过」。
2. **纯 ASCII。** cmd.exe 按固定字节块读取 .bat，多字节中文字符跨块边界时
   会被错误切分，把后半句当成命令去执行。所以所有中文提示都交给 Python 输出。
3. **不能只靠 ``where python``。** Windows 自带一个假的 python.exe
   （App Execution Alias），存在于 PATH 上、``where`` 能找到，但运行它只会
   弹出微软商店并以 9009 退出。唯一可靠的判断是**真的执行一次**。
4. **结尾必须有 pause**，否则出错时窗口仍然会闪掉。

把规则写成测试比写在文档里可靠——文档没人看，测试会拦住你。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "start.bat"


def test_launcher_exists():
    assert LAUNCHER.exists(), "缺少 start.bat"


def test_launcher_uses_crlf_line_endings():
    raw = LAUNCHER.read_bytes()
    assert b"\r\n" in raw, "start.bat 必须使用 CRLF 换行"
    lone_lf = raw.replace(b"\r\n", b"").count(b"\n")
    assert lone_lf == 0, f"start.bat 存在 {lone_lf} 处纯 LF 换行，cmd.exe 会解析异常"


def test_launcher_is_pure_ascii():
    bad: list[tuple[int, str]] = []
    for lineno, line in enumerate(LAUNCHER.read_text(encoding="utf-8").splitlines(), 1):
        for char in line:
            if ord(char) > 127:
                bad.append((lineno, char))
    assert not bad, f"start.bat 含非 ASCII 字符，cmd.exe 可能解析失败：{bad[:5]}"


def test_launcher_avoids_multiline_if_blocks():
    for line in LAUNCHER.read_text(encoding="utf-8").splitlines():
        assert not line.strip().lower().endswith("("), f"发现多行 if 块：{line!r}"


def test_launcher_verifies_python_candidates_by_running_them():
    content = LAUNCHER.read_text(encoding="utf-8")
    assert ":probe" in content, "缺少 :probe 子过程"
    assert "call :probe" in content, "没有调用 :probe 去验证候选"
    assert "where python" in content, "应遍历 PATH 上的所有 python.exe"
    assert '-c "import sys"' in content, "没有真正执行候选解释器来验证"
    assert 'set "PYEXE=python"' not in content, "不应无条件信任 PATH 上的 python"


def test_launcher_covers_common_install_locations():
    content = LAUNCHER.read_text(encoding="utf-8")
    for hint in ("anaconda3", "miniconda3", "call :probe py"):
        assert hint in content, f"缺少兜底探测：{hint}"


def test_launcher_ends_with_pause():
    assert "\npause" in LAUNCHER.read_text(encoding="utf-8").lower()


def test_gitattributes_pins_bat_to_crlf():
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in attributes


def test_gitignore_excludes_runtime_data():
    ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/*" in ignore, "运行期数据必须一开始就排除，避免误提交"

