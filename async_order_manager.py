# 檔案名稱: async_order_manager.py
import asyncio
import time
import logging
from typing import List, Dict

# 假設這是你的券商 API (如果是同步套件，我們會在下面用 to_thread 包裝它)
# from fubon_api_core import FubonAPI

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S.%f'[:-3] # 顯示到毫秒
)
logger = logging.getLogger(__name__)

class AsyncOrderManager:
    def __init__(self):
        # 這裡會初始化你的富邦 API
        # self.api = FubonAPI()
        logger.info("⚡ 非同步極速下單引擎初始化完成")

    def _sync_place_order(self, stock_code: str, action: str, price: float, qty: int) -> dict:
        """
        模擬原本的同步下單函數 (例如呼叫富邦 SDK)。
        大多數台股券商 SDK (C++ wrapper) 預設是阻塞的(Blocking)。
        """
        logger.info(f"[{stock_code}] 📡 傳送 {action} 委託至券商...")
        time.sleep(0.2) # 模擬網路延遲與券商主機處理時間
        
        # 模擬券商回報
        return {"stock": stock_code, "status": "Success", "order_id": f"ORD_{int(time.time()*1000)}"}

    async def async_place_order(self, stock_code: str, action: str, price: float, qty: int):
        """
        將同步的 SDK 下單動作，包裝成非同步 (Async) 任務
        這樣就不會卡住主執行緒 (Event Loop)
        """
        start_time = time.time()
        
        # 使用 asyncio.to_thread 讓阻塞的 API 呼叫在背景 Thread 執行
        # 這是台股 API 非同步化的標準解法！
        result = await asyncio.to_thread(
            self._sync_place_order, stock_code, action, price, qty
        )
        
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[{stock_code}] ✅ 委託回報接收完成! (耗時: {elapsed:.2f} ms) 回報: {result}")
        return result

    async def execute_basket_orders(self, orders: List[Dict]):
        """
        【極速核心】同時送出一籃子(多檔)委託單
        """
        logger.info(f"🚀 準備同時發射 {len(orders)} 筆委託單...")
        start_time = time.time()
        
        # 建立一堆非同步任務 (Tasks)
        tasks = []
        for order in orders:
            task = self.async_place_order(
                stock_code=order['stock_code'],
                action=order['action'],
                price=order['price'],
                qty=order['qty']
            )
            tasks.append(task)
            
        # asyncio.gather 會「同時」執行所有任務，並等待它們全部完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = (time.time() - start_time) * 1000
        logger.info(f"🎉 籃子委託全部執行完畢！總耗時: {total_time:.2f} ms")
        return results

    async def main_loop(self):
        """
        模擬盤中不斷監聽訊號的主迴圈
        """
        logger.info("正在監聽策略觸發訊號...")
        await asyncio.sleep(1) # 模擬等待訊號
        
        # 假設策略同時觸發了 5 檔股票的多單
        mock_signals = [
            {"stock_code": "2330", "action": "BUY", "price": 850.0, "qty": 1},
            {"stock_code": "2603", "action": "BUY", "price": 180.0, "qty": 2},
            {"stock_code": "2317", "action": "BUY", "price": 150.0, "qty": 5},
            {"stock_code": "2454", "action": "BUY", "price": 1100.0, "qty": 1},
            {"stock_code": "3231", "action": "BUY", "price": 120.0, "qty": 10},
        ]
        
        # 瞬間發射！
        await self.execute_basket_orders(mock_signals)

if __name__ == "__main__":
    manager = AsyncOrderManager()
    
    # 啟動非同步事件迴圈
    asyncio.run(manager.main_loop())