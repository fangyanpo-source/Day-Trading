# 檔案名稱: streamlit_app.py
import streamlit as st
import pandas as pd
import time
from datetime import datetime, time as dt_time
import os
import requests
import pytz
from dotenv import load_dotenv
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from redis_manager import redis_db

# 嘗試匯入回測引擎 (若環境中有 backtest_engine.py 即可啟用回測功能)
try:
    from backtest_engine import TechnicalIndicators, StrategyFactory, BacktestEngine
    BACKTEST_AVAILABLE = True

    # 🌟 覆寫布林+MACD策略 (針對短線交易優化的敏銳版)
    def custom_short_term_bollinger_macd(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 5: return None, "", None
        curr = df.iloc[-1]
        last = df.iloc[-2]
        
        # 第一步：MACD 給「方向」
        macd_golden_cross = (last['MACD_DIF'] <= last['MACD_DEM']) and (curr['MACD_DIF'] > curr['MACD_DEM'])
        hist_short_below_0 = (curr['MACD_OSC'] < 0) and (curr['MACD_OSC'] > last['MACD_OSC'])
        long_direction = macd_golden_cross or hist_short_below_0
        
        macd_death_cross = (last['MACD_DIF'] >= last['MACD_DEM']) and (curr['MACD_DIF'] < curr['MACD_DEM'])
        hist_short_above_0 = (curr['MACD_OSC'] > 0) and (curr['MACD_OSC'] < last['MACD_OSC'])
        short_direction = macd_death_cross or hist_short_above_0
        
        if position == 0:
            # 第二步：布林通道給「位置」
            near_lower = (current_price <= curr['BB_Lower'] * 1.002) or (last['Low'] <= last['BB_Lower'] and current_price > curr['BB_Lower'])
            mid_support = (last['Close'] < last['BB_Mid']) and (current_price >= curr['BB_Mid'])
            
            if (near_lower or mid_support) and long_direction:
                sl = df['BB_Lower'].iloc[-5:].min()
                return "BUY", "做多:布林支撐+MACD轉強", sl
                
            near_upper = (current_price >= curr['BB_Upper'] * 0.998) or (last['High'] >= last['BB_Upper'] and current_price < curr['BB_Upper'])
            mid_resist = (last['Close'] > last['BB_Mid']) and (current_price <= curr['BB_Mid'])
            
            if (near_upper or mid_resist) and short_direction:
                sl = df['BB_Upper'].iloc[-5:].max()
                return "SHORT", "做空:布林受阻+MACD轉弱", sl
                
        elif position > 0:
            reach_upper = current_price >= curr['BB_Upper']
            break_mid_down = (last['Close'] >= last['BB_Mid']) and (current_price < curr['BB_Mid'])
            momentum_weakens = curr['MACD_OSC'] < last['MACD_OSC']
            if reach_upper or break_mid_down or momentum_weakens:
                return "SELL", "平多:觸軌/破中軌/動能衰退", None
                
        elif position < 0:
            reach_lower = current_price <= curr['BB_Lower']
            break_mid_up = (last['Close'] <= last['BB_Mid']) and (current_price > curr['BB_Mid'])
            momentum_weakens = curr['MACD_OSC'] > last['MACD_OSC']
            if reach_lower or break_mid_up or momentum_weakens:
                return "COVER", "平空:觸軌/破中軌/動能衰退", None
                
        return None, "", None

    StrategyFactory.strategy_13_bollinger_macd_combo = custom_short_term_bollinger_macd

except ImportError:
    BACKTEST_AVAILABLE = False

load_dotenv()
ENV_TRADE_MODE = os.getenv("TRADE_MODE", "PAPER").upper()
TRADE_MODE = redis_db.get_flag("system:config:trade_mode") or ENV_TRADE_MODE
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", -20000))

STRATEGY_MAP = {
    "strategy_01_momentum_breakout": "🟢 動能突破策略",
    "strategy_02_orb_breakout": "🟢 開盤區間突破(ORB)",
    "strategy_03_gap_play": "🟢 跳空缺口交易",
    "strategy_04_mean_reversion_long": "🟢 均值回歸做多",
    "strategy_05_vwap_bounce": "🟢 VWAP 均價策略",
    "strategy_06_fast_ma_cross": "🟢 快速均線策略",
    "strategy_07_trend_weakness_short": "🔴 空方轉弱策略",
    "strategy_08_rebound_fail_short": "🔴 反彈不過前高",
    "strategy_09_mean_reversion_short": "🔴 均值回歸做空",
    "strategy_10_rsi_divergence_short": "🔴 籌碼/指標背離",
    "strategy_11_macd_cross_dual": "⚖️ MACD 交叉",
    "strategy_12_kd_cross_dual": "⚖️ KD 交叉",
    "strategy_13_bollinger_macd_combo": "⚖️ 布林+MACD 雙重確認",
    "strategy_14_rolling_breakout_dual": "⚖️ 均線/通道突破",
    "strategy_15_rsi_contrarian_dual": "⚖️ RSI 逆勢交易"
}

st.set_page_config(page_title="風林火山 - 量化戰情室 Pro", layout="wide", page_icon="📈", initial_sidebar_state="expanded")

hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;} footer {visibility: hidden;}
            .block-container { padding-top: 2.5rem; padding-bottom: 1rem; max-width: 95%; }
            div[data-testid="metric-container"] { 
                background-color: #f0f2f6; border-radius: 8px; padding: 10px 15px; 
                box-shadow: 1px 1px 3px rgba(0,0,0,0.05); border-left: 4px solid #3b82f6;
            }
            @media (prefers-color-scheme: dark) { 
                div[data-testid="metric-container"] { 
                    background-color: #1a1c24; border: 1px solid #2d303e; border-left: 4px solid #3b82f6; box-shadow: none; 
                } 
            }
            button[data-baseweb="tab"] { font-size: 1.05rem !important; font-weight: bold; }
            div[data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: bold; }
            div[data-testid="stMetricLabel"] { font-size: 1.0rem !important; }
            div[data-testid="stMetricDelta"] { font-size: 0.9rem !important; }
            div.row-widget.stRadio > div { gap: 15px; }
            h1 { font-size: 2.2rem !important; }
            h2 { font-size: 1.8rem !important; }
            h3 { font-size: 1.4rem !important; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

if "watch_pool_text" not in st.session_state:
    initial_pool = redis_db.get_json("system:config:watch_pool") or ["2330", "2603", "2317"]
    st.session_state.watch_pool_text = ", ".join(initial_pool)

# ==========================================
# 全域資料快取函數區
# ==========================================
@st.cache_resource
def get_fubon_sdk():
    fubon_id = os.getenv("FUBON_ID")
    fubon_pass = os.getenv("FUBON_PASSWORD")
    cert_path = os.getenv("FUBON_CERT_PATH")
    cert_pass = os.getenv("FUBON_CERT_PASS")
    if not all([fubon_id, fubon_pass, cert_path, cert_pass]): return None
    try:
        from fubon_neo.sdk import FubonSDK
        sdk = FubonSDK()
        sdk.login(fubon_id, fubon_pass, cert_path, cert_pass)
        return sdk
    except: return None

@st.cache_data(ttl=600, show_spinner=False)
def fetch_base_stock_info(pool):
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        res = requests.get(url, timeout=5).json()
        return {item['Code']: item for item in res}
    except: return {}

@st.cache_data(ttl=5, show_spinner=False)
def fetch_fubon_snapshots(pool):
    sdk = get_fubon_sdk()
    if not sdk: return {}
    snapshots = {}
    for code in pool:
        try:
            res = sdk.marketdata.rest_client.stock.intraday.quote(symbol=code)
            if res and res.data:
                snapshots[code] = res.data[0] if isinstance(res.data, list) else res.data
        except: pass
    return snapshots

@st.cache_data(ttl=30, show_spinner=False)
def fetch_kline_data(symbol, period, interval):
    """
    🌟 數據源升級：Hybrid K線快取引擎 (yfinance 歷史 + 富邦 API 即時零延遲)
    """
    try:
        df_yf = yf.download(f"{symbol}.TW", period=period, interval=interval, progress=False)
        if df_yf.empty: 
            df_yf = yf.download(f"{symbol}.TWO", period=period, interval=interval, progress=False)
            
        if not df_yf.empty:
            if isinstance(df_yf.columns, pd.MultiIndex): df_yf.columns = df_yf.columns.droplevel(1)
            if df_yf.index.tz is None: df_yf.index = df_yf.index.tz_localize('UTC').tz_convert('Asia/Taipei')
            else: df_yf.index = df_yf.index.tz_convert('Asia/Taipei')
            df_yf = df_yf.dropna(subset=['Close'])
        
        sdk = get_fubon_sdk()
        if sdk and interval in ['1m', '5m', '60m', '1h']:
            tf_map = {'1m': '1', '5m': '5', '60m': '60', '1h': '60'}
            try:
                fubon_res = sdk.marketdata.rest_client.stock.intraday.candles(symbol=symbol, timeframe=tf_map[interval])
                if fubon_res and fubon_res.data:
                    df_fb = pd.DataFrame(fubon_res.data)
                    df_fb['date'] = pd.to_datetime(df_fb['date'])
                    
                    if df_fb['date'].dt.tz is None:
                        df_fb['date'] = df_fb['date'].dt.tz_localize('Asia/Taipei')
                    else:
                        df_fb['date'] = df_fb['date'].dt.tz_convert('Asia/Taipei')
                        
                    df_fb = df_fb.set_index('date')
                    df_fb = df_fb.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
                    
                    if not df_yf.empty:
                        today_str = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d')
                        df_yf = df_yf[df_yf.index.strftime('%Y-%m-%d') != today_str]
                        df_final = pd.concat([df_yf, df_fb[df_fb.index.strftime('%Y-%m-%d') == today_str]])
                    else:
                        df_final = df_fb
                else:
                    df_final = df_yf
            except Exception as e:
                df_final = df_yf
        else:
            df_final = df_yf

        if not df_final.empty and len(df_final) > 0:
            df_final['SMA_5'] = df_final['Close'].rolling(window=5, min_periods=1).mean()
            df_final['SMA_10'] = df_final['Close'].rolling(window=10, min_periods=1).mean()
            
            df_final['SMA_12'] = df_final['Close'].rolling(window=12, min_periods=1).mean()
            df_final['BB_Std'] = df_final['Close'].rolling(window=12, min_periods=1).std()
            df_final['BB_Upper'] = df_final['SMA_12'] + (df_final['BB_Std'] * 2)
            df_final['BB_Lower'] = df_final['SMA_12'] - (df_final['BB_Std'] * 2)
            
            df_final['EMA_fast'] = df_final['Close'].ewm(span=6, adjust=False).mean()
            df_final['EMA_slow'] = df_final['Close'].ewm(span=19, adjust=False).mean()
            df_final['MACD_DIF'] = df_final['EMA_fast'] - df_final['EMA_slow']
            df_final['MACD_DEM'] = df_final['MACD_DIF'].ewm(span=6, adjust=False).mean()
            df_final['MACD_OSC'] = df_final['MACD_DIF'] - df_final['MACD_DEM']
            
            df_final['Color'] = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(df_final['Close'], df_final['Open'])]
            df_final['MACD_Color'] = ['#ef5350' if m >= 0 else '#26a69a' for m in df_final['MACD_OSC']]
            
        return df_final
    except Exception as e:
        st.error(f"K線圖資料獲取失敗: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def fetch_twse_hot_stocks():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        res = requests.get(url, timeout=10).json()
        hot_stocks = []
        for stock in res:
            code = stock.get("Code", "")
            if len(code) != 4 or code.startswith('0'): continue
            try:
                # 🌟 關鍵修復：去除千分位逗號，避免 ValueError 導致所有熱門股票被剔除
                c_str = str(stock.get("ClosingPrice", "0")).replace(',', '')
                h_str = str(stock.get("HighestPrice", "0")).replace(',', '')
                l_str = str(stock.get("LowestPrice", "0")).replace(',', '')
                v_str = str(stock.get("TradeVolume", "0")).replace(',', '')
                
                c = float(c_str) if c_str else 0.0
                h = float(h_str) if h_str else 0.0
                l = float(l_str) if l_str else 0.0
                vol = float(v_str) / 1000 if v_str else 0.0 
                
                if c < 10 or vol < 2000: continue
                amp = (h - l) / c if c > 0 else 0
                if amp < 0.02: continue
                
                hot_stocks.append({"code": code, "vol": vol})
            except Exception:
                continue
                
        hot_stocks = sorted(hot_stocks, key=lambda x: x['vol'], reverse=True)[:100]
        return [s["code"] for s in hot_stocks]
    except Exception as e:
        return []

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

def safe_int(v):
    try: return int(v) if v is not None else None
    except: return None

tz = pytz.timezone('Asia/Taipei')
now = datetime.now(tz)
is_market_open = now.weekday() < 5 and (dt_time(8, 0) <= now.time() <= dt_time(13, 30))

# ==========================================
# 側邊欄：重要風控與控制中樞
# ==========================================
st.sidebar.title("⚙️ 系統控制中樞")

weekdays = ["一", "二", "三", "四", "五", "六", "日"]
st.sidebar.markdown(f"""
    <div style="background-color: #111; padding: 15px; border-radius: 10px; text-align: center; border: 1px solid #333; margin-bottom: 15px;">
        <div style="color: #888; font-size: 13px; margin-bottom: 5px;">台股交易時間</div>
        <div style="color: #00ffcc; font-size: 32px; font-weight: bold; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;">{now.strftime('%H:%M:%S')}</div>
        <div style="color: #aaa; font-size: 12px; margin-top: 5px;">{now.strftime('%Y-%m-%d')} (星期{weekdays[now.weekday()]})</div>
    </div>
""", unsafe_allow_html=True)

st.sidebar.subheader("💱 交易模式切換")
mode_idx = 1 if TRADE_MODE == "LIVE" else 0
selected_mode_label = st.sidebar.radio("選擇大腦運作模式：", ["🟢 模擬測試 (PAPER)", "🔴 實盤交易 (LIVE)"], index=mode_idx, help="切換後將即時同步至策略大腦")
new_mode_flag = "LIVE" if "LIVE" in selected_mode_label else "PAPER"
if new_mode_flag != TRADE_MODE:
    redis_db.set_flag("system:config:trade_mode", new_mode_flag)
    st.rerun()

st.sidebar.divider()
auto_refresh = st.sidebar.toggle("⏱️ 啟動畫面即時更新\n(僅限【盤中交易面板】)", value=True)

st.sidebar.divider()
st.sidebar.subheader("🚨 緊急風控面板")
is_paused = redis_db.get_flag("system:flag:pause_entries") == "1"
if st.sidebar.button("▶️ 恢復新單進場" if is_paused else "⏸️ 暫停新單進場", use_container_width=True):
    redis_db.set_flag("system:flag:pause_entries", "0" if is_paused else "1")
    st.rerun()

st.sidebar.markdown("<br>", unsafe_allow_html=True)
if st.sidebar.button("🔥 一鍵市價全平倉", type="primary", use_container_width=True):
    redis_db.set_flag("system:flag:manual_close_all", "1", expire_sec=60)
    st.sidebar.success("已發送全平倉指令！")

# ==========================================
# 主畫面區塊：緊湊型 KPI 儀表板
# ==========================================
st.markdown("<h1>📈 風林火山 - 日內量化戰情室 Pro</h1>", unsafe_allow_html=True)

pnl_str = redis_db.get_flag("system:data:realized_pnl") or redis_db.get_flag("system:mock:pnl")
realized_pnl = float(pnl_str) if pnl_str else 0.0
positions = redis_db.get_json("system:data:positions") or {}

total_unrealized_pnl = 0.0
pos_list = []
for sym, details in positions.items():
    buy_price, qty = details.get("entry_price", 0), abs(details.get("position", 0))
    current_trade = redis_db.get_json(f"market:trades:{sym}")
    current_price = current_trade.get("price", buy_price) if current_trade else buy_price
    unrealized = (current_price - buy_price) * qty if details.get("position", 0) > 0 else (buy_price - current_price) * qty
    total_unrealized_pnl += unrealized
    raw_strategy = details.get("strategy_code", details.get("strategy", ""))
    chinese_strategy = STRATEGY_MAP.get(raw_strategy, raw_strategy)
    pos_list.append({"標的": sym, "方向": "多單" if details.get("position", 0) > 0 else "空單", "數量": qty, "策略": chinese_strategy, "成本價": f"{buy_price:.2f}", "現價": f"{current_price:.2f}", "停損": f"{details.get('stop_loss_price', 0):.2f}", "未實現損益": f"NT$ {unrealized:,.0f}"})

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("💰 今日已實現淨利", f"NT$ {realized_pnl:,.0f}")
col_m2.metric("📊 當前未實現損益", f"NT$ {total_unrealized_pnl:,.0f}", delta=f"{total_unrealized_pnl:,.0f}")
col_m3.metric("💼 活躍部位數量", f"{len(positions)} 檔")
col_m4.metric("🛡️ 距離熔斷額度", f"NT$ {(abs(MAX_DAILY_LOSS) + realized_pnl):,.0f}")

if realized_pnl < 0: 
    st.progress(min(abs(realized_pnl) / abs(MAX_DAILY_LOSS), 1.0), text=f"⚠️ 每日虧損限額使用率 (上限: {abs(MAX_DAILY_LOSS):,.0f})")

st.markdown("---")

nav_options = ["🔥 盤中交易面板", "📈 K線圖與回測", "💼 庫存與即時訊號", "💰 成交回報與行情", "⚙️ 選股與策略設定"]
selected_tab = st.radio("系統導航", nav_options, horizontal=True, label_visibility="collapsed")
st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

# ------------------------------------------
# 分頁 1: 盤中交易面板 (雷達清單與微結構深度 雙拼佈局)
# ------------------------------------------
if selected_tab == "🔥 盤中交易面板":
    if redis_db.get_flag("system:flag:kill_switch") == "1": st.error("🚨 【全局熔斷機制已啟動】 系統鎖定，為保護資金已拒絕所有新委託！ 🚨")
    if redis_db.get_flag("system:flag:manual_close_all") == "1": st.warning("⚠️ 正在執行手動一鍵全平倉程序...")
    if is_paused: st.warning("⏸️ 目前已手動暫停新單進場，大腦僅維持現有部位的停損與停利！")
        
    current_pool = redis_db.get_json("system:config:watch_pool") or ["2330", "2603", "2317"]

    def build_radar_df():
        base_info = fetch_base_stock_info(current_pool)
        fubon_snaps = fetch_fubon_snapshots(current_pool)
        global_mode = redis_db.get_flag("system:config:signal_mode") or "CONSENSUS"
        mode_str = "共識模式" if global_mode == "CONSENSUS" else "首發模式"
        
        radar_data = []
        for code in current_pool:
            if len(code) != 4 or code.startswith('0'): continue
            info = base_info.get(code, {})
            name = info.get('Name', '-')
            trade = redis_db.get_json(f"market:trades:{code}") or {}
            book = redis_db.get_json(f"market:books:{code}") or {}
            
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            bid_price = bids[0]['price'] if bids and isinstance(bids, list) and len(bids) > 0 else None
            ask_price = asks[0]['price'] if asks and isinstance(asks, list) and len(asks) > 0 else None
            
            last_price, tick_vol, total_vol, change_val, amp_val = None, trade.get('size', None), None, None, None
            snap = fubon_snaps.get(code)
            
            def apply_fubon_snap():
                nonlocal last_price, total_vol, change_val, amp_val
                if snap:
                    try:
                        lp = getattr(snap, 'closePrice', getattr(snap, 'close', None))
                        tv = getattr(snap, 'totalVolume', getattr(snap, 'volume', None))
                        op = getattr(snap, 'openPrice', getattr(snap, 'open', 0))
                        hp = getattr(snap, 'highPrice', getattr(snap, 'high', 0))
                        low_p = getattr(snap, 'lowPrice', getattr(snap, 'low', 0))
                        if lp is not None: last_price = lp
                        if tv is not None: total_vol = tv
                        if op and op > 0 and last_price is not None:
                            change_val = round(float(last_price) - float(op), 2)
                            amp_val = round(((float(hp) - float(low_p)) / float(op)) * 100, 2)
                    except: pass
            
            def apply_twse_info():
                nonlocal last_price, total_vol, change_val, amp_val
                if info:
                    try:
                        last_str = str(info.get('ClosingPrice', '')).replace(',', '')
                        if last_str: last_price = float(last_str)
                        vol_str = str(info.get('TradeVolume', '')).replace(',', '')
                        if vol_str: total_vol = int(vol_str) // 1000
                        open_str = str(info.get('OpeningPrice', '')).replace(',', '')
                        high_str = str(info.get('HighestPrice', '')).replace(',', '')
                        low_str = str(info.get('LowestPrice', '')).replace(',', '')
                        op = float(open_str) if open_str else last_price
                        hp = float(high_str) if high_str else last_price
                        low_p = float(low_str) if low_str else last_price
                        if op and op > 0 and last_price is not None:
                            change_val = round(float(last_price) - float(op), 2)
                            amp_val = round(((float(hp) - float(low_p)) / float(op)) * 100, 2)
                    except: pass

            if is_market_open:
                apply_fubon_snap()
                if last_price is None: last_price = trade.get('price', None)
                if total_vol is None: total_vol = trade.get('volume', None)
            else:
                apply_twse_info()
                if last_price is None or last_price == 0: apply_fubon_snap()

            final_vol = safe_int(total_vol)
            if final_vol is None or final_vol < 2000: continue

            radar_data.append({
                "商品名稱": name, "代碼": code, "買進價": safe_float(bid_price), "賣出價": safe_float(ask_price),
                "成交價": safe_float(last_price), "漲跌": safe_float(change_val), "振幅%": safe_float(amp_val),
                "單量": safe_int(tick_vol), "總量": final_vol, "全局模式": mode_str
            })

        df_radar = pd.DataFrame(radar_data)
        if not df_radar.empty:
            def color_pct(val):
                if isinstance(val, (int, float)) and pd.notna(val):
                    if val > 0: return 'color: #ef5350; font-weight:bold;'
                    elif val < 0: return 'color: #26a69a; font-weight:bold;'
                return ''
            return df_radar.style.map(color_pct, subset=['漲跌', '振幅%']), len(df_radar)
        return None, 0

    status_label = "🟡 盤中即時 (API 連線中)" if is_market_open else "🔵 盤後資料 (TWSE 官方收盤)"
    styled_df, valid_count = build_radar_df()

    col_radar, col_orderbook = st.columns([1.6, 1.0])

    with col_radar:
        st.markdown(f"**📡 雷達鎖定標的 ({valid_count} 檔) - {status_label}** *(已隱藏無量標的)*")
        if styled_df is not None: 
            st.dataframe(styled_df, use_container_width=True, hide_index=True, height=350)
        else: 
            st.info("尚無符合條件的監控資料。")

    with col_orderbook:
        st.markdown("**🔍 個股微結構與五檔深度**")
        if valid_count > 0:
            valid_codes = [s for s in current_pool if s in styled_df.data['代碼'].values]
            selected_ob_sym = st.selectbox("選擇微結構監控標的", valid_codes if valid_codes else current_pool, label_visibility="collapsed")
        else:
            selected_ob_sym = st.selectbox("選擇微結構監控標的", current_pool, label_visibility="collapsed")
            
        book_data = redis_db.get_json(f"market:books:{selected_ob_sym}")
        if book_data and 'bids' in book_data and 'asks' in book_data:
            bids = book_data.get('bids', [])
            asks = book_data.get('asks', [])
            
            if bids and asks:
                bids_df = pd.DataFrame(bids)
                asks_df = pd.DataFrame(asks)
                
                total_bid_vol = bids_df['size'].sum() if 'size' in bids_df.columns else 0
                total_ask_vol = asks_df['size'].sum() if 'size' in asks_df.columns else 0
                total_vol = total_bid_vol + total_ask_vol
                
                if total_vol > 0:
                    bid_ratio = (total_bid_vol / total_vol) * 100
                    st.markdown(f"**買賣力道失衡 (Imbalance): 委買 {bid_ratio:.1f}% vs 委賣 {100-bid_ratio:.1f}%**")
                    st.progress(bid_ratio / 100.0)
                
                fig_ob = go.Figure()
                fig_ob.add_trace(go.Bar(
                    x=bids_df['price'][::-1] if 'price' in bids_df.columns else [],
                    y=bids_df['size'][::-1] if 'size' in bids_df.columns else [],
                    name='委買 (Bid)', marker_color='#ef5350', opacity=0.8
                ))
                fig_ob.add_trace(go.Bar(
                    x=asks_df['price'] if 'price' in asks_df.columns else [],
                    y=asks_df['size'] if 'size' in asks_df.columns else [],
                    name='委賣 (Ask)', marker_color='#26a69a', opacity=0.8
                ))
                fig_ob.update_layout(
                    height=260, margin=dict(l=10, r=10, t=10, b=10),
                    template="plotly_dark", barmode='group',
                    xaxis_title="價格", yaxis_title="掛單張數",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_ob, use_container_width=True)
        else:
            st.caption("等待行情接入或目前無五檔資料...")

# ------------------------------------------
# 分頁 2: 專業級圖表與歷史回測
# ------------------------------------------
elif selected_tab == "📈 K線圖與回測":
    st.subheader("🎯 圖表與標的設定")
    col_chart_ctl, col_chart_opt, _ = st.columns([1.5, 2.5, 2])
    
    with col_chart_ctl:
        chart_pool = redis_db.get_json("system:config:watch_pool") or ["2330", "2603", "2317"]
        selected_chart_sym = st.selectbox("選擇圖表監控標的", chart_pool)
    with col_chart_opt:
        time_range = st.radio("選擇 K 棒範圍 (支援滑鼠滾輪與框選拖曳自由縮放)", 
                              ["1分K", "5分K", "1小時K", "1日K"], horizontal=True, index=0)
        
        if time_range == "1分K": p_val, i_val = "1d", "1m" 
        elif time_range == "5分K": p_val, i_val = "5d", "5m"
        elif time_range == "1小時K": p_val, i_val = "1mo", "1h"
        else: p_val, i_val = "1y", "1d"

    st.markdown("---")
    st.subheader("🧪 策略歷史回測 (支援複式條件與動態停利)")

    col_bt1, col_bt2 = st.columns([2.5, 1.5])
    with col_bt1:
        bt_strats = st.multiselect("選擇回測策略 (可複選)", list(STRATEGY_MAP.keys()), default=["strategy_13_bollinger_macd_combo"], format_func=lambda x: STRATEGY_MAP.get(x))
    with col_bt2:
        bt_signal_mode = st.selectbox("訊號派發模式", ["🤝 共識模式 (雙重確認)", "⚡ 首發模式 (先到先贏)"], index=0)

    with st.expander("⚙️ 進階風控與停利參數設定 (分批停利/移動停利)", expanded=False):
        col_adv1, col_adv2 = st.columns(2)
        with col_adv1:
            enable_scale_out = st.checkbox("啟用分批停利 (獲利達標先平倉一半)", value=True)
            scale_out_target_pct = st.number_input("分批停利觸發門檻 (%)", value=2.0, step=0.5, format="%.1f")
        with col_adv2:
            enable_trailing_stop = st.checkbox("啟用移動停利 (跟隨最高點回落)", value=True)
            trailing_activation_pct = st.number_input("移動停利啟動門檻 (%)", value=3.0, step=0.5, format="%.1f")
            trailing_drop_pct = st.number_input("最高點回落出場幅度 (%)", value=1.5, step=0.1, format="%.1f")

    col_b1, col_b2, _ = st.columns([1, 1, 2])
    with col_b1:
        bt_period = st.selectbox("回測資料長度", ["1d", "5d", "1mo", "60d", "1y"], index=0)
    with col_b2:
        st.markdown("<br>", unsafe_allow_html=True)
        do_backtest = st.button("🚀 開始運算", use_container_width=True)

    bt_summary = None
    bt_engine = None
    display_period = bt_period if do_backtest else p_val
    df_kline = fetch_kline_data(selected_chart_sym, display_period, i_val)

    if do_backtest and BACKTEST_AVAILABLE and not df_kline.empty:
        if not bt_strats:
            st.warning("請至少選擇一個回測策略！")
        else:
            with st.spinner(f"正在對 {selected_chart_sym} 執行進階回測..."):
                bt_df = TechnicalIndicators.add_all_indicators(df_kline.copy(), bb_period=12, bb_std=2.0, macd_fast=6, macd_slow=19, macd_signal=6)
                mode_val = "CONSENSUS" if "共識" in bt_signal_mode else "FIRST_TRIGGER"
                
                def multi_strat_func(df_slice, current_price, position, **kwargs):
                    buy_signals, sell_signals, short_signals, cover_signals = [], [], [], []
                    for strat_name in bt_strats:
                        strat_func = getattr(StrategyFactory, strat_name, None)
                        if not strat_func: continue
                        res = strat_func(df_slice, current_price, position, book_data=None, **kwargs)
                        if not res or not res[0]: continue
                        
                        a, r = res[0], res[1]
                        sl = res[2] if len(res) == 3 else None
                        
                        if a == "BUY": buy_signals.append((a, r, sl))
                        elif a == "SELL": sell_signals.append((a, r, sl))
                        elif a == "SHORT": short_signals.append((a, r, sl))
                        elif a == "COVER": cover_signals.append((a, r, sl))

                    for exits in [sell_signals, cover_signals]:
                        if exits: return exits[0][0], exits[0][1], exits[0][2]

                    if mode_val == "FIRST_TRIGGER":
                        for entries in [buy_signals, short_signals]:
                            if entries: return entries[0][0], entries[0][1], entries[0][2]
                    elif mode_val == "CONSENSUS":
                        threshold = 2 if len(bt_strats) >= 2 else 1
                        for entries in [buy_signals, short_signals]:
                            if len(entries) >= threshold:
                                combined_reason = "共識: " + " & ".join([s[1] for s in entries])
                                sl_list = [s[2] for s in entries if s[2] is not None]
                                final_sl = max(sl_list) if entries[0][0] == "BUY" else min(sl_list) if sl_list else None
                                return entries[0][0], combined_reason, final_sl
                    return None, "", None

                bt_engine = BacktestEngine(
                    bt_df, initial_capital=1000000, verbose=False, force_close_time="13:20",
                    enable_scale_out=enable_scale_out, scale_out_target_pct=scale_out_target_pct / 100.0,
                    enable_trailing_stop=enable_trailing_stop, trailing_activation_pct=trailing_activation_pct / 100.0,
                    trailing_drop_pct=trailing_drop_pct / 100.0
                )
                
                bt_summary = bt_engine.run(multi_strat_func)
                st.success("✅ 回測完成！進出場點已標示於下方 K 線圖。")
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("交易次數", f"{bt_summary['Total_Trades']} 次")
                sc2.metric("勝率", f"{bt_summary['Win_Rate']}%")
                sc3.metric("獲利因子 (Profit Factor)", f"{bt_summary['Profit_Factor']}")
                sc4.metric("最大回撤 (MDD)", f"{bt_summary['Max_Drawdown_%']}%")
                st.info(f"💰 總淨利: NT$ {bt_summary['Net_Profit']:,.0f} (總報酬率: {bt_summary['Total_Return_Pct']}%) | 夏普值: {bt_summary['Sharpe_Ratio']}")

    elif do_backtest and df_kline.empty:
        st.error("獲取回測歷史資料失敗。")

    if selected_chart_sym and not df_kline.empty:
        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True, 
            vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2],
            specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]]
        )

        fig.add_trace(go.Candlestick(x=df_kline.index, open=df_kline['Open'], high=df_kline['High'], low=df_kline['Low'], close=df_kline['Close'], name="K線", increasing_line_color='#ef5350', decreasing_line_color='#26a69a'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['SMA_5'], line=dict(color='yellow', width=1), name='5MA'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['SMA_10'], line=dict(color='orange', width=1), name='10MA'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['SMA_12'] if 'SMA_12' in df_kline.columns else df_kline['SMA_20'], line=dict(color='magenta', width=1), name='12MA(BB中軌)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['BB_Upper'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1, dash='dash'), name='BB 上軌'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['BB_Lower'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1, dash='dash'), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.05)', name='BB 下軌'), row=1, col=1)

        if bt_engine:
            if bt_engine.buy_markers:
                bx, by = zip(*bt_engine.buy_markers)
                fig.add_trace(go.Scatter(x=bx, y=by, mode='markers', marker=dict(symbol='triangle-up', size=16, color='#00ffcc', line=dict(width=1, color='black')), name='回測買進 🔺'), row=1, col=1)
            if bt_engine.sell_markers:
                sx, sy = zip(*bt_engine.sell_markers)
                fig.add_trace(go.Scatter(x=sx, y=sy, mode='markers', marker=dict(symbol='triangle-down', size=16, color='#ff3366', line=dict(width=1, color='black')), name='回測賣出 🔻'), row=1, col=1)

        trade_times, trade_prices, trade_texts = [], [], []
        if redis_db.client:
            for key in redis_db.client.keys("system:data:fill_*"):
                fill = redis_db.get_json(key)
                if fill and fill.get("symbol") == selected_chart_sym:
                    dt = pd.to_datetime(fill.get("timestamp"), unit='s').tz_localize('UTC').tz_convert('Asia/Taipei')
                    trade_times.append(dt)
                    trade_prices.append(fill.get("price"))
                    trade_texts.append(f"{fill.get('qty')}股")
        
        if trade_times:
            fig.add_trace(go.Scatter(x=trade_times, y=trade_prices, mode='markers', marker=dict(symbol='diamond', size=14, color='#FFD700', line=dict(width=1, color='white')), text=trade_texts, hoverinfo='text+x+y', name='實盤進出場 💎'), row=1, col=1)

        fig.add_trace(go.Bar(x=df_kline.index, y=df_kline['Volume'], marker_color=df_kline['Color'], name='成交量'), row=2, col=1)
        fig.add_trace(go.Bar(x=df_kline.index, y=df_kline['MACD_OSC'], marker_color=df_kline['MACD_Color'], name='MACD 柱'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['MACD_DIF'], line=dict(color='cyan', width=1), name='DIF'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df_kline.index, y=df_kline['MACD_DEM'], line=dict(color='orange', width=1), name='DEM'), row=3, col=1)

        rangebreaks = [dict(bounds=["sat", "mon"])] 
        if i_val in ["1m", "5m"]: rangebreaks.append(dict(bounds=[13.5, 9], pattern="hour"))
        fig.update_xaxes(rangebreaks=rangebreaks)

        curr_trade = redis_db.get_json(f"market:trades:{selected_chart_sym}")
        curr_price = curr_trade.get('price') if curr_trade else None
        pos_info = positions.get(selected_chart_sym)

        if pos_info:
            entry = pos_info.get('entry_price')
            sl = pos_info.get('stop_loss_price')
            is_long = pos_info.get('position', 0) > 0
            if entry: fig.add_hline(y=entry, line_dash="solid", line_color="#3b82f6" if is_long else "#eab308", annotation_text=f"成本: {entry:.2f}", annotation_position="top left", row=1, col=1)
            if sl: fig.add_hline(y=sl, line_dash="dash", line_color="#ef4444", annotation_text=f"防守線: {sl:.2f}", annotation_position="bottom left", row=1, col=1)

        if curr_price: fig.add_hline(y=curr_price, line_dash="dot", line_color="#10b981", annotation_text=f"現價: {curr_price:.2f}", annotation_position="right", row=1, col=1)

        fig.update_layout(
            height=750, margin=dict(l=10, r=10, t=40, b=10),
            xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False, xaxis3_rangeslider_visible=False,
            dragmode="zoom", template="plotly_dark", title=f"{selected_chart_sym} 專業技術分析",
            showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        fig.update_yaxes(title_text="價格", row=1, col=1)
        fig.update_yaxes(title_text="成交量", row=2, col=1)
        fig.update_yaxes(title_text="MACD", row=3, col=1)
        st.plotly_chart(fig, use_container_width=True)
            
    elif selected_chart_sym: st.caption(f"未能載入 {selected_chart_sym} 的 K 線資料，請確認該標的代碼是否正確。")

# ------------------------------------------
# 分頁 3: 庫存與訊號
# ------------------------------------------
elif selected_tab == "💼 庫存與即時訊號":
    col3a, col3b = st.columns([1.5, 1])
    with col3a:
        st.subheader("💼 當前持倉明細")
        if pos_list:
            df_pos = pd.DataFrame(pos_list)
            st.dataframe(df_pos.style.map(lambda val: f'color: {"#28a745" if float(val.split(" ")[1].replace(",",""))>0 else "#dc3545"}; font-weight:bold' if "NT$" in str(val) else '', subset=['未實現損益']), use_container_width=True, hide_index=True)
        else: st.info("目前空手。")
    with col3b:
        st.subheader("🎯 最新委託 Watchlist")
        watchlist = redis_db.get_json("system:data:daily_watchlist")
        if watchlist: st.dataframe(pd.DataFrame([{"標的": sym, "動作": v.get("action"), "數量": v.get("qty")} for sym, v in watchlist.items()]), use_container_width=True, hide_index=True)

# ------------------------------------------
# 分頁 4: 成交回報與行情
# ------------------------------------------
elif selected_tab == "💰 成交回報與行情":
    col4a, col4b = st.columns([1.5, 1])
    with col4a:
        st.subheader("💰 今日成交回報 (Fills)")
        fill_keys = redis_db.client.keys("system:data:fill_*") if redis_db.client else []
        if fill_keys:
            fill_data = []
            for key in fill_keys:
                fill = redis_db.get_json(key)
                if fill:
                    fill_time = datetime.fromtimestamp(fill.get("timestamp", time.time())).strftime('%H:%M:%S')
                    fill_data.append({"時間": fill_time, "標的": fill.get("symbol", ""), "成交價": fill.get("price", None), "數量": fill.get("qty", None), "類型": fill.get("type", "真實")})
            df_fills = pd.DataFrame(fill_data).sort_values(by="時間", ascending=False)
            st.dataframe(df_fills, use_container_width=True, hide_index=True)
        else:
            st.write("今日尚無成交紀錄。")
            
    with col4b:
        st.subheader("📡 行情心跳 (Ticks)")
        market_keys = redis_db.client.keys("market:trades:*") if redis_db.client else []
        market_data = [{"標的": key.split(":")[-1], "現價": redis_db.get_json(key).get("price", None), "單量": redis_db.get_json(key).get("size", None)} for key in market_keys if redis_db.get_json(key)]
        if market_data: st.dataframe(pd.DataFrame(market_data), use_container_width=True, hide_index=True)
        else: st.caption("等待行情接入...")

# ------------------------------------------
# 分頁 5: 選股與策略設定
# ------------------------------------------
elif selected_tab == "⚙️ 選股與策略設定":
    st.subheader("🛠️ 選股清單與策略大腦設定")
    if st.button("🔄 自動抓取 TWSE 熱門股並立即套用 (量大/高振幅)", type="primary"):
        fetch_twse_hot_stocks.clear()
        with st.spinner("正在從 TWSE 獲取最新大盤資料，並同步至大腦..."):
            hot_codes = fetch_twse_hot_stocks()
            if hot_codes:
                # 🌟 1. 強制過濾並截斷至安全連線數量 (95檔)，保護 API 不被斷線
                safe_pool = [s.strip() for s in hot_codes if len(s.strip()) == 4 and not s.strip().startswith('0')][:95]
                
                # 🌟 2. 更新 UI 文字框顯示
                st.session_state.watch_pool_text = ", ".join(safe_pool)
                
                # 🌟 3. 核心修復：直接將新名單寫入 Redis，省去手動按儲存的步驟！
                redis_db.set_json("system:config:watch_pool", safe_pool)
                
                st.success(f"✅ 成功抓取 {len(safe_pool)} 檔熱門股，並已【全自動同步】至策略大腦與行情引擎！")
                time.sleep(1.5)
                st.rerun()
            else:
                st.error("⚠️ 無法從證交所獲取資料，可能遇到 API 請求限制或今日無符合條件標的，請稍後再試。")

    with st.form("config_form_main"):
        st.markdown("#### 1. 監控標的設定")
        new_pool_str = st.text_area("監控清單 (以逗號分隔)", value=st.session_state.watch_pool_text, height=100)
        st.markdown("#### 2. 策略啟用與派發")
        available_strats = list(STRATEGY_MAP.keys())
        current_strats = redis_db.get_json("system:config:active_strategies") or ["strategy_13_bollinger_macd_combo", "strategy_05_vwap_bounce"]
        selected_strats = st.multiselect("啟用的量化策略組合", options=available_strats, default=[s for s in current_strats if s in available_strats], format_func=lambda x: STRATEGY_MAP.get(x, x))
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            signal_modes_dict = {
                "CONSENSUS": "🤝 共識模式 (需多個策略同時確認才進場，勝率高)",
                "FIRST_TRIGGER": "⚡ 首發模式 (任一策略觸發即刻進場，搶佔先機)"
            }
            curr_mode = redis_db.get_flag("system:config:signal_mode") or "CONSENSUS"
            selected_mode = st.selectbox(
                "訊號派發模式", 
                options=list(signal_modes_dict.keys()), 
                format_func=lambda x: signal_modes_dict[x],
                index=list(signal_modes_dict.keys()).index(curr_mode) if curr_mode in signal_modes_dict else 0
            )
        with col_f2:
            sizing_options = {"fixed_risk": "固定風險 (Fixed Risk)", "capital_pct": "簡單百分比 (Capital %)", "kelly": "凱利公式 (Kelly Criterion)"}
            curr_sizing = redis_db.get_flag("system:config:sizing_mode") or "fixed_risk"
            selected_sizing_key = st.selectbox("智能倉位計算模式", options=list(sizing_options.keys()), format_func=lambda x: sizing_options[x], index=list(sizing_options.keys()).index(curr_sizing))

        if st.form_submit_button("💾 儲存並同步設定至大腦", use_container_width=True):
            pool_list = [s.strip() for s in new_pool_str.split(",") if s.strip() and len(s.strip()) == 4 and not s.strip().startswith('0')]
            
            # 🌟 加入安全上限保護 (手動輸入時也防呆)
            if len(pool_list) > 95:
                st.warning("⚠️ 輸入標的超過 95 檔安全上限，已自動截斷保留前 95 檔。")
                pool_list = pool_list[:95]
                
            redis_db.set_json("system:config:watch_pool", pool_list)
            redis_db.set_json("system:config:active_strategies", selected_strats)
            redis_db.set_flag("system:config:signal_mode", selected_mode)
            redis_db.set_flag("system:config:sizing_mode", selected_sizing_key)
            st.session_state.watch_pool_text = ", ".join(pool_list)
            st.success("🎉 設定已無縫同步至策略大腦！(已自動剔除輸入的 ETF 等代碼)")

# 🌟 限於盤中交易面板的自動更新邏輯
if auto_refresh and selected_tab == "🔥 盤中交易面板":
    time.sleep(2)
    st.rerun()