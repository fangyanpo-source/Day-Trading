# system_monitor_advanced.py
import os
import time
import logging
import asyncio
import functools
import requests
from datetime import datetime
import pytz
from dotenv import load_dotenv

from redis_manager import redis_db
from fubon_async_order_manager import FubonAsyncOrderManager

load_dotenv()

# ✅ 交易模式從環境變數讀取，與其他模組保持一致
TRADE_MODE = os.getenv("TRADE_MODE", "PAPER").upper()
PAPER_TRADE_MODE = (TRADE_MODE != "LIVE")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def send_telegram_notify(message: str):
    # ✅ 統一使用 TG_BOT_TOKEN / TG_CHAT_ID（與 .env 及 realtime_strategy_engine 一致）
    tg_token   = os.getenv("TG_BOT_TOKEN", "")
    tg_chat_id = os.getenv("TG_CHAT_ID", "")
    if not tg_token or not tg_chat_id:
        return
    url     = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id":    tg_chat_id,
        "text":       f"🚀 【風林火山系統通知】\n{message}",
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        logger.error(f"Telegram 傳送失敗: {e}")


def handle_exceptions(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exp:
            logger.error(f"🚨 異常: {exp}")
    return wrapper


class SystemMonitorAdvanced:
    def __init__(self):
        self.is_running        = True
        self.SCREENER_FLAG_KEY = "system:flag:screener_updated"
        self.WATCHLIST_KEY     = "system:data:daily_watchlist"
        self.KILL_SWITCH_KEY   = "system:flag:kill_switch"
        self.current_watchlist = {}

        # ✅ MAX_DAILY_LOSS 從環境變數讀取，與 realtime_strategy_engine 保持一致
        # 原本寫死 -10000，與 .env 的 -20000 不同，導致熔斷行為矛盾
        self.MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", -20000))

        # 每日狀態追蹤（用於跨日自動重置 kill_switch）
        self._last_trade_date: str = ""

        fubon_id   = os.getenv("FUBON_ID")
        fubon_pass = os.getenv("FUBON_PASSWORD")
        cert_path  = os.getenv("FUBON_CERT_PATH")
        cert_pass  = os.getenv("FUBON_CERT_PASS")

        # 實盤模式：Fail-fast，缺少必要環境變數時立即報錯
        if not PAPER_TRADE_MODE:
            missing = [v for v in ["FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASS"]
                       if not os.getenv(v)]
            if missing:
                raise EnvironmentError(f"🚨 實盤模式缺少環境變數: {missing}")

        try:
            self.order_manager = FubonAsyncOrderManager(
                id_no=fubon_id, password=fubon_pass,
                cert_path=cert_path, cert_pass=cert_pass
            )
            self.order_manager.sdk.set_on_order(self.on_order_callback)
            self.order_manager.sdk.set_on_filled(self.on_filled_callback)

            mode_msg = "🟢 【模擬交易模式】啟動" if PAPER_TRADE_MODE else "🔴 【實盤交易模式】啟動，真金白銀！"
            logger.warning(mode_msg)
            send_telegram_notify(f"系統已連線！\n狀態：{mode_msg}")

        except Exception as e:
            logger.error(f"❌ 系統啟動失敗: {e}")
            send_telegram_notify("❌ 系統啟動失敗 (API登入異常)")
            raise SystemExit("無法連線至券商。")

    # =========================================================
    # 每日狀態管理
    # =========================================================
    def _get_trade_date(self) -> str:
        """取得今日交易日日期字串，08:59 前歸屬前一個自然日。"""
        from datetime import timedelta
        tz  = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz)
        if now.hour < 9:
            now = now - timedelta(days=1)
        return now.strftime('%Y-%m-%d')

    def _check_and_reset_daily_state(self):
        """
        每次迴圈比對交易日，日期改變時重置 kill_switch 等每日狀態。
        ✅ 修正點：原版不會跨日清除 kill_switch，隔天系統啟動後永遠被熔斷鎖定。
        """
        today_str = self._get_trade_date()
        if today_str != self._last_trade_date:
            if self._last_trade_date:
                logger.info("🌅 偵測到新交易日，重置每日熔斷狀態。")
                redis_db.delete_flag(self.KILL_SWITCH_KEY)
            self._last_trade_date = today_str

    # =========================================================
    # WebSocket 回呼
    # =========================================================
    @handle_exceptions
    def on_order_callback(self, err, content):
        if err:
            return
        logger.info(f"📨 [委託回報] {content}")

    @handle_exceptions
    def on_filled_callback(self, err, content):
        if err:
            return
        symbol = getattr(content, 'symbol', '未知')
        price  = getattr(content, 'price',  0)
        qty    = getattr(content, 'qty',    0)

        logger.info(f"💰 [成交回報！] 標的: {symbol}, 價格: {price}, 數量: {qty}")
        send_telegram_notify(
            f"💰 <b>成交回報</b>\n標的：{symbol}\n價格：{price}\n數量：{qty} 股"
        )
        fill_data = {
            "symbol": symbol, "price": float(price),
            "qty": int(qty),  "timestamp": time.time()
        }
        redis_db.set_json(f"system:data:fill_{int(time.time()*1000)}", fill_data)

    # =========================================================
    # 風控核心
    # =========================================================
    def is_kill_switch_active(self) -> bool:
        return redis_db.get_flag(self.KILL_SWITCH_KEY) == "1"

    def check_risk_limits(self):
        """
        讀取策略大腦寫入的累計損益，超過每日上限時觸發熔斷。
        熔斷邏輯與 realtime_strategy_engine 共用同一個 Redis key，確保兩邊同步。
        """
        mock_pnl_str = redis_db.get_flag("system:mock:pnl")
        if not mock_pnl_str:
            return
        try:
            current_pnl = float(mock_pnl_str)
        except ValueError:
            return

        if current_pnl <= self.MAX_DAILY_LOSS and not self.is_kill_switch_active():
            logger.error(
                f"🚨🚨🚨 【全局熔斷觸發】當日虧損達 {current_pnl:.0f}，"
                f"上限 {self.MAX_DAILY_LOSS:.0f}"
            )
            # ✅ 寫入 Redis kill_switch，讓 realtime_strategy_engine 與 Streamlit 同步感知
            redis_db.set_flag(self.KILL_SWITCH_KEY, "1", expire_sec=86400)
            send_telegram_notify(
                f"🚨🚨🚨 <b>全局熔斷觸發</b>\n"
                f"當日虧損達 {current_pnl:.0f} 元\n"
                f"系統已鎖定所有新委託！"
            )

    # =========================================================
    # 下單執行
    # =========================================================
    def process_and_fire_orders(self):
        basket_orders = []

        for stock_code, details in self.current_watchlist.items():
            action = details.get('action', 'BUY')
            price  = details.get('target_price', 0)
            qty    = details.get('qty', 1000)

            if PAPER_TRADE_MODE:
                logger.info(f"🎮 [模擬單] {stock_code} {action} {qty}股 @ {price}")
                fill_data = {
                    "symbol": stock_code, "price": float(price),
                    "qty": qty, "timestamp": time.time(), "type": "模擬"
                }
                redis_db.set_json(
                    f"system:data:fill_{int(time.time()*1000)}", fill_data
                )
                send_telegram_notify(
                    f"🎮 <b>模擬成交</b>\n標的：{stock_code}\n"
                    f"方向：{action}\n價格：{price}\n數量：{qty} 股"
                )
                continue

            basket_orders.append({
                "stock_code": stock_code,
                "action":     action,
                "price":      price,
                "qty":        qty
            })

        if basket_orders and not PAPER_TRADE_MODE:
            asyncio.run(self.order_manager.execute_basket_orders(basket_orders))

    # =========================================================
    # 主監控迴圈
    # =========================================================
    def run(self):
        logger.info(f"🔔 系統監控下單模組啟動（{TRADE_MODE} 模式）")

        while self.is_running:
            try:
                # ✅ 每次迴圈檢查是否跨日，需要重置熔斷狀態
                self._check_and_reset_daily_state()

                # 風控：檢查是否超過每日虧損上限
                self.check_risk_limits()

                # 偵測策略大腦發出的下單旗標
                if redis_db.get_flag(self.SCREENER_FLAG_KEY) == "1":
                    # 若已熔斷，清除旗標後跳過，不執行下單
                    if self.is_kill_switch_active():
                        logger.warning("⚠️ kill_switch 已啟動，忽略此次下單訊號。")
                        redis_db.delete_flag(self.SCREENER_FLAG_KEY)
                        time.sleep(0.2)
                        continue

                    watchlist_data = redis_db.get_json(self.WATCHLIST_KEY)
                    if watchlist_data:
                        self.current_watchlist = watchlist_data
                        self.process_and_fire_orders()

                    redis_db.delete_flag(self.SCREENER_FLAG_KEY)

                time.sleep(0.2)

            except KeyboardInterrupt:
                self.is_running = False
            except Exception as e:
                logger.error(f"監控迴圈發生錯誤: {e}")
                time.sleep(1)

        logger.info("🛑 系統監控下單模組已關閉。")


if __name__ == "__main__":
    monitor = SystemMonitorAdvanced()
    monitor.run()