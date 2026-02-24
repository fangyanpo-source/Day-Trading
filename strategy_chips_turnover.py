"""
籌碼動能選股策略 (Strategy: Chips & Turnover) - TWSE 官方即時行情版
功能：
1. 資金關注：篩選全市場「成交金額 (Turnover Value)」排行前 50 名的熱門股。
2. 籌碼/分點模擬：透過「量價關係」與「均價 (VWAP)」來推估主力買氣。
   - 條件 A: 漲幅 > 0% (紅盤)
   - 條件 B: 現價 > 均價 (VWAP) -> 代表今日買進的人大多賺錢，主力控盤強
   - 條件 C: 振幅 > 2% -> 有波動才有當沖空間
"""

import pandas as pd
import numpy as np
import logging
import time
import os
import sys
import glob
import json
import sqlite3
import requests
import re
from datetime import datetime

# 引入 Redis 供 Streamlit 整合
try:
    from redis_manager import redis_db
except ImportError:
    print("❌ 找不到 redis_manager.py，無法直接更新 Redis 監控清單")
    redis_db = None

# 引入備援 API (夜間覆盤專用)
try:
    import yfinance as yf
except ImportError:
    yf = None
    print("⚠️ 找不到 yfinance 套件，夜間備援模式將無法使用 (pip install yfinance)")

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("ChipsStrategy")

DB_PATH = 'trading_data.db'

