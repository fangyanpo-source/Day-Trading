"""
全市場日K線下載器 - V4.1 富邦 Neo SDK 版
新增功能：
- 支援期貨/選擇權 即時/歷史K線 (intraday.candles)
- 完全符合 SDK 2.2.4+ 異常處理規範
"""

import time
import logging
import pandas as pd
from datetime import datetime, timedelta
import os
import json

from fubon_neo.sdk import FubonSDK
from fubon_neo.fugle_marketdata.rest.base_rest import FugleAPIError   # ✅ 正確匯入例外
from database_manager import DatabaseManager

try:
    from expand_stock_universe import get_universe_list
    HAS_EXPAND = True
except ImportError:
    HAS_EXPAND = False
    DEFAULT_LIST = ['2330', '2317', '2454', '2603', '2881', '0050', '0056']
    print("⚠️ 找不到 expand_stock_universe.py，使用內建測試清單")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("HistoricalDownloader")

CONFIG_FILE = "fubon_config.json"


def load_config():
    """讀取富邦 Neo 設定檔"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"讀取設定檔失敗: {e}")
    # 引導使用者輸入
    print("\n" + "=" * 50)
    print("🛠️ 初次設定：請輸入富邦 API 登入資訊")
    print("=" * 50)
    cfg = {
        'id': input("身分證字號: ").strip(),
        'pwd': input("交易密碼: ").strip(),
        'cert_path': input("憑證路徑 (.pfx): ").strip(),
        'cert_pwd': input("憑證密碼: ").strip()
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4)
    print(f"✅ 設定已儲存至 {CONFIG_FILE}")
    return cfg


# ----------------------------------------------------------------------
# 📈 股票日Ｋ線下載 (原有，僅強化異常處理)
# ----------------------------------------------------------------------
def download_stock_daily_candles(sdk, symbol, start_date, end_date):
    """
    下載個股日K線（historical.candles）
    """
    try:
        reststock = sdk.marketdata.rest_client.stock
        params = {
            "symbol": symbol,
            "from": start_date,
            "to": end_date,
            "timeframe": "D",
            "fields": "open,high,low,close,volume,change",
            "sort": "asc"
        }
        resp = reststock.historical.candles(**params)
        if resp and 'data' in resp:
            df = pd.DataFrame(resp['data'])
            df.rename(columns={
                'date': 'Timestamp',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }, inplace=True)
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            return df
    except FugleAPIError as e:
        logger.error(f"{symbol} 股票API錯誤 [{e.status_code}]: {e.response_text}")
    except Exception as e:
        logger.error(f"{symbol} 股票下載失敗: {e}")
    return None


# ----------------------------------------------------------------------
# 📉 期貨/選擇權 日內K線下載 (新增，完全依據API文件)
# ----------------------------------------------------------------------
def download_futopt_intraday_candles(sdk, symbol, timeframe='1', session=None):
    """
    下載期貨/選擇權 即時K線 (intraday.candles)

    參數:
        sdk      : 已登入的 FubonSDK 實例
        symbol   : 期權代碼，例如 'TXFA4', 'TXO4'
        timeframe: K線週期，可選 '1','5','10','15','30','60'
        session  : 可選 'afterhours' 夜盤
    回傳:
        DataFrame 包含欄位: Timestamp, Open, High, Low, Close, Volume, Average
    """
    try:
        restfutopt = sdk.marketdata.rest_client.futopt
        # 2.2.4 以上版本建議使用 try/except FugleAPIError 捕捉
        params = {'symbol': symbol}
        if timeframe:
            params['timeframe'] = timeframe
        if session:
            params['session'] = session

        resp = restfutopt.intraday.candles(**params)
        if resp and 'data' in resp:
            df = pd.DataFrame(resp['data'])
            # 統一轉為標準欄位名稱
            df.rename(columns={
                'date': 'Timestamp',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'average': 'Average'
            }, inplace=True)
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            # 附帶商品基本資訊
            df['symbol'] = symbol
            df['timeframe'] = timeframe
            return df
    except FugleAPIError as e:
        logger.error(f"{symbol} 期權API錯誤 [{e.status_code}]: {e.response_text}")
    except Exception as e:
        logger.error(f"{symbol} 期權下載失敗: {e}")
    return None


def main():
    logger.info("🚀 啟動全市場日K線下載器 (富邦 Neo SDK 4.1)")

    cfg = load_config()
    sdk = FubonSDK()
    try:
        accounts = sdk.login(cfg['id'], cfg['pwd'], cfg['cert_path'], cfg['cert_pwd'])
        logger.info("✅ 登入成功")
    except Exception as e:
        logger.error(f"❌ 登入失敗: {e}")
        return

    sdk.init_realtime()
    logger.info("✅ 行情連線初始化完成")

    # --------------------------------------------------------------
    # 1. 下載股票日K線（原有邏輯）
    # --------------------------------------------------------------
    if HAS_EXPAND:
        symbols = get_universe_list()
    else:
        symbols = DEFAULT_LIST
    logger.info(f"📋 股票清單共 {len(symbols)} 檔")

    end = datetime.now()
    start = end - timedelta(days=365)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    logger.info(f"📅 股票下載區間: {start_str} ~ {end_str}")

    db = DatabaseManager("trading_data.db")

    success_count = 0
    for idx, sym in enumerate(symbols, 1):
        logger.info(f"[{idx}/{len(symbols)}] 下載 {sym} ...")
        df = download_stock_daily_candles(sdk, sym, start_str, end_str)
        if df is not None and not df.empty:
            db.save_stock_data(sym, '1D', df)
            success_count += 1
        time.sleep(0.6)

    logger.info(f"✅ 股票完成！成功更新 {success_count}/{len(symbols)} 檔")

    # --------------------------------------------------------------
    # 2. (示範) 下載期貨當日1分K線
    # --------------------------------------------------------------
    futopt_symbols = ['TXFA4', 'TXO4']   # 可自行擴充
    for fut_sym in futopt_symbols:
        logger.info(f"🔄 下載期權即時K線: {fut_sym}")
        df_fut = download_futopt_intraday_candles(sdk, fut_sym, timeframe='1')
        if df_fut is not None:
            # 儲存至資料庫（需擴充 table schema，此處僅示範）
            logger.info(f"✅ 取得 {fut_sym} {len(df_fut)} 筆1分K線")
            # db.save_futopt_data(fut_sym, df_fut)   # 若需儲存請自行實作

    sdk.logout()


if __name__ == "__main__":
    main()