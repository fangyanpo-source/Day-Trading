"""
台股完整清單與批次下載工具 (expand_stock_universe.py) - V3.0 自動爬蟲版
功能：
1. [New] 自動從證交所/櫃買中心網站抓取「最新完整」股票清單 (含上市+上櫃)
2. 提供 get_universe_list() 介面供其他程式呼叫
3. 自動過濾權證、ETF (可選)，只保留普通股
"""

import pandas as pd
import requests
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 預設的精選清單 (當爬蟲失敗時的備案)
DEFAULT_STOCKS = {
    '2330': '台積電', '2317': '鴻海', '2454': '聯發科', '2603': '長榮', '2881': '富邦金'
}

def fetch_twse_stocks():
    """從證交所抓取上市股票清單"""
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    try:
        res = requests.get(url)
        df = pd.read_html(res.text)[0]
        # 設定欄位
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        # 篩選股票 (代碼只有4碼的通常是普通股)
        df['代號'] = df['有價證券代號及名稱'].apply(lambda x: x.split()[0])
        df['名稱'] = df['有價證券代號及名稱'].apply(lambda x: x.split()[-1])
        # 只保留 4 碼代號 (排除權證、公司債等)
        df = df[df['代號'].str.match(r'^\d{4}$')]
        # 排除 00 開頭 (ETF) 與 91 開頭 (DR) - 視需求而定
        # df = df[~df['代號'].str.startswith('00')] 
        # df = df[~df['代號'].str.startswith('91')]
        
        stocks = dict(zip(df['代號'], df['名稱']))
        logger.info(f"✅ 成功抓取上市股票: {len(stocks)} 檔")
        return stocks
    except Exception as e:
        logger.error(f"❌ 抓取上市股票失敗: {e}")
        return {}

def fetch_tpex_stocks():
    """從櫃買中心抓取上櫃股票清單"""
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    try:
        res = requests.get(url)
        df = pd.read_html(res.text)[0]
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        df['代號'] = df['有價證券代號及名稱'].apply(lambda x: x.split()[0])
        df['名稱'] = df['有價證券代號及名稱'].apply(lambda x: x.split()[-1])
        df = df[df['代號'].str.match(r'^\d{4}$')]
        
        stocks = dict(zip(df['代號'], df['名稱']))
        logger.info(f"✅ 成功抓取上櫃股票: {len(stocks)} 檔")
        return stocks
    except Exception as e:
        logger.error(f"❌ 抓取上櫃股票失敗: {e}")
        return {}

def get_universe_list():
    """
    獲取全市場股票代碼 (List)
    優先嘗試爬蟲，失敗則回傳預設清單
    """
    logger.info("正在更新全市場清單 (TWSE + TPEX)...")
    
    twse = fetch_twse_stocks()
    tpex = fetch_tpex_stocks()
    
    # 合併
    all_stocks = {**twse, **tpex}
    
    if all_stocks:
        logger.info(f"🎉 總計取得: {len(all_stocks)} 檔股票")
        # 這裡也可以選擇將清單存成 CSV 供下次快速讀取
        # pd.DataFrame(list(all_stocks.items()), columns=['code', 'name']).to_csv('stock_list.csv', index=False)
        return list(all_stocks.keys())
    else:
        logger.warning("⚠️ 爬蟲失敗，使用預設精選清單")
        return list(DEFAULT_STOCKS.keys())

# 為了相容舊程式，保留 TWSE_STOCKS 變數，但建議呼叫 get_universe_list()
TWSE_STOCKS = DEFAULT_STOCKS

def main():
    stocks = get_universe_list()
    print(f"\n📋 前 10 檔預覽: {stocks[:10]}")
    print(f"📋 後 10 檔預覽: {stocks[-10:]}")

if __name__ == "__main__":
    main()