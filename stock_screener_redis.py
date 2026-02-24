# 檔案名稱: stock_screener_redis.py
import json
import logging
import time
from datetime import datetime
from redis_manager import redis_db  # 確保同目錄下有我們稍早建立的 redis_manager.py

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class StockScreener:
    def __init__(self):
        # 這些 Key 必須與 system_monitor.py 監聽的 Key 完全一致
        self.watchlist_key = "system:data:daily_watchlist"
        self.flag_key = "system:flag:screener_updated"

    def run_screening_logic(self):
        """
        【這區塊是你原有的策略邏輯】
        實務上，你會在這裡透過 data_provider 獲取 K 線、籌碼，然後進行 pandas 運算。
        這裡我們用模擬的假資料來示範。
        """
        logger.info("開始執行盤前/盤中選股運算 (模擬中)...")
        time.sleep(2)  # 模擬運算耗時 2 秒
        
        # 模擬選出的股票清單格式 (Dictionary)
        mock_watchlist = {
            "2330": {"name": "台積電", "strategy": "量價突破", "target_price": 850},
            "2603": {"name": "長榮", "strategy": "均線多頭", "target_price": 180},
            "2317": {"name": "鴻海", "strategy": "外資大買", "target_price": 150}
        }
        
        logger.info(f"選股完成！共選出 {len(mock_watchlist)} 檔標的。")
        return mock_watchlist

    def save_to_redis(self, watchlist_data):
        """
        【核心修改區】
        將選股結果寫入 Redis，徹底取代原本寫入 .json 與 .flag 檔案的動作
        """
        if not watchlist_data:
            logger.warning("選股清單為空，跳過寫入。")
            return

        logger.info("準備將選股清單寫入 Redis 記憶體...")
        
        # 1. 將選股結果直接寫入 Redis，設定 24 小時後自動過期 (避免佔用記憶體)
        success_json = redis_db.set_json(self.watchlist_key, watchlist_data, expire_sec=86400)
        
        if success_json:
            logger.info("✅ 選股清單 JSON 已成功寫入 Redis！")
            
            # 2. 設定更新旗標，存活時間設為 60 秒 (避免系統當機導致舊旗標殘留)
            success_flag = redis_db.set_flag(self.flag_key, "1", expire_sec=60)
            
            if success_flag:
                logger.info("✅ 已發送 Redis 更新旗標！(主系統將在 1 毫秒內收到通知)")
            else:
                logger.error("❌ Redis 旗標設定失敗！")
        else:
            logger.error("❌ Redis 選股清單寫入失敗！")

    def run(self):
        """主執行流程"""
        logger.info("=== 🚀 啟動高效能選股程式 (Redis 整合版) ===")
        
        try:
            # 1. 執行選股邏輯，取得選股清單
            final_watchlist = self.run_screening_logic()
            
            # 2. 儲存結果到 Redis (取代原本的檔案寫入: open('watchlist.json', 'w')...)
            self.save_to_redis(final_watchlist)
            
        except Exception as e:
            logger.error(f"選股過程中發生錯誤: {e}")
            
        logger.info("=== 選股程式執行結束 ===")

if __name__ == "__main__":
    screener = StockScreener()
    screener.run()