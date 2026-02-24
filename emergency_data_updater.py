# emergency_data_updater.py
import os
import json
import sqlite3
import datetime
import time
import requests
import pandas as pd
try:
    import yfinance as yf
except ImportError:
    print("請先安裝 yfinance: pip install yfinance")

# ✅ 匯入 Redis 管理器，讓盤後更新結果可以同步至 Streamlit 面板與策略引擎
from redis_manager import redis_db

# --- 設定區 ---
DB_PATH = 'trading_data.db'   # SQLite 資料庫路徑

# ✅ 系統安全上限（與 auto_stock_pool.py / fubon_websocket_engine.py 保持一致）
MAX_SAFE_STOCKS = 95

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
}


def get_latest_trading_date():
    """取得最近的一個交易日 (YYYYMMDD)"""
    now = datetime.datetime.now()
    # 如果現在時間早於下午 3 點，盤後資料可能還沒好，往前推一天
    if now.hour < 15:
        now = now - datetime.timedelta(days=1)
    # 避開六日
    while now.weekday() > 4:
        now = now - datetime.timedelta(days=1)
    return now.strftime('%Y%m%d')


def update_twse_hot_stocks():
    """
    強制抓取 TWSE 每日收盤行情並找出熱門股
    過濾條件：成交量 2000 張以上、振幅 4% 以上、漲跌幅前 100 名、排除 ETF
    """
    target_date = get_latest_trading_date()
    print(f"[*] 準備抓取 TWSE {target_date} 盤後資料...")

    url = (f"https://www.twse.com.tw/exchangeReport/MI_INDEX"
           f"?response=json&date={target_date}&type=ALLBUT0999")

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res_json = res.json()

        if res_json.get('stat') != 'OK':
            print(f"[!] TWSE API 回應異常: {res_json.get('stat')}")
            return []

        price_data = None
        fields = None

        # 嘗試解析新版格式（tables 陣列）
        if 'tables' in res_json:
            for table in res_json['tables']:
                if 'fields' in table and 'data' in table:
                    if '證券代號' in table['fields'] and '收盤價' in table['fields']:
                        fields = table['fields']
                        price_data = table['data']
                        break

        # 嘗試舊版格式（fieldsX / dataX）
        if not price_data:
            for key in res_json.keys():
                if key.startswith('fields'):
                    if '證券代號' in res_json[key] and '收盤價' in res_json[key]:
                        fields = res_json[key]
                        data_key = key.replace('fields', 'data')
                        price_data = res_json.get(data_key)
                        break

        if not price_data:
            print("[!] 無法在 TWSE 回應中找到價格表格格式。")
            return []

        df = pd.DataFrame(price_data, columns=fields)
        df['證券代號'] = df['證券代號'].astype(str)

        # 只保留 1~9 開頭且長度為 4 碼的純數字代號（排除 ETF 與權證）
        df = df[df['證券代號'].str.match(r'^[1-9]\d{3}$')]

        # 轉換數值型態（去除千分位逗號）
        numeric_cols = ['成交股數', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(',', ''), errors='coerce'
                )

        # 處理漲跌符號
        if '漲跌(+/-)' in df.columns:
            sign = df['漲跌(+/-)'].astype(str).str.extract(r'([+\-])')[0]
            df['漲跌值'] = df['漲跌價差']
            df.loc[sign == '-', '漲跌值'] = -df['漲跌價差']
            df.loc[~sign.isin(['+', '-']), '漲跌值'] = 0.0
        else:
            df['漲跌值'] = 0.0

        # 計算昨收 = 收盤價 - 漲跌值
        df['昨收'] = df['收盤價'] - df['漲跌值']
        df = df[df['昨收'] > 0].copy()

        # 計算振幅與漲跌幅
        df['振幅(%)'] = (df['最高價'] - df['最低價']) / df['昨收'] * 100
        df['漲跌幅(%)'] = df['漲跌值'] / df['昨收'] * 100
        df['絕對漲跌幅(%)'] = df['漲跌幅(%)'].abs()

        # 核心過濾
        cond = (df['成交股數'] >= 2000000) & (df['振幅(%)'] >= 4.0)
        hot_stocks = df[cond].copy()
        hot_stocks = hot_stocks.sort_values(by='絕對漲跌幅(%)', ascending=False).head(100)

        output_csv = f"TWSE_HotStocks_{target_date}.csv"
        hot_stocks.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"[v] 熱門股名單已儲存至: {output_csv} (共 {len(hot_stocks)} 檔)")

        return hot_stocks['證券代號'].tolist()

    except Exception as e:
        print(f"[X] 抓取 TWSE 資料失敗: {e}")
        return []


