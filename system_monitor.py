import time
import logging
from redis_manager import redis_db # 匯入我們剛剛建立的 Redis 管理器

logger = logging.getLogger(__name__)

class SystemMonitor:
    def __init__(self):
        self.is_running = True
        # 定義 Redis 中使用的 key 名稱
        self.SCREENER_FLAG_KEY = "system:flag:screener_updated"
        self.WATCHLIST_KEY = "system:data:daily_watchlist"

    def check_screener_update(self):
        """檢查選股是否已更新 (原本是讀取 .flag 檔案)"""
        # --- [優化] 改為從 Redis 讀取 flag ---
        flag_status = redis_db.get_flag(self.SCREENER_FLAG_KEY)
        
        if flag_status == "1":
            logger.info("偵測到選股更新通知 (via Redis)")
            
            # 讀取更新後的選股名單 (原本是讀取 daily_watchlist.json)
            # --- [優化] 改為從 Redis 讀取 JSON 資料 ---
            watchlist_data = redis_db.get_json(self.WATCHLIST_KEY)
            
            if watchlist_data:
                logger.info(f"成功從 Redis 載入選股清單，共 {len(watchlist_data)} 筆資料")
                # ... 在這裡執行後續處理邏輯 ...
            else:
                logger.warning("有更新通知，但在 Redis 中找不到選股清單資料！")
            
            # 處理完畢後，清除 flag (原本是刪除 .flag 檔案)
            redis_db.delete_flag(self.SCREENER_FLAG_KEY)
            logger.info("已清除 Redis 中的選股更新旗標")
            return True
            
        return False

    def trigger_mock_update(self):
        """這是一個測試用的方法，模擬選股程式完成並寫入資料"""
        mock_data = {
            "2330": {"name": "台積電", "strategy": "突破"},
            "2603": {"name": "長榮", "strategy": "反彈"}
        }
        
        logger.info("模擬：選股程式執行完成，開始將結果寫入 Redis...")
        # 1. 將選股結果寫入 Redis
        redis_db.set_json(self.WATCHLIST_KEY, mock_data)
        
        # 2. 設定更新旗標，通知監控程式
        redis_db.set_flag(self.SCREENER_FLAG_KEY, "1")
        logger.info("模擬：已寫入資料並設定更新旗標")

    def run(self):
        logger.info("系統監控程式啟動 (Redis 版本)...")
        
        # 為了測試，我們先模擬觸發一次更新
        self.trigger_mock_update()

        while self.is_running:
            self.check_screener_update()
            
            # 實務上這裡可能會有心跳檢查、錯誤處理等邏輯
            # 這裡為了展示，檢查一次後就結束
            self.is_running = False 
            time.sleep(1)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    monitor = SystemMonitor()
    monitor.run()