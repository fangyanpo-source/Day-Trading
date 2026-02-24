# 檔案名稱: fubon_async_order_manager.py
import asyncio
import time
import logging
from typing import List, Dict

# 匯入富邦新一代 API SDK 與常數
from fubon_neo.sdk import FubonSDK, Order
from fubon_neo.constant import TimeInForce, OrderType, PriceType, MarketType, BSAction

logger = logging.getLogger(__name__)

class FubonAsyncOrderManager:
    def __init__(self, id_no: str, password: str, cert_path: str, cert_pass: str):
        self.sdk = FubonSDK()
        logger.info("登入富邦新一代 API 中...")
        
        try:
            self.accounts = self.sdk.login(id_no, password, cert_path, cert_pass)
            logger.info(f"✅ 富邦 API 登入成功！帳號資訊: {self.accounts.data}")
            
            # 預設使用第一個證券帳號 (若為期貨請改用期貨帳號判斷)
            self.stock_account = self.accounts.data[0] 
            
        except Exception as e:
            logger.error(f"❌ 富邦 API 登入失敗: {e}")
            raise

    def _sync_fubon_place_order(self, stock_code: str, action_str: str, price: float, qty: int) -> dict:
        """
        呼叫真實的富邦 SDK 進行委託 (阻塞版本，以獲取完整委託書號)
        """
        try:
            # 判斷買賣別
            bs_action = BSAction.Buy if action_str.upper() == "BUY" else BSAction.Sell
            
            # 建立富邦委託單內容
            # 這裡以現股 (Stock)、限價 (Limit)、當日有效 (ROD) 為例
            order = Order(
                buy_sell=bs_action,
                symbol=stock_code,
                price=str(price),
                quantity=qty,
                market_type=MarketType.Common,   # 整股市場
                price_type=PriceType.Limit,      # 限價單 (若要市價可改 PriceType.Market)
                time_in_force=TimeInForce.ROD,   # 當日有效
                order_type=OrderType.Stock       # 現股
            )
            
            logger.info(f"[{stock_code}] 📡 傳送 {action_str} 委託至富邦主機...")
            
            # 呼叫 SDK 下單 (不傳入 True，使用預設的阻塞模式獲取完整回報)
            result = self.sdk.stock.place_order(self.stock_account, order)
            
            if result.is_success:
                return {"stock": stock_code, "status": "Success", "data": result.data}
            else:
                return {"stock": stock_code, "status": "Failed", "message": result.message}
                
        except Exception as e:
            logger.error(f"[{stock_code}] 委託發生嚴重錯誤: {e}")
            return {"stock": stock_code, "status": "Error", "message": str(e)}

    async def async_place_order(self, stock_code: str, action: str, price: float, qty: int):
        """非同步包裝器"""
        start_time = time.time()
        
        # 將富邦的阻塞委託丟到背景 Thread 執行
        result = await asyncio.to_thread(
            self._sync_fubon_place_order, stock_code, action, price, qty
        )
        
        elapsed = (time.time() - start_time) * 1000
        
        if result["status"] == "Success":
            logger.info(f"[{stock_code}] ✅ 委託成功! (耗時: {elapsed:.2f} ms) 委託書號: {result['data'].order_no}")
        else:
            logger.warning(f"[{stock_code}] ❌ 委託失敗! (耗時: {elapsed:.2f} ms) 錯誤: {result.get('message')}")
            
        return result

    async def execute_basket_orders(self, orders: List[Dict]):
        """同時送出一籃子委託單至富邦主機"""
        logger.info(f"🚀 準備同時發射 {len(orders)} 筆委託單...")
        start_time = time.time()
        
        tasks = []
        for order in orders:
            task = self.async_place_order(
                stock_code=order['stock_code'],
                action=order['action'],
                price=order['price'],
                qty=order['qty']
            )
            tasks.append(task)
            
        # 同時執行所有委託並等待回應
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = (time.time() - start_time) * 1000
        logger.info(f"🎉 籃子委託全部送出完畢！總耗時: {total_time:.2f} ms")
        return results