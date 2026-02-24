"""
台股盤後選股腳本 - V3.0 (對齊戰情室 V10.6 邏輯)
功能：
1. 自動透過 TWSE OpenAPI 或 CSV 備用節點獲取全市場今日報價
2. 鎖定台灣時間 (UTC+8)，解決跨日抓取日期錯誤問題
3. 篩選條件：漲跌幅前 100 名、成交量 ≥ 2000 張、震幅 ≥ 2%、排除 ETF
4. 自動將結果輸出為當日日期綴尾的 CSV 檔案
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from io import StringIO
import logging
import os

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TWSEStockScreenerPro:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        # 常見 ETF 開頭代號，用於排除
        self.etf_prefixes = ['00', '006', '007', '008', '009']
    
    def run_screener(self, limit=100, min_volume=2000, min_amplitude=2.0, min_price=10, max_price=1000):
        """
        執行完整選股流程
        """
        logger.info("🚀 啟動 TWSE 盤後選股策略...")
        
        try:
            # 1. 獲取原始數據
            data = self._fetch_twse_openapi()
            
            if data is None or data.empty:
                logger.warning("⚠️ OpenAPI 獲取失敗，自動切換至 CSV 備用數據源...")
                data = self._fetch_twse_csv()
            
            if data is None or data.empty:
                logger.error("❌ 無法獲取任何 TWSE 數據，請檢查網路或 TWSE 伺服器狀態。")
                return pd.DataFrame(), pd.DataFrame()
            
            logger.info("✅ 成功獲取市場數據，開始進行清洗與計算...")
            
            # 2. 數據清洗與指標計算
            processed_data = self._process_data(data)
            
            if processed_data.empty:
                logger.error("❌ 數據處理後無有效資料。")
                return pd.DataFrame(), pd.DataFrame()
            
            # 3. 條件篩選 (成交量、震幅、股價範圍)
            filtered_data = self._apply_filters(
                processed_data, 
                min_volume=min_volume,
                min_amplitude=min_amplitude,
                min_price=min_price,
                max_price=max_price
            )
            
            # 4. 分離強弱勢股
            top_gainers = self._get_top_gainers(filtered_data, limit)
            top_losers = self._get_top_losers(filtered_data, limit)
            
            return top_gainers, top_losers
            
        except Exception as e:
            logger.error(f"❌ 選股策略執行錯誤: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame(), pd.DataFrame()
    
    def _fetch_twse_openapi(self):
        """使用 TWSE OpenAPI 獲取數據"""
        try:
            url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            response = self.session.get(url, timeout=15)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            if not data:
                return None
                
            return pd.DataFrame(data)
            
        except Exception as e:
            logger.debug(f"OpenAPI 連線異常: {e}")
            return None
    
    def _fetch_twse_csv(self):
        """使用 TWSE CSV 獲取數據 (強制鎖定台灣時間)"""
        try:
            # 強制使用台灣時間 (UTC+8)
            tw_tz = timezone(timedelta(hours=8))
            now_tw = datetime.now(tw_tz)
            date_str = now_tw.strftime('%Y%m%d')
            
            url = f'https://www.twse.com.tw/rwc/zh/MIS/OA310/list?dataType=ALL&date={date_str}'
            logger.info(f"嘗試下載 CSV: {url}")
            
            response = self.session.get(url, timeout=15)
            response.encoding = 'utf-8'
            
            if response.status_code != 200:
                return None
            
            # 讀取 CSV，跳過第一行註解
            df = pd.read_csv(StringIO(response.text), header=1)
            return df
            
        except Exception as e:
            logger.debug(f"CSV 下載異常: {e}")
            return None
    
    def _process_data(self, df):
        """處理原始數據，統一欄位名稱並計算技術指標"""
        try:
            processed = df.copy()
            
            # 判斷是否為 CSV 格式並重新命名欄位
            if '證券代號' in processed.columns:
                processed = processed.rename(columns={
                    '證券代號': 'Code',
                    '證券名稱': 'Name',
                    '收盤價': 'ClosingPrice',
                    '漲跌價差': 'Change',
                    '最高價': 'HighestPrice',
                    '最低價': 'LowestPrice',
                    '成交股數': 'TradeVolume'
                })
            
            # 確保必要欄位存在
            required_columns = ['Code', 'ClosingPrice', 'Change', 'HighestPrice', 'LowestPrice', 'TradeVolume']
            for col in required_columns:
                if col not in processed.columns:
                    logger.warning(f"缺少必要欄位: {col}")
                    return pd.DataFrame()
            
            # 清理代碼空白
            processed['Code'] = processed['Code'].astype(str).str.strip()
            
            # 過濾只保留普通股 (4碼數字)
            processed = processed[processed['Code'].str.match(r'^\d{4}$')]
            
            # 排除 ETF
            processed = processed[~processed['Code'].str.startswith(tuple(self.etf_prefixes))]
            
            if processed.empty:
                return pd.DataFrame()
            
            # 轉換數值欄位 (去除逗號)
            numeric_cols = ['ClosingPrice', 'Change', 'HighestPrice', 'LowestPrice', 'TradeVolume']
            for col in numeric_cols:
                processed[col] = processed[col].astype(str).str.replace(',', '')
                processed[col] = pd.to_numeric(processed[col], errors='coerce')
            
            # 計算成交量（將股數轉為張數）
            processed['Volume'] = processed['TradeVolume'] / 1000
            
            # 計算昨收與漲跌幅
            processed['PrevClose'] = processed['ClosingPrice'] - processed['Change']
            processed['ChangePercent'] = 0.0
            mask = processed['PrevClose'] != 0
            processed.loc[mask, 'ChangePercent'] = (
                processed.loc[mask, 'Change'] / processed.loc[mask, 'PrevClose'] * 100
            )
            
            # 計算震幅 = (最高 - 最低) / 昨收
            processed['Amplitude'] = 0.0
            processed.loc[mask, 'Amplitude'] = (
                (processed.loc[mask, 'HighestPrice'] - processed.loc[mask, 'LowestPrice']) / 
                processed.loc[mask, 'PrevClose'] * 100
            )
            
            # 清理 NaN 值
            processed = processed.dropna(subset=['ChangePercent', 'Volume', 'Amplitude'])
            
            return processed
            
        except Exception as e:
            logger.error(f"數據清洗錯誤: {e}")
            return pd.DataFrame()
    
    def _apply_filters(self, df, min_volume, min_amplitude, min_price, max_price):
        """套用使用者自訂的過濾條件"""
        filtered = df.copy()
        filtered = filtered[filtered['Volume'] >= min_volume]
        filtered = filtered[filtered['Amplitude'] >= min_amplitude]
        filtered = filtered[
            (filtered['ClosingPrice'] >= min_price) & 
            (filtered['ClosingPrice'] <= max_price)
        ]
        # 排除漲跌幅為 0 或過小的平盤股
        filtered = filtered[abs(filtered['ChangePercent']) >= 0.1]
        return filtered
    
    def _get_top_gainers(self, df, limit):
        """獲取漲幅前 N 名"""
        if df.empty: return pd.DataFrame()
        gainers = df[df['ChangePercent'] > 0].copy()
        if gainers.empty: return pd.DataFrame()
        
        gainers = gainers.sort_values('ChangePercent', ascending=False).head(limit)
        gainers = gainers.rename(columns={
            'Code': 'symbol', 'Name': 'name', 'ClosingPrice': 'price',
            'ChangePercent': 'change_pct', 'Volume': 'volume', 
            'Amplitude': 'amplitude', 'Change': 'change_amount',
            'HighestPrice': 'high', 'LowestPrice': 'low'
        })
        return gainers[['symbol', 'name', 'price', 'change_pct', 'volume', 'amplitude', 'change_amount', 'high', 'low']]
    
    def _get_top_losers(self, df, limit):
        """獲取跌幅前 N 名"""
        if df.empty: return pd.DataFrame()
        losers = df[df['ChangePercent'] < 0].copy()
        if losers.empty: return pd.DataFrame()
        
        losers = losers.sort_values('ChangePercent', ascending=True).head(limit)
        losers = losers.rename(columns={
            'Code': 'symbol', 'Name': 'name', 'ClosingPrice': 'price',
            'ChangePercent': 'change_pct', 'Volume': 'volume', 
            'Amplitude': 'amplitude', 'Change': 'change_amount',
            'HighestPrice': 'high', 'LowestPrice': 'low'
        })
        return losers[['symbol', 'name', 'price', 'change_pct', 'volume', 'amplitude', 'change_amount', 'high', 'low']]


if __name__ == "__main__":
    # 若要設定自動排程，只需直接執行本 Python 腳本即可
    screener = TWSEStockScreenerPro()
    
    # 可依照需求調整預設參數
    gainers, losers = screener.run_screener(
        limit=100, 
        min_volume=3000, 
        min_amplitude=3.0, 
        min_price=10, 
        max_price=150
    )
    
    # 產生具備今日日期的檔名 (以台灣時區為主)
    tw_tz = timezone(timedelta(hours=8))
    today_str = datetime.now(tw_tz).strftime('%Y%m%d')
    
    gainers_file = f"twse_gainers_{today_str}.csv"
    losers_file = f"twse_losers_{today_str}.csv"
    
    if not gainers.empty:
        gainers.to_csv(gainers_file, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 已成功匯出強勢股 CSV: {gainers_file} (共 {len(gainers)} 檔)")
    else:
        logger.warning("📉 今日無符合條件的強勢股。")
        
    if not losers.empty:
        losers.to_csv(losers_file, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 已成功匯出弱勢股 CSV: {losers_file} (共 {len(losers)} 檔)")
    else:
        logger.warning("📉 今日無符合條件的弱勢股。")

    print("\n" + "="*50)
    print(f"篩選完成日期: {datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)