def import_to_watchlist(new_stocks):
    """將撈出的熱門股同步匯入本地監控清單檔案（JSON / TXT）"""
    if not new_stocks:
        return

    print(f"[*] 準備將 {len(new_stocks)} 檔熱門股匯入監控清單...")

    target_files = ['auto_trading_watchlist.json', 'daily_watchlist.json', 'stock_codes.txt']

    for file_path in target_files:
        if not os.path.exists(file_path) and not file_path.endswith('.txt'):
            continue

        print(f"  -> 嘗試更新清單: {file_path}")

        if file_path.endswith('.json'):
            data = []
            is_dict = False
            dict_key = 'watchlist'
            original_data = {}

            try:
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        original_data = json.load(f)

                    if isinstance(original_data, list):
                        data = original_data
                    elif isinstance(original_data, dict):
                        is_dict = True
                        if 'watchlist' in original_data and isinstance(original_data['watchlist'], list):
                            dict_key = 'watchlist'
                            data = original_data['watchlist']
                        elif 'stocks' in original_data and isinstance(original_data['stocks'], list):
                            dict_key = 'stocks'
                            data = original_data['stocks']
                        elif 'data' in original_data and isinstance(original_data['data'], list):
                            dict_key = 'data'
                            data = original_data['data']
                        else:
                            original_data['watchlist'] = []
                            data = original_data['watchlist']

                current_set = set(str(x).strip() for x in data)
                added_count = 0
                for stock in new_stocks:
                    stock_str = str(stock).strip()
                    if stock_str not in current_set:
                        data.append(stock_str)
                        current_set.add(stock_str)
                        added_count += 1

                with open(file_path, 'w', encoding='utf-8') as f:
                    if is_dict:
                        original_data[dict_key] = data
                        json.dump(original_data, f, indent=4, ensure_ascii=False)
                    else:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                print(f"     [v] {file_path} 寫入成功！新增 {added_count} 檔，目前共 {len(data)} 檔。")
            except Exception as e:
                print(f"     [X] 處理 {file_path} 失敗: {e}")

        elif file_path.endswith('.txt'):
            try:
                existing_stocks = []
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_stocks = [line.strip() for line in f if line.strip()]

                current_set = set(existing_stocks)
                added_count = 0
                for stock in new_stocks:
                    stock_str = str(stock).strip()
                    if stock_str not in current_set:
                        existing_stocks.append(stock_str)
                        current_set.add(stock_str)
                        added_count += 1

                with open(file_path, 'w', encoding='utf-8') as f:
                    for stock in existing_stocks:
                        f.write(stock + '\n')
                print(f"     [v] {file_path} 寫入成功！新增 {added_count} 檔，目前共 {len(existing_stocks)} 檔。")
            except Exception as e:
                print(f"     [X] 處理 {file_path} 失敗: {e}")


def sync_to_redis(new_stocks):
    """
    ✅ 新增核心功能：將最新熱門股名單同步寫入 Redis。
    
    過去 emergency_data_updater.py 只更新本地 JSON 檔與 SQLite，
    但 Streamlit 面板、策略大腦、行情引擎都從 Redis 讀取，
    導致「監控清單與雷達鎖定標的資料皆未更新」的問題。
    
    此函式統一將本次更新結果寫入 Redis 的兩個關鍵 Key：
    1. system:config:watch_pool  → 供行情引擎動態訂閱 WebSocket
    2. system:data:last_emergency_update → 供 UI 面板顯示最後更新時間戳
    """
    if not new_stocks:
        print("[!] 無熱門股資料，跳過 Redis 同步。")
        return

    # ✅ 截斷至安全上限（95 檔），與 WebSocket 引擎保持一致，避免截斷警告
    safe_pool = new_stocks[:MAX_SAFE_STOCKS]
    dropped_count = len(new_stocks) - len(safe_pool)
    if dropped_count > 0:
        print(f"[!] 熱門股共 {len(new_stocks)} 檔，截斷後保留前 {MAX_SAFE_STOCKS} 檔（丟棄 {dropped_count} 檔）。")

    try:
        # 1. 更新監控選股池
        redis_db.set_json("system:config:watch_pool", safe_pool)
        print(f"[v] Redis [system:config:watch_pool] 已同步 {len(safe_pool)} 檔熱門股！")

        # 2. 記錄最後更新時間，供 UI 面板顯示「最後同步時間」
        update_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        redis_db.set_flag("system:data:last_emergency_update", update_ts)
        print(f"[v] Redis [system:data:last_emergency_update] 已記錄更新時間: {update_ts}")

        # 3. 觸發「選股已更新」旗標，讓 Streamlit 可以即時偵測並刷新顯示
        redis_db.set_flag("system:flag:screener_updated", "1", expire_sec=60)
        print("[v] Redis [system:flag:screener_updated] 已觸發刷新旗標！")

    except Exception as e:
        print(f"[X] 同步 Redis 失敗: {e}")


