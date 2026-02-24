# 檔案名稱: mock_market_maker.py
import time
import random
import logging
import requests
import csv
import os
from datetime import datetime
from redis_manager import redis_db

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class TWSEScreener:
    """
    [系統功能三：TWSE 選股策略]
    全自動從證交所獲取資料，並依據嚴格條件進行篩選
    """
    def __init__(self):
        self.url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

    def fetch_and_screen(self):
        logger.info("📡 開始從 TWSE 下載全市場行情資料進行智能選股...")
        try:
            response = requests.get(self.url, timeout=15)
            data = response.json()
            
            screened_stocks = []
            
            for stock in data:
                try:
                    code = stock.get("Code", "")
                    name = stock.get("Name", "")
                    
                    # 條件 1: 排除 ETF 與權證 (普通股通常為 4 碼，且不以 '00' 開頭)
                    if len(code) != 4 or code.startswith("00"):
                        continue
                        
                    close_price = float(stock.get("ClosingPrice", 0))
                    open_price = float(stock.get("OpeningPrice", 0))
                    high_price = float(stock.get("HighestPrice", 0))
                    low_price = float(stock.get("LowestPrice", 0))
                    # TWSE 的 TradeVolume 是股數，轉換為張數
                    volume = float(stock.get("TradeVolume", 0)) / 1000
                    
                    # 條件 2: 股價範圍限制 (排除 10 元以下雞蛋水餃股)
                    if close_price < 10.0:
                        continue
                        
                    # 條件 3: 成交量 >= 2000 張
                    if volume < 2000:
                        continue
                        
                    # 條件 4: 震幅 >= 2%
                    if low_price > 0:
                        amplitude = (high_price - low_price) / low_price
                        if amplitude < 0.02:
                            continue
                            
                    # 計算漲跌幅 (粗略以今收與今開計算，作為動能指標)
                    if open_price > 0:
                        change_percent = (close_price - open_price) / open_price
                    else:
                        change_percent = 0
                        
                    screened_stocks.append({
                        "code": code,
                        "name": name,
                        "price": close_price,
                        "volume": volume,
                        "amplitude": amplitude,
                        "change_percent": change_percent
                    })
                    
                except (ValueError, TypeError):
                    continue

            # 排序：優先以「漲跌幅」與「成交量」進行排序，取前 100 名
            # 這裡以成交量做主排序作為熱門度指標
            top_100_stocks = sorted(screened_stocks, key=lambda x: x['volume'], reverse=True)[:100]
            
            logger.info(f"✅ TWSE 選股完成！共篩選出 {len(top_100_stocks)} 檔符合條件之強勢股。")
            
            # 匯出 CSV 功能
            self._export_to_csv(top_100_stocks)
            
            return top_100_stocks
            
        except Exception as e:
            logger.error(f"❌ TWSE 篩選失敗: {e}")
            return []

    def _export_to_csv(self, stocks):
        filename = f"TWSE_HotStocks_{datetime.now().strftime('%Y%m%d')}.csv"
        try:
            with open(filename, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=["code", "name", "price", "volume", "amplitude", "change_percent"])
                writer.writeheader()
                writer.writerows(stocks)
            logger.info(f"💾 選股結果已匯出至 {filename}")
        except Exception as e:
            logger.error(f"匯出 CSV 失敗: {e}")

class MockExchange:
    """
    [系統功能一：模擬交易引擎]
    負責產生逼真的 Tick (逐筆) 與 Books (五檔) 資料
    """
    def __init__(self):
        self.screener = TWSEScreener()
        self.mock_stocks = {}

    def initialize_market(self):
        # 1. 取得 TWSE 篩選後的熱門股
        hot_stocks = self.screener.fetch_and_screen()
        
        if not hot_stocks:
            logger.warning("無法取得熱門股，使用預設測試清單。")
            watch_pool = ["2330", "2317", "2603"]
            for code in watch_pool:
                self.mock_stocks[code] = {"price": 100.0, "vol": 0}
        else:
            watch_pool = [s["code"] for s in hot_stocks]
            for s in hot_stocks:
                self.mock_stocks[s["code"]] = {"price": s["price"], "vol": 0}
                
        # 寫入 Redis 供策略大腦使用
        redis_db.set_json("system:config:watch_pool", watch_pool)
        logger.info(f"🚀 模擬交易所初始化完成，監控 {len(self.mock_stocks)} 檔標的。")

    def _generate_mock_books(self, current_price):
        """產生逼真的五檔委買/委賣掛單 (供進階策略偵測流動性與滑價)"""
        tick_size = 0.5 if current_price < 100 else 1.0 # 簡單模擬跳動單位
        
        bids = [{"price": round(current_price - (i * tick_size), 2), "size": random.randint(10, 500)} for i in range(1, 6)]
        asks = [{"price": round(current_price + (i * tick_size), 2), "size": random.randint(10, 500)} for i in range(1, 6)]
        return {"bids": bids, "asks": asks}

    def run(self):
        self.initialize_market()
        logger.info("🎪 模擬造市商開始瘋狂洗價 (含成交與五檔)...")
        
        try:
            while True:
                for symbol, data in self.mock_stocks.items():
                    # 模擬價格隨機遊走 (-0.3% ~ +0.3%)
                    change_percent = random.uniform(-0.003, 0.003)
                    new_price = round(data["price"] * (1 + change_percent), 2)
                    self.mock_stocks[symbol]["price"] = new_price
                    
                    trade_size = random.randint(1, 50)
                    self.mock_stocks[symbol]["vol"] += trade_size
                    
                    # 1. 推播 Trades (最新成交)
                    tick_data = {
                        "symbol": symbol,
                        "price": new_price,
                        "size": trade_size,
                        "volume": self.mock_stocks[symbol]["vol"]
                    }
                    redis_db.set_json(f"market:trades:{symbol}", tick_data)
                    
                    # 2. 推播 Books (五檔掛單深度)
                    books_data = self._generate_mock_books(new_price)
                    books_data["symbol"] = symbol
                    redis_db.set_json(f"market:books:{symbol}", books_data)
                
                # 更新頻率
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("🎪 模擬交易所已安全關閉。")

if __name__ == "__main__":
    exchange = MockExchange()
    exchange.run()