class ChipsTurnoverScreener:
    def __init__(self):
        print("🔌 系統初始化：準備使用 TWSE 官方即時 API 進行全市場行情掃描...")

    def get_target_stocks(self):
        stocks = []
        csv_files = glob.glob("TWSE_HotStocks_*.csv")
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            try:
                df = pd.read_csv(latest_csv)
                if '證券代號' in df.columns:
                    stocks = df['證券代號'].astype(str).tolist()
            except Exception: pass

        if not stocks and os.path.exists("auto_trading_watchlist.json"):
            try:
                with open("auto_trading_watchlist.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list): stocks = data
                    elif isinstance(data, dict) and 'watchlist' in data: stocks = data['watchlist']
            except Exception: pass

        if not stocks:
            stocks = ['2330', '2317', '2603', '3481', '2454']
            
        clean_stocks = [str(s).strip() for s in stocks if str(s).strip()[0].isdigit()]
        clean_stocks = list(dict.fromkeys(clean_stocks))
        return clean_stocks
        
    def export_to_watchlist(self, selected_stocks):
        if not selected_stocks: return
        clean_stocks = [str(s).strip() for s in selected_stocks if str(s).strip()]
        if len(clean_stocks) > 95: clean_stocks = clean_stocks[:95]
        comma_separated_str = ",".join(clean_stocks)
            
        if redis_db and getattr(redis_db, 'is_connected', False):
            try: 
                redis_db.set_json("system:config:watch_pool", clean_stocks)
                # 寫入一個時間戳，強制部分前端邏輯知道資料已更新
                redis_db.set_flag("system:config:last_update", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                print("   ✅ 已成功同步清單至 Redis / Memurai 大腦！(請至戰情室網頁按 F5 重新整理)")
            except Exception as e: 
                print(f"   ❌ Redis 同步異常: {e}")
        else:
            print("   ⚠️ Redis 未連線，將僅寫入實體檔案備援。")
                
        # 🌟 升級版：安全覆寫 JSON (保留字典結構防呆，避免 Streamlit 讀取崩潰)
        target_files = ['auto_trading_watchlist.json', 'daily_watchlist.json']
        for file_path in target_files:
            try:
                is_dict = False
                dict_key = 'watchlist'
                original_data = {}
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        try: original_data = json.load(f)
                        except Exception: pass
                    if isinstance(original_data, dict):
                        is_dict = True
                        if 'watchlist' in original_data: dict_key = 'watchlist'
                        elif 'stocks' in original_data: dict_key = 'stocks'
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    if is_dict:
                        original_data[dict_key] = clean_stocks
                        json.dump(original_data, f, indent=4, ensure_ascii=False)
                    else:
                        json.dump(clean_stocks, f, indent=4, ensure_ascii=False)
            except Exception: pass
                
        for file_path in ['stock_codes.txt', 'watchlist_config.txt', '.watchlist_cache']:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(comma_separated_str)
            except Exception: pass
            
        return comma_separated_str

    def sync_kbars_to_db(self, selected_market_data):
        if not selected_market_data: return
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_kbars (
                    stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
                    UNIQUE(stock_id, date)
                )
            ''')
            
            today_fallback = datetime.now().strftime('%Y-%m-%d')
            for row in selected_market_data:
                stock_id = row['code']
                open_p, high_p, low_p, close_p = row['open'], row['high'], row['low'], row['price']
                vol = row['volume']

                # 🌟 優先使用資料自帶的真實日期 (避免將昨日資料印上今日日期)
                d_str1 = row.get('date', today_fallback)
                d_str2 = d_str1.replace('-', '')

                for d_str in [d_str1, d_str2]:
                    cursor.execute('''
                        INSERT OR REPLACE INTO daily_kbars 
                        (stock_id, date, open, high, low, close, volume) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (stock_id, d_str, open_p, high_p, low_p, close_p, vol))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"   ❌ K 線寫入資料庫失敗: {e}")

    def _fetch_twse_intraday(self, stocks):
        """🌟 透過 TWSE 官方行情 API 抓取即時資料"""
        market_data = []
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        try:
            session.get("https://mis.twse.com.tw/stock/index.jsp", headers=headers, timeout=5)
        except: pass
            
        url_base = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={}&json=1&delay=0"
        
        batch_size = 40
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i+batch_size]
            
            channels = []
            for s in batch:
                channels.append(f"tse_{s}.tw")
                channels.append(f"otc_{s}.tw")
            
            ex_ch_str = "|".join(channels)
            url = url_base.format(ex_ch_str)
            
            print(f"   已向 TWSE 請求 {min(i+batch_size, len(stocks))}/{len(stocks)} 檔即時數據...", end='\r')
            
            try:
                res = session.get(url, headers=headers, timeout=10)
                data = res.json()
                
                if 'msgArray' in data and data['msgArray']:
                    for item in data['msgArray']:
                        z_val = str(item.get('z', '-'))
                        y_val = str(item.get('y', '-'))
                        b_val = str(item.get('b', '-'))
                        o_val = str(item.get('o', '-'))
                        h_val = str(item.get('h', '-'))
                        l_val = str(item.get('l', '-'))
                        v_val = str(item.get('v', '-'))
                        c_val = str(item.get('c', 'unknown'))
                        n_val = str(item.get('n', 'unknown'))

                        # 🌟 關鍵修復：如果 z 和 v 都是空的，代表盤後資料已清空，此時千萬不能拿昨收(y)來充數！
                        if z_val == '-' and v_val == '-': 
                            continue
                        
                        try:
                            if z_val != '-':
                                price = float(z_val)
                            elif b_val != '-' and b_val.split('_')[0] != '-':
                                price = float(b_val.split('_')[0])
                            else:
                                continue # 放棄此筆，交給盤後備援引擎處理
                                
                            ref_price = float(y_val) if y_val != '-' else price
                            
                            open_p = float(o_val) if o_val != '-' else price
                            high_p = float(h_val) if h_val != '-' else price
                            low_p = float(l_val) if l_val != '-' else price
                            vol = float(v_val) if v_val != '-' else 0 
                            
                            turnover = price * vol * 1000 
                            change_pct = ((price - ref_price) / ref_price) * 100 if ref_price > 0 else 0
                            avg_p = (high_p + low_p + price) / 3 if high_p > 0 else price
                            
                            # 盤中資料，預設標記為今日
                            actual_date = datetime.now().strftime('%Y-%m-%d')
                            
                            market_data.append({
                                'code': c_val, 'name': n_val, 'price': price,
                                'change_pct': change_pct, 'turnover_val': turnover,
                                'avg_price': avg_p, 'high': high_p, 'low': low_p,
                                'open': open_p, 'volume': vol, 'date': actual_date
                            })
                        except ValueError:
                            pass 
                            
            except Exception as e:
                logger.error(f"TWSE 抓取異常: {e}")
                
            time.sleep(2.5) 
            
        return market_data

    def _fetch_from_local_csv(self, missing_stocks):
        """🌟 從剛剛下載的 TWSE 熱門股 CSV 中提取最精準的官方盤後資料"""
        csv_files = glob.glob("TWSE_HotStocks_*.csv")
        if not csv_files: return []
        
        latest_csv = max(csv_files, key=os.path.getctime)
        # 智能提取檔案中的真實日期
        match = re.search(r'(\d{8})', latest_csv)
        if match:
            date_str = match.group(1)
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        else:
            formatted_date = datetime.now().strftime('%Y-%m-%d')
            
        try:
            df = pd.read_csv(latest_csv)
            df['證券代號'] = df['證券代號'].astype(str)
            
            recovered_data = []
            for s in missing_stocks:
                stock_df = df[df['證券代號'] == s]
                if not stock_df.empty:
                    row = stock_df.iloc[0]
                    price = pd.to_numeric(row.get('收盤價', 0), errors='coerce')
                    if pd.isna(price) or price <= 0: continue
                    
                    ref_price = pd.to_numeric(row.get('昨收', price), errors='coerce')
                    open_p = pd.to_numeric(row.get('開盤價', price), errors='coerce')
                    high_p = pd.to_numeric(row.get('最高價', price), errors='coerce')
                    low_p = pd.to_numeric(row.get('最低價', price), errors='coerce')
                    vol = pd.to_numeric(row.get('成交股數', 0), errors='coerce') / 1000 # 轉為張
                    change_pct = pd.to_numeric(row.get('漲跌幅(%)', 0), errors='coerce')
                    
                    turnover = price * vol * 1000
                    avg_p = (high_p + low_p + price) / 3
                    
                    recovered_data.append({
                        'code': s, 'name': str(row.get('證券名稱', s)),
                        'price': price, 'change_pct': change_pct,
                        'turnover_val': turnover, 'avg_price': avg_p,
                        'high': high_p, 'low': low_p, 'open': open_p, 'volume': vol,
                        'date': formatted_date
                    })
            return recovered_data
        except Exception as e:
            logger.error(f"CSV 備援讀取失敗: {e}")
            return []

    def run_screener(self):
        stocks = self.get_target_stocks()
        print(f"📥 正在透過 TWSE API 抓取 {len(stocks)} 檔即時行情...")
        
        market_data = self._fetch_twse_intraday(stocks)

        # ==========================================
        # 🌟 日夜雙引擎切換：優先使用本地 CSV，再使用 YF
        # ==========================================
        fetched_codes = set(str(row['code']) for row in market_data)
        missing_stocks = [str(s) for s in stocks if str(s) not in fetched_codes]

        if missing_stocks:
            print(f"\n⚠️ TWSE API 盤中快照已清空，共有 {len(missing_stocks)} 檔無資料 (目前為盤後時段)。")
            
            # 1. 優先啟動 CSV 本地備援 (最準確的官方盤後資料)
            print("🔄 啟動【本地盤後資料庫備援】：嘗試讀取今日最新 TWSE CSV...")
            recovered_from_csv = self._fetch_from_local_csv(missing_stocks)
            if recovered_from_csv:
                market_data.extend(recovered_from_csv)
                fetched_codes = set(str(row['code']) for row in market_data)
                missing_stocks = [str(s) for s in stocks if str(s) not in fetched_codes]
                print(f"   ✅ 成功從本地 CSV 補齊 {len(recovered_from_csv)} 檔今日盤後資料！")

            # 2. 若還有缺漏 (例如 OTC 上櫃股票)，啟動 YFinance 備援
            if missing_stocks:
                if yf is None:
                    print("❌ 找不到 yfinance 套件，無法補齊剩餘資料。")
                else:
                    print(f"🔄 啟動【YFinance 備援】：嘗試補齊剩餘 {len(missing_stocks)} 檔收盤資料...")
                    for idx, s in enumerate(missing_stocks):
                        try:
                            ticker = yf.Ticker(f"{s}.TW")
                            hist = ticker.history(period="2d")
                            if hist.empty:
                                ticker = yf.Ticker(f"{s}.TWO")
                                hist = ticker.history(period="2d")
                                
                            if not hist.empty:
                                today_data = hist.iloc[-1]
                                # 🌟 取得資料庫真正的所屬日期
                                actual_date = hist.index[-1].strftime('%Y-%m-%d')
                                
                                price = float(today_data['Close'])
                                vol = float(today_data['Volume']) / 1000 # 轉回張數統一度量衡
                                open_p = float(today_data['Open'])
                                high_p = float(today_data['High'])
                                low_p = float(today_data['Low'])
                                
                                ref_price = float(hist.iloc[-2]['Close']) if len(hist) > 1 else open_p
                                change_pct = ((price - ref_price) / ref_price) * 100 if ref_price > 0 else 0
                                turnover = price * vol * 1000
                                avg_p = (high_p + low_p + price) / 3 if high_p > 0 else price
                                
                                market_data.append({
                                    'code': str(s), 'name': str(s),
                                    'price': price, 'change_pct': change_pct,
                                    'turnover_val': turnover, 'avg_price': avg_p,
                                    'high': high_p, 'low': low_p, 'open': open_p, 'volume': vol,
                                    'date': actual_date
                                })
                        except Exception:
                            pass
                        print(f"   已抓取備援資料: {idx + 1}/{len(missing_stocks)}", end='\r')

        if not market_data:
            print("\n⚠️ 備援模式也無法獲取資料，請檢查網路連線。")
            return

        print(f"\n✅ 掃描完成，共取得 {len(market_data)} 檔有效資料")
        df = pd.DataFrame(market_data)
        picks = []
        for _, row in df.iterrows():
            score = 0
            reasons = []

            if row['change_pct'] > 0:
                score += 30
                reasons.append("紅盤")
            elif row['change_pct'] < -3:
                score -= 20
                
            if row['price'] > row['avg_price']:
                score += 40
                reasons.append("站上均價")
                
            amp = 0
            if row['price'] > 0 and (1 + row['change_pct']/100) > 0:
                yesterday_close = row['price'] / (1 + row['change_pct']/100)
                amp = ((row['high'] - row['low']) / yesterday_close) * 100
                
            if amp > 2:
                score += 10
                reasons.append("振幅>2%")
                
            rank_pct = (df['turnover_val'] > row['turnover_val']).sum() / len(df)
            rank_score = 20 * (1 - rank_pct)
            score += rank_score
            
            if score >= 40: 
                turnover_billion = round(row['turnover_val'] / 100000000, 2)
                picks.append({
                    'Code': row['code'], 'Name': row['name'], 'Price': round(row['price'], 2),
                    'Chg%': round(row['change_pct'], 2), 'Turnover(億)': turnover_billion,
                    'VWAP': round(row['avg_price'], 2), 'Score': int(score), 'Note': " | ".join(reasons)
                })

        final_df = pd.DataFrame(picks)
        if not final_df.empty:
            final_df = final_df.sort_values(by='Score', ascending=False).head(50)
            print(f"✅ 篩選出 {len(final_df)} 檔資金關注焦點。")
            
            selected_codes = final_df['Code'].tolist()
            comma_str = self.export_to_watchlist(selected_codes)
            
            selected_market_data = [row for row in market_data if row['code'] in selected_codes]
            self.sync_kbars_to_db(selected_market_data)
            
            if not redis_db or not getattr(redis_db, 'is_connected', False):
                print("\n" + "="*80)
                print("💡 【戰情室快速接軌區 (如畫面未自動更新請複製貼上)】")
                print(comma_str)
                print("="*80 + "\n")
        else:
            print("⚠️ 目前無符合條件的強勢股。")

    def run_continuously(self, interval_seconds=60):
        print(f"🚀 啟動【盤中自動輪詢模式】(每 {interval_seconds} 秒更新一次)...")
        print("💡 提示：請保持這個黑色終端機視窗開啟，不要關閉它！\n")
        
        while True:
            now = datetime.now()
            current_time = now.time()
            
            start_time = datetime.strptime("08:50", "%H:%M").time()
            end_time = datetime.strptime("13:40", "%H:%M").time()
            
            if now.weekday() >= 5:
                print(f"[{now.strftime('%H:%M:%S')}] 週末不開盤，執行一次快照後程式自動結束。")
                self.run_screener()
                break
                
            if current_time < start_time:
                print(f"[{now.strftime('%H:%M:%S')}] 尚未開盤，等待中 (每分鐘檢查一次)...")
                time.sleep(60)
                continue
                
            if current_time > end_time:
                print(f"[{now.strftime('%H:%M:%S')}] 已經收盤，執行最終結算快照後程式結束。")
                self.run_screener()
                break
                
            print(f"\n[{now.strftime('%H:%M:%S')}] 🔄 開始執行盤中即時掃描...")
            self.run_screener()
            print(f"⏳ 休息 {interval_seconds} 秒後進行下一次資料庫更新...\n")
            time.sleep(interval_seconds)


if __name__ == "__main__":
    screener = ChipsTurnoverScreener()
    
    now = datetime.now()
    is_weekend = now.weekday() >= 5
    is_market_hours = (8 <= now.hour <= 13) or (now.hour == 14 and now.minute <= 30)
    
    if not is_weekend and is_market_hours:
        screener.run_continuously(interval_seconds=60)
    else:
        print("🌙 目前非盤中時間，執行【單次快照模式】...")
        screener.run_screener()