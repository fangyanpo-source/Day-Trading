# launch_system.py
"""
風林火山量化戰情室 — 一鍵啟動器
====================================
執行方式：
    python launch_system.py            # 完整啟動（所有服務）
    python launch_system.py --no-ui    # 不啟動 Streamlit（純後台模式）
    python launch_system.py --init     # 僅執行盤前初始化（選股池 + K 線更新）後退出
"""

import subprocess
import sys
import os
import time
import signal
import argparse
import logging
from datetime import datetime
from pathlib import Path

# ── 日誌設定 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Launcher")

# ── 全域進程表（用於關閉時統一清理） ──────────────────────
_processes: dict[str, subprocess.Popen] = {}

# ── 顏色輸出（Windows 需要 colorama，Linux/Mac 原生支援） ──
try:
    import colorama; colorama.init()
    GREEN  = "\033[92m"; YELLOW = "\033[93m"
    RED    = "\033[91m"; CYAN   = "\033[96m"; RESET = "\033[0m"
except ImportError:
    GREEN = YELLOW = RED = CYAN = RESET = ""


# =============================================================
# 服務定義表
# =============================================================
# 每個服務的設定：
#   cmd          : 實際執行的命令（list）
#   label        : 顯示用中文名稱
#   delay_after  : 啟動後等待幾秒讓服務就緒
#   critical     : True = 若啟動失敗則中止整個啟動流程
#   restart      : True = 進程意外終止時自動重啟（需搭配 watchdog 迴圈）
#   init_only    : True = 只在 --init 模式執行，執行完後自動結束

SERVICES = [
    {
        "key":        "init_pool",
        "label":      "📊 盤前選股池更新 (auto_stock_pool)",
        "cmd":        [sys.executable, "auto_stock_pool.py"],
        "delay_after": 3,
        "critical":   False,
        "restart":    False,
        "init_only":  True,
    },
    {
        "key":        "init_kbar",
        "label":      "🗃️  盤前 K 線補齊 (emergency_data_updater)",
        "cmd":        [sys.executable, "emergency_data_updater.py"],
        "delay_after": 5,
        "critical":   False,
        "restart":    False,
        "init_only":  True,
    },
    {
        "key":        "websocket",
        "label":      "📡 富邦行情 WebSocket 引擎 (fubon_websocket_engine)",
        "cmd":        [sys.executable, "fubon_websocket_engine.py"],
        "delay_after": 4,
        "critical":   True,
        "restart":    True,
        "init_only":  False,
    },
    {
        "key":        "strategy",
        "label":      "🧠 即時策略大腦 (realtime_strategy_engine)",
        "cmd":        [sys.executable, "realtime_strategy_engine.py"],
        "delay_after": 2,
        "critical":   True,
        "restart":    True,
        "init_only":  False,
    },
    {
        "key":        "streamlit",
        "label":      "🖥️  Streamlit 戰情室面板 (streamlit_app)",
        "cmd":        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py",
                       "--server.port", "8501", "--server.headless", "true"],
        "delay_after": 3,
        "critical":   False,
        "restart":    True,
        "init_only":  False,
    },
]


# =============================================================
# 核心工具函式
# =============================================================

