# fubon_websocket_engine.py
import os
import json
import time
import logging
from dotenv import load_dotenv
from fubon_neo.sdk import FubonSDK, Mode
from redis_manager import redis_db

# 載入 .env 檔案中的環境變數
load_dotenv()

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class FubonMarketDataEngine:
    def __init__(self):
        fubon_id   = os.getenv("FUBON_ID")
        fubon_pass = os.getenv("FUBON_PASSWORD")
        cert_path  = os.getenv("FUBON_CERT_PATH")
        cert_pass  = os.getenv("FUBON_CERT_PASS")

        self.subscribed_symbols = set()
        self.is_running = True

        # 富邦單一連線上限為 200 個 Channel。
        # 每檔股票訂閱 2 個 Channel (trades + books)
        # 安全上限設為 95 檔 (190 channels)，保留緩衝空間。
        # ⚠️ 此數值須與 auto_stock_pool.py / emergency_data_updater.py 的 MAX_SAFE_STOCKS 保持一致
        self.MAX_SAFE_STOCKS = 95

        try:
            self.sdk = FubonSDK()
            logger.info("登入富邦 API 準備接收行情...")
            self.sdk.login(fubon_id, fubon_pass, cert_path, cert_pass)

            # 初始化即時行情連線（Speed 模式獲得極低延遲）
            self.sdk.init_realtime(Mode.Speed)
            self.ws_stock = self.sdk.marketdata.websocket_client.stock

            # 綁定 WebSocket 事件監聽器
            self.ws_stock.on('connect',    self.on_connect)
            self.ws_stock.on('disconnect', self.on_disconnect)
            self.ws_stock.on('error',      self.on_error)
            self.ws_stock.on('message',    self.on_message)

            logger.info("✅ 行情引擎基礎連線初始化完成！")

        except Exception as e:
            logger.error(f"⚠️ 行情引擎初始化失敗: {e}")
            raise

    # ==========================================
    # WebSocket 事件處理區
    # ==========================================
    def on_connect(self):
        logger.info("🟢 WebSocket 行情伺服器已連線！")

    def on_disconnect(self, message):
        logger.warning(f"🔴 WebSocket 行情伺服器斷線: {message}")
        # ✅ 斷線自動重連（原版只記 log，斷線後行情會永久停滯）
        time.sleep(5)
        if self.is_running:
            try:
                logger.info("🔄 正在嘗試重新連線...")
                self.ws_stock.connect()
                logger.info("🟢 重連成功！")
            except Exception as e:
                logger.error(f"重連失敗，將在下次迴圈繼續嘗試: {e}")

    def on_error(self, error):
        logger.error(f"⚠️ WebSocket 發生錯誤: {error}")

    def on_message(self, message):
        """處理接收到的即時行情訊息，並極速寫入 Redis"""
        try:
            data = json.loads(message)

            if data.get('event') == 'data':
                content = data.get('data', {})
                channel = content.get('channel')
                symbol  = content.get('symbol')

                # 寫入 Redis，供 UI 面板與策略大腦高速讀取
                redis_key = f"market:{channel}:{symbol}"
                redis_db.set_json(redis_key, content)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"處理行情訊息時發生錯誤: {e}")

    # ==========================================
    # 核心升級：動態訂閱控制區 (Hot Reload)
    # ==========================================
    def start(self):
        """啟動連線並進入動態監聽迴圈"""
        logger.info("正在連線至富邦行情伺服器...")
        self.ws_stock.connect()
        time.sleep(2)  # 確保連線建立

        logger.info("📡 行情引擎已啟動，進入【動態監控模式】！(按 Ctrl+C 停止)")

        try:
            while self.is_running:
                # 1. 動態從 Redis 讀取最新的監控清單
                current_pool = redis_db.get_json("system:config:watch_pool")
                if not current_pool:
                    current_pool = ["2330", "2603", "2317"]  # 預設保護清單

                current_set = set(current_pool)

                # ----------------------------------------------------
                # 關鍵順序：必須【先移除舊標的】，再【新增新標的】
                # 避免瞬間訂閱數超過富邦的 200 個 Channel 上限！
                # ----------------------------------------------------

                # 步驟 A: 處理【移除】的訂閱標的，釋放連線資源
                removed_symbols = self.subscribed_symbols - current_set
                for sym in removed_symbols:
                    logger.info(f"➖ 動態取消訂閱: [{sym}]")
                    try:
                        self.ws_stock.unsubscribe({'channel': 'trades', 'symbol': sym})
                        self.ws_stock.unsubscribe({'channel': 'books',  'symbol': sym})
                    except Exception:
                        pass
                    self.subscribed_symbols.remove(sym)

                # 步驟 B: 計算還有多少額度可以新增，保護連線不斷線
                new_symbols    = list(current_set - self.subscribed_symbols)
                available_slots = self.MAX_SAFE_STOCKS - len(self.subscribed_symbols)

                if len(new_symbols) > available_slots:
                    # ✅ 修正點：顯示具體被截斷的股票代碼，方便追查來源
                    dropped_symbols = new_symbols[available_slots:]
                    logger.warning(
                        f"⚠️ 新增標的過多！"
                        f"目前已訂閱 {len(self.subscribed_symbols)} 檔，"
                        f"安全上限 {self.MAX_SAFE_STOCKS} 檔，"
                        f"將截斷以下 {len(dropped_symbols)} 檔: {dropped_symbols}\n"
                        f"💡 請確認 auto_stock_pool.py / emergency_data_updater.py "
                        f"的 MAX_SAFE_STOCKS 已設定為 {self.MAX_SAFE_STOCKS}。"
                    )
                    new_symbols = new_symbols[:available_slots]

                # 步驟 C: 處理【新增】的訂閱標的
                for sym in new_symbols:
                    logger.info(f"➕ 動態新增訂閱: [{sym}] 逐筆成交與五檔")
                    self.ws_stock.subscribe({'channel': 'trades', 'symbol': sym})
                    self.ws_stock.subscribe({'channel': 'books',  'symbol': sym})
                    self.subscribed_symbols.add(sym)

                # 每 3 秒檢查一次 Redis 是否有變動
                time.sleep(3)

        except KeyboardInterrupt:
            logger.info("收到中斷指令，正在安全關閉行情引擎...")
            self.is_running = False
            self.ws_stock.disconnect()


if __name__ == "__main__":
    engine = FubonMarketDataEngine()
    engine.start()