def load_radar_targets():
    """
    優先從 Redis 讀取最新的監控標的，
    若 Redis 無資料才退回掃描本地設定檔。
    """
    # ✅ 優先讀 Redis（與主系統資料來源一致）
    redis_pool = redis_db.get_json("system:config:watch_pool")
    if redis_pool:
        print(f"[*] 從 Redis 載入 {len(redis_pool)} 檔雷達鎖定標的。")
        return redis_pool

    # Fallback：掃描本地 JSON / TXT 設定檔
    print("[*] Redis 無資料，改從本地設定檔掃描...")
    targets = set()
    target_files = ['auto_trading_watchlist.json', 'daily_watchlist.json', 'stock_codes.txt']

    for file_path in target_files:
        if not os.path.exists(file_path):
            continue
        try:
            if file_path.endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    raw_targets = []
                    if isinstance(data, list):
                        raw_targets = data
                    elif isinstance(data, dict):
                        for key in ('watchlist', 'stocks', 'data'):
                            if key in data and isinstance(data[key], list):
                                raw_targets = data[key]
                                break
                    for item in raw_targets:
                        val = str(item).strip()
                        if val and val[0].isdigit():
                            targets.add(val)
            elif file_path.endswith('.txt'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        val = line.strip()
                        if val and val[0].isdigit():
                            targets.add(val)
        except Exception as e:
            print(f"[X] 讀取 {file_path} 失敗: {e}")

    targets_list = list(targets)
    print(f"[*] 從本地設定檔載入 {len(targets_list)} 檔雷達鎖定標的。")
    return targets_list


def update_radar_kbars(targets):
    """使用 YFinance 強制更新 SQLite 中的盤後日 K 資料"""
    if not targets:
        print("[!] 沒有可更新的標的。")
        return

    print(f"[*] 開始更新 {len(targets)} 檔標的之盤後 K 線資料至資料庫...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_kbars (
            stock_id TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            UNIQUE(stock_id, date)
        )
    ''')

    success_count = 0
    for stock_id in targets:
        yf_symbol = f"{stock_id}.TW"
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="5d")

            if hist.empty:
                yf_symbol = f"{stock_id}.TWO"
                ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="5d")

            if not hist.empty:
                for index, row in hist.iterrows():
                    date_str = index.strftime('%Y-%m-%d')
                    cursor.execute('''
                        INSERT OR REPLACE INTO daily_kbars
                        (stock_id, date, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (stock_id, date_str,
                          row['Open'], row['High'], row['Low'], row['Close'], row['Volume']))
                success_count += 1
                print(f"  -> {stock_id} 更新成功")
            else:
                print(f"  -> {stock_id} 找不到資料")

        except Exception as e:
            print(f"  -> {stock_id} 更新失敗: {e}")

        time.sleep(0.5)

    conn.commit()
    conn.close()
    print(f"[v] 雷達標的 K 線更新完成！成功: {success_count}/{len(targets)}")


if __name__ == "__main__":
    print("=== 當沖系統緊急資料修復工具 ===")

    # 1. 更新熱門股清單
    hot_stock_codes = update_twse_hot_stocks()
    print("-" * 30)

    # 2. 同步至本地 JSON / TXT 監控清單檔案
    import_to_watchlist(hot_stock_codes)
    print("-" * 30)

    # ✅ 3. 同步至 Redis（修復「監控清單與雷達鎖定標的資料皆未更新」的根本原因）
    #    此步驟讓 Streamlit 面板、策略大腦、行情引擎立即看到最新熱門股名單。
    sync_to_redis(hot_stock_codes)
    print("-" * 30)

    # 4. 從 Redis 或本地設定檔讀取最終標的清單，進行 YFinance K 線補齊
    targets = load_radar_targets()
    update_radar_kbars(targets)

    print("=== 執行完畢 ===")