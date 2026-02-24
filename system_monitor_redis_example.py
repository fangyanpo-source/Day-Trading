# 檔案名稱: system_monitor_redis_example.py
import time
import logging
import traceback
from redis_manager import redis_db # 匯入我們建立的 Redis 管理器

logger = logging.getLogger(__name__)

class SystemMonitor:
    def __init__(self):
        self.is_running = True
        
        # 定義 Redis 中使用的 key 名稱 (須與選股程式一致)
        self.SCREENER_FLAG_KEY = "system:flag:screener_updated"
        self.WATCHLIST_KEY = "system:data:daily_watchlist"
        
        # 本地快取，避免重複處理相同的清單
        self.current_watchlist = {}

    def check_screener_update(self):
        """極低延遲檢查選股是否已更新"""
        try:
            flag_status = redis_db.get_flag(self.SCREENER_FLAG_KEY)
            
            if flag_status == "1":
                logger.info("🔔 偵測到選股更新訊號 (via Redis)！")
                
                # 瞬間從記憶體讀取選股名單
                watchlist_data = redis_db.get_json(self.WATCHLIST_KEY)
                
                if watchlist_data:
                    logger.info(f"✅ 成功載入最新選股清單，共 {len(watchlist_data)} 檔標的。")
                    self.current_watchlist = watchlist_data
                    
                    # ----------------------------------------------------
                    # 【核心整合區】
                    # 在這裡呼叫你的策略引擎或統一委託管理器
                    # 例如: strategy_manager.update_pool(self.current_watchlist)
                    # ----------------------------------------------------
                    self.process_new_watchlist()
                    
                else:
                    logger.warning("⚠️ 收到更新訊號，但 Redis 中無選股資料！")
                
                # 處理完畢後，安全地清除 flag
                redis_db.delete_flag(self.SCREENER_FLAG_KEY)
                logger.debug("已重置 Redis 更新旗標。")
                
        except Exception as e:
            logger.error(f"檢查選股更新時發生異常: {e}")
            logger.error(traceback.format_exc())

    def process_new_watchlist(self):
        """處理新選股清單的業務邏輯"""
        logger.info("開始處理新的選股標的...")
        # 實務上這裡會連接 intraday_strategies.py 或 unified_order_manager.py
        for stock_code, details in self.current_watchlist.items():
            logger.info(f" -> 標的: {stock_code}, 策略: {details.get('strategy', 'N/A')}")
        logger.info("處理完成，等待下一次訊號。")

    def run(self):
        logger.info("🚀 日內交易主控台/監控系統已啟動 (Redis 高速版)...")
        logger.info("正在監聽系統訊號...")

        while self.is_running:
            try:
                # 1. 檢查選股更新訊號
                self.check_screener_update()
                
                # 2. 其他盤中監控邏輯可放在此處
                # check_risk_limits()
                # check_api_connection()
                
                # 極短暫的休眠，避免佔用 100% CPU，但保持低延遲 (0.5秒)
                time.sleep(0.5)
                
            except KeyboardInterrupt:
                logger.info("接收到中斷訊號，正在安全關閉系統...")
                self.is_running = False
            except Exception as e:
                logger.error(f"主迴圈發生非預期錯誤: {e}")
                time.sleep(1) # 發生嚴重錯誤時稍作休息避免狂洗 Log

if __name__ == "__main__":
    # 設定日誌格式
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    monitor = SystemMonitor()
    monitor.run()