def _log(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    color = {"info": GREEN, "warn": YELLOW, "error": RED, "head": CYAN}.get(level, RESET)
    print(f"{color}[{ts}] {msg}{RESET}", flush=True)


def _start_service(svc: dict) -> subprocess.Popen | None:
    """啟動單一服務，回傳 Popen 物件；失敗回傳 None。"""
    _log(f"▶  啟動中：{svc['label']}", "info")
    try:
        proc = subprocess.Popen(
            svc["cmd"],
            stdout=None,   # 直接輸出至終端，方便即時檢視 log
            stderr=None,
            cwd=str(Path(__file__).parent),
            creationflags=0,  # Windows 上可改為 subprocess.CREATE_NEW_CONSOLE
        )
        _log(f"✅ 已啟動 PID={proc.pid}：{svc['label']}", "info")
        return proc
    except FileNotFoundError as e:
        _log(f"❌ 找不到啟動檔案：{e}（請確認工作目錄正確）", "error")
        return None
    except Exception as e:
        _log(f"❌ 啟動失敗 [{svc['label']}]：{e}", "error")
        return None


def _shutdown_all(signum=None, frame=None):
    """收到 Ctrl+C 或 SIGTERM 時，依序關閉所有子進程。"""
    _log("\n🛑  收到中斷信號，正在安全關閉所有服務...", "warn")
    # 反序關閉：先關 Streamlit → 策略大腦 → WebSocket 引擎
    for key in reversed(list(_processes.keys())):
        proc = _processes[key]
        if proc and proc.poll() is None:
            _log(f"   ➖ 關閉 {key} (PID={proc.pid})", "warn")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass
    _log("✅ 所有服務已關閉。", "info")
    sys.exit(0)


# =============================================================
# 啟動流程
# =============================================================

def run_init_only():
    """只執行盤前初始化任務後退出。"""
    _log("═" * 55, "head")
    _log("  📋  盤前初始化模式 (--init)", "head")
    _log("═" * 55, "head")

    for svc in [s for s in SERVICES if s["init_only"]]:
        proc = _start_service(svc)
        if proc:
            _log(f"   ⏳ 等待完成（最多 60 秒）...", "info")
            try:
                proc.wait(timeout=60)
                rc = proc.returncode
                if rc == 0:
                    _log(f"   ✅ {svc['label']} 執行完成。", "info")
                else:
                    _log(f"   ⚠️  {svc['label']} 結束碼={rc}，請確認輸出。", "warn")
            except subprocess.TimeoutExpired:
                _log(f"   ⚠️  {svc['label']} 超過 60 秒，強制結束。", "warn")
                proc.kill()

    _log("✅ 盤前初始化完成！", "info")


def run_full(enable_ui: bool = True):
    """完整啟動所有後台服務。"""
    # 註冊中斷信號
    signal.signal(signal.SIGINT,  _shutdown_all)
    signal.signal(signal.SIGTERM, _shutdown_all)

    _log("═" * 55, "head")
    _log("  🚀  風林火山量化戰情室 — 完整啟動", "head")
    _log(f"  📁  工作目錄: {Path.cwd()}", "head")
    _log("═" * 55, "head")

    # ── 步驟 1：盤前初始化（同步執行，不進入重啟監控） ──
    _log("\n[第一階段] 盤前資料初始化...", "head")
    for svc in [s for s in SERVICES if s["init_only"]]:
        proc = _start_service(svc)
        if proc:
            _log(f"   ⏳ 等待 {svc['label']} 完成...", "info")
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                _log(f"   ⚠️  超時，繼續後續啟動。", "warn")
                proc.kill()
        time.sleep(svc.get("delay_after", 2))

    # ── 步驟 2：啟動長期運行的後台服務 ──
    _log("\n[第二階段] 啟動後台服務...", "head")
    for svc in [s for s in SERVICES if not s["init_only"]]:
        if svc["key"] == "streamlit" and not enable_ui:
            _log(f"⏭️  跳過（--no-ui 模式）：{svc['label']}", "warn")
            continue

        proc = _start_service(svc)
        if proc is None and svc["critical"]:
            _log(f"💥 關鍵服務啟動失敗，中止！", "error")
            _shutdown_all()
            return

        if proc:
            _processes[svc["key"]] = proc

        time.sleep(svc.get("delay_after", 2))

    # ── 步驟 3：狀態摘要 ──
    _log("\n[啟動完成] 服務狀態摘要", "head")
    _log("─" * 55, "head")
    for key, proc in _processes.items():
        status = f"🟢 執行中 PID={proc.pid}" if proc.poll() is None else f"🔴 已停止 (RC={proc.returncode})"
        _log(f"  {key:<18} {status}", "info")
    if enable_ui:
        _log("\n  🌐 Streamlit 面板：http://localhost:8501", "head")
    _log("─" * 55, "head")
    _log("  按 Ctrl+C 安全關閉所有服務", "warn")
    _log("═" * 55, "head")

    # ── 步驟 4：Watchdog 監控迴圈（自動重啟崩潰的進程） ──
    _watchdog_loop()


def _watchdog_loop():
    """持續監控各服務，若意外終止則自動重啟。"""
    restart_counts: dict[str, int] = {}
    RESTART_LIMIT = 5       # 同一服務最多自動重啟 5 次
    COOLDOWN_SEC  = 10      # 重啟前等待秒數（避免瘋狂重啟）

    service_map = {s["key"]: s for s in SERVICES if not s["init_only"]}

    while True:
        time.sleep(5)  # 每 5 秒巡邏一次

        for key, proc in list(_processes.items()):
            if proc.poll() is None:
                continue  # 正常運行中

            svc = service_map.get(key)
            if not svc or not svc.get("restart", False):
                continue

            count = restart_counts.get(key, 0)
            if count >= RESTART_LIMIT:
                _log(f"🚨 [{key}] 已重啟 {count} 次，超過上限，請手動檢查！", "error")
                continue

            _log(f"⚠️  [{key}] 進程意外終止（RC={proc.returncode}），"
                 f"{COOLDOWN_SEC} 秒後自動重啟（{count + 1}/{RESTART_LIMIT}）...", "warn")
            time.sleep(COOLDOWN_SEC)

            new_proc = _start_service(svc)
            if new_proc:
                _processes[key] = new_proc
                restart_counts[key] = count + 1
            else:
                _log(f"❌ [{key}] 重啟失敗！", "error")


# =============================================================
# 入口
# =============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="風林火山量化戰情室 一鍵啟動器"
    )
    parser.add_argument(
        "--no-ui", action="store_true",
        help="不啟動 Streamlit 面板（純後台模式）"
    )
    parser.add_argument(
        "--init", action="store_true",
        help="只執行盤前初始化（選股池 + K 線更新）後退出"
    )
    args = parser.parse_args()

    # 確認工作目錄為本檔案所在資料夾，避免找不到其他 .py
    os.chdir(Path(__file__).parent)

    if args.init:
        run_init_only()
    else:
        run_full(enable_ui=not args.no_ui)
