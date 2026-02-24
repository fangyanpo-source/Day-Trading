# 檔案名稱: redis_manager.py
import redis
import json
import logging

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RedisManager")

class RedisManager:
    """
    統一管理 Redis/Memurai 連線的控制中心。
    負責：
    1. 與背景 Memurai 伺服器進行握手通訊
    2. 處理資料型別轉換 (Dict/List <-> JSON字串)
    3. 若伺服器未開啟，自動無縫降級為單機虛擬記憶體，保證系統不崩潰
    """
    def __init__(self, host='127.0.0.1', port=6379, db=0):
        self.is_connected = False
        self.fallback_cache = {}  # 備援用的單機虛擬記憶體
        self.client = None
        
        try:
            # decode_responses=True 讓 Redis 直接回傳 Python 字串，不用手動 decode
            self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True, socket_timeout=2)
            # 測試連線 (這會對 Memurai 送出 PING)
            self.client.ping()
            self.is_connected = True
            logger.info("✅ 成功連線至 Redis / Memurai 伺服器！戰情室資料將可即時同步。")
        except redis.ConnectionError:
            logger.warning("⚠️ 無法連線至 Redis 伺服器 (Memurai可能未啟動)。系統將降級為『單機虛擬記憶體備援模式』。")
        except Exception as e:
            logger.error(f"❌ Redis 初始化發生未知的錯誤: {e}")

    def set_json(self, key, value, expire_sec=None):
        """
        將 Python 的 List 或 Dict 寫入 Redis (自動轉 JSON)
        【修正】新增 expire_sec 參數，支援設定 TTL 過期時間
        """
        try:
            json_str = json.dumps(value, ensure_ascii=False)
            if self.is_connected:
                self.client.set(key, json_str)
                # 【修正】若有指定過期秒數，則設定 TTL
                if expire_sec is not None:
                    self.client.expire(key, expire_sec)
            else:
                self.fallback_cache[key] = json_str
        except Exception as e:
            logger.error(f"Redis 寫入 JSON 失敗 [{key}]: {e}")

    def get_json(self, key, default=None):
        """從 Redis 讀取 JSON 並自動轉回 Python List 或 Dict"""
        try:
            if self.is_connected:
                data = self.client.get(key)
            else:
                data = self.fallback_cache.get(key)
                
            if data:
                return json.loads(data)
            return default
        except Exception as e:
            logger.error(f"Redis 讀取 JSON 失敗 [{key}]: {e}")
            return default

    def set_flag(self, key, value, expire_sec=None):
        """
        寫入簡單的字串或數值標籤
        【修正】新增 expire_sec 參數，支援設定 TTL 過期時間
        """
        try:
            if self.is_connected:
                self.client.set(key, str(value))
                # 【修正】若有指定過期秒數，則設定 TTL
                if expire_sec is not None:
                    self.client.expire(key, expire_sec)
            else:
                self.fallback_cache[key] = str(value)
        except Exception as e:
            logger.error(f"Redis 寫入 Flag 失敗 [{key}]: {e}")

    def get_flag(self, key, default=None):
        """讀取簡單的字串或數值標籤"""
        try:
            if self.is_connected:
                data = self.client.get(key)
            else:
                data = self.fallback_cache.get(key)
                
            return data if data is not None else default
        except Exception as e:
            logger.error(f"Redis 讀取 Flag 失敗 [{key}]: {e}")
            return default

    def delete_flag(self, key):
        """
        【修正】新增 delete_flag 方法，刪除指定的 Key
        原本遺漏此方法，導致多個模組呼叫時產生 AttributeError
        """
        try:
            if self.is_connected:
                self.client.delete(key)
            else:
                self.fallback_cache.pop(key, None)
        except Exception as e:
            logger.error(f"Redis 刪除 Flag 失敗 [{key}]: {e}")

# 實例化一個全域物件供其他所有模組 (如 streamlit_app.py) 共同匯入使用
# 寫法範例: from redis_manager import redis_db
redis_db = RedisManager()