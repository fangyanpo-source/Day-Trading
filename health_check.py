# 檔案名稱: health_check.py
"""
========================================
  風林火山系統 - 啟動前健康檢查工具
  執行方式: python health_check.py
========================================
"""

import sys
import os
import socket
import importlib

PASS = "  ✅"
FAIL = "  ❌"
WARN = "  ⚠️"

print("=" * 50)
print("  風林火山系統 - 啟動前健康檢查")
print("=" * 50)

all_ok = True

# ==========================================
# 1. 套件檢查
# ==========================================
print("\n【1】必要套件檢查")
required_packages = {
    "redis":        "pip install redis",
    "yfinance":     "pip install yfinance",
    "pandas":       "pip install pandas",
    "requests":     "pip install requests",
    "dotenv":       "pip install python-dotenv",
    "pytz":         "pip install pytz",
    "plotly":       "pip install plotly",
    "streamlit":    "pip install streamlit",
    "numpy":        "pip install numpy",
    "matplotlib":   "pip install matplotlib",
}
optional_packages = {
    "fubon_neo":    "請至富邦官方取得 SDK 並安裝",
}

missing = []
for pkg, install_cmd in required_packages.items():
    try:
        importlib.import_module(pkg)
        print(f"{PASS} {pkg}")
    except ImportError:
        print(f"{FAIL} {pkg}  →  {install_cmd}")
        missing.append(install_cmd)
        all_ok = False

for pkg, note in optional_packages.items():
    try:
        importlib.import_module(pkg)
        print(f"{PASS} {pkg} (富邦 SDK)")
    except ImportError:
        print(f"{WARN} {pkg} (選用) → {note}")

if missing:
    print(f"\n  💡 一鍵安裝所有缺少套件：")
    pkgs = " ".join([c.replace("pip install ", "") for c in missing])
    print(f"     pip install {pkgs}")

# ==========================================
# 2. Redis / Memurai 連線檢查
# ==========================================
print("\n【2】Redis / Memurai 連線檢查")
try:
    s = socket.create_connection(("127.0.0.1", 6379), timeout=2)
    s.close()
    print(f"{PASS} Redis/Memurai 正在運行 (127.0.0.1:6379)")

    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_timeout=2)
        r.ping()
        print(f"{PASS} Redis PING 回應正常")
    except Exception as e:
        print(f"{FAIL} Redis PING 失敗: {e}")
        all_ok = False

except (socket.timeout, ConnectionRefusedError, OSError):
    print(f"{FAIL} Redis/Memurai 未啟動！")
    print(f"       Windows → 請啟動 Memurai 服務")
    print(f"       Linux/Mac → 請執行 redis-server")
    all_ok = False

# ==========================================
# 3. .env 環境變數檢查
# ==========================================
print("\n【3】.env 環境變數檢查")
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

env_vars = {
    "TRADE_MODE":       ("必填", "PAPER"),
    "TOTAL_CAPITAL":    ("必填", "1000000"),
    "FUBON_ID":         ("實盤必填", None),
    "FUBON_PASSWORD":   ("實盤必填", None),
    "FUBON_CERT_PATH":  ("實盤必填", None),
    "FUBON_CERT_PASS":  ("實盤必填", None),
    "TG_BOT_TOKEN":     ("選填", None),
    "TG_CHAT_ID":       ("選填", None),
}

trade_mode = os.getenv("TRADE_MODE", "PAPER").upper()
print(f"  📌 目前交易模式: {trade_mode}")

for var, (required_level, default) in env_vars.items():
    val = os.getenv(var)
    if val:
        # 遮蔽敏感資訊
        display = val[:3] + "***" if len(val) > 3 else "***"
        print(f"{PASS} {var} = {display}")
    elif default:
        print(f"{WARN} {var} 未設定，將使用預設值: {default}")
    elif required_level == "必填":
        print(f"{FAIL} {var} 未設定！({required_level})")
        all_ok = False
    elif required_level == "實盤必填" and trade_mode == "LIVE":
        print(f"{FAIL} {var} 未設定！(實盤模式下為必填)")
        all_ok = False
    else:
        print(f"{WARN} {var} 未設定 ({required_level}，模擬模式可略過)")

# ==========================================
# 4. 必要 Python 檔案存在檢查
# ==========================================
print("\n【4】系統模組檔案檢查")
required_files = [
    "redis_manager.py",
    "backtest_engine.py",
    "realtime_strategy_engine.py",
    "fubon_websocket_engine.py",
    "system_monitor_advanced.py",
    "auto_stock_pool.py",
    "strategy_chips_turnover.py",
    "streamlit_app.py",
]
for fname in required_files:
    if os.path.exists(fname):
        print(f"{PASS} {fname}")
    else:
        print(f"{FAIL} {fname} 不存在！")
        all_ok = False

# ==========================================
# 5. 資料庫初始化檢查
# ==========================================
print("\n【5】SQLite 資料庫檢查")
import sqlite3
db_path = "trading_data.db"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_kbars (
            stock_id TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            UNIQUE(stock_id, date)
        )
    """)
    conn.commit()
    conn.close()
    print(f"{PASS} {db_path} 正常（資料表已確認）")
except Exception as e:
    print(f"{FAIL} 資料庫初始化失敗: {e}")
    all_ok = False

# ==========================================
# 6. 目錄結構檢查
# ==========================================
print("\n【6】必要目錄檢查")
required_dirs = ["logs", "watchlists"]
for d in required_dirs:
    if not os.path.exists(d):
        os.makedirs(d)
        print(f"{WARN} {d}/ 不存在，已自動建立")
    else:
        print(f"{PASS} {d}/")

# ==========================================
# 最終結果
# ==========================================
print("\n" + "=" * 50)
if all_ok:
    print("🎉 所有檢查通過！系統可以啟動。")
    print("\n啟動順序（各開一個終端機）：")
    print("  1. python auto_stock_pool.py")
    print("  2. python fubon_websocket_engine.py")
    print("  3. python realtime_strategy_engine.py")
    print("  4. python system_monitor_advanced.py")
    print("  5. streamlit run streamlit_app.py")
else:
    print("⚠️  有項目未通過，請先修正上方 ❌ 的問題再啟動系統！")
print("=" * 50)
