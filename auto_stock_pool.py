# auto_stock_pool.py
import requests
import logging
from redis_manager import redis_db

# 設定日誌格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ✅ 系統安全上限：富邦 WebSocket 每個標的訂閱 2 個 Channel (trades + books)
# 富邦單一連線上限 200 channels，保留緩衝後最多 95 檔。
# 此常數必須與 fubon_websocket_engine.py 中的 MAX_SAFE_STOCKS 保持一致！
MAX_SAFE_STOCKS = 95

class AutoStockPool:
    def __init__(self):
        # TWSE 每日收盤行情 OpenAPI
        self.url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

    def generate_hot_pool(self):
        logger.info("開始從證交所下載最新市場行情資料...")
        try:
            response = requests.get(self.url, timeout=10)
            data = response.json()

            hot_stocks = []

            for stock in data:
                try:
                    code = stock.get("Code", "")
                    # 排除權證、牛熊證等非普通股（普通股代號通常為 4 碼）
                    if len(code) != 4:
                        continue

                    # ✅ 加入千分位去除，避免含逗號的字串 float 轉換失敗
                    close_price = float(str(stock.get("ClosingPrice", 0)).replace(',', '') or 0)
                    high_price  = float(str(stock.get("HighestPrice",  0)).replace(',', '') or 0)
                    low_price   = float(str(stock.get("LowestPrice",   0)).replace(',', '') or 0)
                    # TWSE 的 TradeVolume 是股數，除以 1000 轉成「張數」
                    volume = float(str(stock.get("TradeVolume", 0)).replace(',', '') or 0) / 1000

                    # 條件 1: 股價大於 10 元（排除低價雞蛋水餃股）
                    if close_price < 10:
                        continue

                    # 條件 2: 成交量超過 2000 張（確保流動性，不產生巨大滑價）
                    if volume < 2000:
                        continue

                    # 條件 3: 振幅超過 2%（有波動才有當沖套利空間）
                    amplitude = (high_price - low_price) / close_price if close_price > 0 else 0
                    if amplitude < 0.02:
                        continue

                    hot_stocks.append({
                        "code":      code,
                        "name":      stock.get("Name", ""),
                        "volume":    volume,
                        "price":     close_price,
                        "amplitude": amplitude
                    })
                except ValueError:
                    # 忽略無法轉型為數字的無效資料
                    continue

            # 依「成交量」由大到小排序
            hot_stocks = sorted(hot_stocks, key=lambda x: x['volume'], reverse=True)

            # ✅ 修正點：原本取前 100 檔，造成 WebSocket 引擎每次都截斷 5 檔並發出警告。
            # 改為直接取前 MAX_SAFE_STOCKS(95) 檔，與 fubon_websocket_engine.py 的上限對齊。
            top_pool = hot_stocks[:MAX_SAFE_STOCKS]

            watch_pool_codes = [stock["code"] for stock in top_pool]

            logger.info(f"✅ 成功篩選出 {len(watch_pool_codes)} 檔高流動性強勢股！"
                        f"（限制在 {MAX_SAFE_STOCKS} 檔安全上限以內）")
            logger.info(f"熱門排行榜前 5 名: {watch_pool_codes[:5]}")

            # 將清單寫入 Redis，供「策略大腦」與「行情引擎」讀取
            redis_db.set_json("system:config:watch_pool", watch_pool_codes)
            logger.info("✅ 已同步最新選股池至 Redis！")

            return watch_pool_codes

        except Exception as e:
            logger.error(f"獲取選股池時發生錯誤: {e}")
            return []


if __name__ == "__main__":
    pool_manager = AutoStockPool()
    pool_manager.generate_hot_pool()