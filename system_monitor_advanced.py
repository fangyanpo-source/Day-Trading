# 檔案名稱: system_monitor_advanced.py
import os
import time
import logging
import traceback
import asyncio
import functools
import requests
from dotenv import load_dotenv

from redis_manager import redis_db
from fubon_async_order_manager import FubonAsyncOrderManager

load_dotenv()
PAPER_TRADE_MODE = True

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S.%f'[:-3])
logger = logging.getLogger(__name__)

# =========================================================
# 🌟 升級 3：Telegram 即時推播功能
# ==========================================
def send_telegram_notify(message):
    tg_token = os.getenv("TG_BOT_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    if not tg_token or not tg_chat_id:
        return # 若未設定則略過
    
    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": tg_chat_id,
        "text": f"🚀 【風林火山系統通知】\n{message}",
        "parse_mode": "HTML"
    }
    try:
        # 使用背景發送，避免卡住主程式
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        logger.error(f"Telegram 傳送失敗: {e}")

def handle_exceptions(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try: return func(*args, **kwargs)
        except Exception as exp: logger.error(f"🚨 異常: {exp}")
    return wrapper

class SystemMonitorAdvanced:
    def __init__(self):
        self.is_running = True
        self.SCREENER_FLAG_KEY = "system:flag:screener_updated"
        self.WATCHLIST_KEY = "system:data:daily_watchlist"
        self.KILL_SWITCH_KEY = "system:flag:kill_switch"
        self.MAX_DAILY_LOSS = -10000 
        self.current_watchlist = {}
        
        fubon_id = os.getenv("FUBON_ID")
        fubon_pass = os.getenv("FUBON_PASSWORD")
        cert_path = os.getenv("FUBON_CERT_PATH")
        cert_pass = os.getenv("FUBON_CERT_PASS")
        
        try:
            self.order_manager = FubonAsyncOrderManager(id_no=fubon_id, password=fubon_pass, cert_path=cert_path, cert_pass=cert_pass)
            self.order_manager.sdk.set_on_order(self.on_order_callback)
            self.order_manager.sdk.set_on_filled(self.on_filled_callback)
            
            mode_msg = "🟢 【模擬交易模式】啟動" if PAPER_TRADE_MODE else "🔴 【實盤交易模式】啟動，真金白銀！"
            logger.warning(mode_msg)
            send_telegram_notify(f"系統已連線！\n狀態：{mode_msg}")
            
        except Exception as e:
            send_telegram_notify("❌ 系統啟動失敗 (API登入異常)")
            raise SystemExit("無法連線至券商。")

    @handle_exceptions
    def on_order_callback(self, err, content):
        if err: return
        logger.info(f"📨 [委託回報] {content}")

    @handle_exceptions
    def on_filled_callback(self, err, content):
        if err: return
        symbol = getattr(content, 'symbol', '未知')
        price = getattr(content, 'price', 0)
        qty = getattr(content, 'qty', 0)
        
        logger.info(f"💰 [成交回報！] 標的: {symbol}, 價格: {price}, 數量: {qty}")
        send_telegram_notify(f"💰 <b>成交回報</b>\n標的：{symbol}\n價格：{price}\n數量：{qty} 股")
        
        fill_data = {"symbol": symbol, "price": float(price), "qty": int(qty), "timestamp": time.time()}
        redis_db.set_json(f"system:data:fill_{int(time.time()*1000)}", fill_data)

    def is_kill_switch_active(self):
        return redis_db.get_flag(self.KILL_SWITCH_KEY) == "1"

    def check_risk_limits(self):
        mock_current_pnl = redis_db.get_flag("system:mock:pnl")
        if not mock_current_pnl: return
        current_pnl = float(mock_current_pnl)
        if current_pnl <= self.MAX_DAILY_LOSS and not self.is_kill_switch_active():
            logger.error("🚨🚨🚨 【全局熔斷觸發】")
            redis_db.set_flag(self.KILL_SWITCH_KEY, "1", expire_sec=86400)
            send_telegram_notify(f"🚨🚨🚨 <b>全局熔斷觸發</b>\n當日虧損達 {current_pnl}\n系統已鎖定所有新委託！")

    def process_and_fire_orders(self):
        basket_orders = []
        for stock_code, details in self.current_watchlist.items():
            action = details.get('action', 'BUY')
            price = details.get('target_price', 0)
            
            # 讀取策略大腦算好的動態股數 (預設至少 1000 股)
            qty = details.get('qty', 1000)
            
            if PAPER_TRADE_MODE:
                logger.info(f"🎮 [模擬單] {stock_code} {action} {qty}股 @ {price}")
                fill_data = {"symbol": stock_code, "price": float(price), "qty": qty, "timestamp": time.time(), "type": "模擬"}
                redis_db.set_json(f"system:data:fill_{int(time.time()*1000)}", fill_data)
                
                # 模擬單也發送推播
                send_telegram_notify(f"🎮 <b>模擬成交</b>\n標的：{stock_code}\n方向：{action}\n價格：{price}\n數量：{qty} 股")
                continue
                
            order_info = {
                "stock_code": stock_code,
                "action": action,  
                "price": price, 
                "qty": qty  # 送出動態計算的股數！
            }
            basket_orders.append(order_info)

        if basket_orders and not PAPER_TRADE_MODE:
            asyncio.run(self.order_manager.execute_basket_orders(basket_orders))

    def run(self):
        while self.is_running:
            try:
                self.check_risk_limits()
                if redis_db.get_flag(self.SCREENER_FLAG_KEY) == "1":
                    if self.is_kill_switch_active():
                        redis_db.delete_flag(self.SCREENER_FLAG_KEY)
                        continue
                    watchlist_data = redis_db.get_json(self.WATCHLIST_KEY)
                    if watchlist_data:
                        self.current_watchlist = watchlist_data
                        self.process_and_fire_orders()
                    redis_db.delete_flag(self.SCREENER_FLAG_KEY)
                time.sleep(0.2)
            except KeyboardInterrupt: self.is_running = False
            except Exception: time.sleep(1)

if __name__ == "__main__":
    monitor = SystemMonitorAdvanced()
    monitor.run()