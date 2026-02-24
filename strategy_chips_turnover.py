# realtime_strategy_engine.py
import os
import time  # ✅ 標準 time 模組（time.sleep / time.time 使用此模組）
import logging
import logging.handlers
import pandas as pd
import requests

# ✅ 修正點 1：明確區分 datetime.time 與 time 模組，避免命名衝突
from datetime import datetime, time as dt_time

import pytz
from dotenv import load_dotenv
from fubon_neo.sdk import FubonSDK
from redis_manager import redis_db
import yfinance as yf
import re

# 🌟 核心對接：匯入回測武器庫與技術指標
from backtest_engine import TechnicalIndicators, StrategyFactory, BatchBacktester, BacktestEngine

load_dotenv()


class RealtimeStrategyEngine:
    def __init__(self):
        # 1. 系統設定與日誌
        self.load_system_settings()
        self.setup_logging()

        # 2. 狀態記憶體與即時 PnL
        self.traded_today = set()
        self.positions = {}
        self.historical_klines = {}
        self.daily_realized_pnl = 0.0
        self.performance_stats = {}

        self.FEE_RATE = 0.001425
        self.DAY_TRADE_TAX = 0.0015

        # ✅ 修正點 1：使用 dt_time 而非 time，避免與 time 模組衝突
        self.market_open_time  = dt_time(9, 0)    # 09:00 開盤
        self.force_close_time  = dt_time(13, 25)  # 13:25 強制平倉
        # 盤後緩衝截止時間：13:25 之後、15:30 之前視為「當日盤後」；
        # 超過 15:30（如 23:48 啟動）視為「非交易時段」，不觸發強制平倉。
        self.trading_day_end   = dt_time(15, 30)
        self.has_force_closed  = False
        self.max_holding_seconds = int(os.getenv("MAX_HOLDING_SECONDS", 1800))

        # ✅ 每日狀態追蹤：記錄最後一次「重置當日狀態」的日期
        # 用於跨日自動重置 has_force_closed / traded_today / daily_pnl
        self._last_trade_date: str = ""

        # 建立選股匯入資料夾 (Dropzone)
        self.watchlist_dir = "watchlists"
        os.makedirs(self.watchlist_dir, exist_ok=True)

        # 策略中文名稱對照表
        self.strategy_name_map = {
            "strategy_01_momentum_breakout":   "🟢 動能突破策略",
            "strategy_02_orb_breakout":         "🟢 開盤區間突破(ORB)",
            "strategy_03_gap_play":             "🟢 跳空缺口交易",
            "strategy_04_mean_reversion_long":  "🟢 均值回歸做多",
            "strategy_05_vwap_bounce":          "🟢 VWAP 均價策略",
            "strategy_06_fast_ma_cross":        "🟢 快速均線策略",
            "strategy_07_trend_weakness_short": "🔴 空方轉弱策略",
            "strategy_08_rebound_fail_short":   "🔴 反彈不過前高",
            "strategy_09_mean_reversion_short": "🔴 均值回歸做空",
            "strategy_10_rsi_divergence_short": "🔴 籌碼/指標背離",
            "strategy_11_macd_cross_dual":      "⚖️ MACD 交叉",
            "strategy_12_kd_cross_dual":        "⚖️ KD 交叉",
            "strategy_13_bollinger_macd_combo": "⚖️ 布林+MACD 雙重確認",
            "strategy_14_rolling_breakout_dual":"⚖️ 均線/通道突破",
            "strategy_15_rsi_contrarian_dual":  "⚖️ RSI 逆勢交易"
        }

        # 3. 初始化動態設定 (選股池、策略、模式)
        self.watch_pool = []
        self.active_strategy_names = []
        self.active_strategies = []
        self.signal_mode = "CONSENSUS"
        self.pause_new_entries = False
        self.refresh_dynamic_configs(initial=True)

        # 4. 富邦 API 初始化
        fubon_id   = os.getenv("FUBON_ID")
        fubon_pass = os.getenv("FUBON_PASSWORD")
        cert_path  = os.getenv("FUBON_CERT_PATH")
        cert_pass  = os.getenv("FUBON_CERT_PASS")

        try:
            self.sdk = FubonSDK()
            self.sdk.login(fubon_id, fubon_pass, cert_path, cert_pass)
            self.sdk.init_realtime()
            self.logger.info(f"🧠 日內交易戰情室 Pro 大腦初始化完成，監控 {len(self.watch_pool)} 檔標的")
        except Exception as e:
            self.logger.error(f"⚠️ 策略大腦登入富邦失敗 (若為模擬模式可忽略): {e}")
            self.sdk = None
            if self.trade_mode == "LIVE":
                self.send_telegram_alert("🚨 嚴重錯誤：富邦 API 登入失敗，實盤系統無法啟動！")
                raise

        self.send_telegram_alert(
            f"🚀 戰情室系統啟動成功！\n模式: {self.trade_mode}\n監控標的: {len(self.watch_pool)} 檔"
        )

    # =========================================================
    # 系統設定載入（含實盤模式必要環境變數驗證）
    # =========================================================
    def load_system_settings(self):
        self.trade_mode = os.getenv("TRADE_MODE", "PAPER").upper()
        self.total_capital = float(os.getenv("TOTAL_CAPITAL", 1000000))
        self.risk_pct = float(os.getenv("RISK_PCT", 0.02))
        self.max_daily_loss = float(os.getenv("MAX_DAILY_LOSS", -20000))

        self.position_sizing_mode = os.getenv("POSITION_SIZING_MODE", "fixed_risk").lower()
        self.capital_alloc_pct = float(os.getenv("CAPITAL_ALLOC_PCT", 0.2))

        self.tg_token   = os.getenv("TG_BOT_TOKEN", "")
        self.tg_chat_id = os.getenv("TG_CHAT_ID", "")
        self.log_dir    = os.getenv("LOG_DIR", "logs")
        self.log_days   = int(os.getenv("LOG_RETENTION_DAYS", "7"))
        self.log_level  = os.getenv("LOG_LEVEL", "INFO").upper()

        # ✅ 實盤模式：Fail-fast，缺少關鍵環境變數時立即拋出，避免深層才報錯
        if self.trade_mode == "LIVE":
            required_vars = ["FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASS"]
            missing = [v for v in required_vars if not os.getenv(v)]
            if missing:
                raise EnvironmentError(
                    f"🚨 實盤模式 (LIVE) 缺少必要環境變數，請在 .env 中設定: {missing}"
                )

    def setup_logging(self):
        os.makedirs(self.log_dir, exist_ok=True)
        self.logger = logging.getLogger("RealtimeEngine")
        self.logger.setLevel(getattr(logging, self.log_level))

        if not self.logger.handlers:
            formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S.%f'[:-3]
            )
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=os.path.join(self.log_dir, "trading_engine.log"),
                when="midnight", interval=1, backupCount=self.log_days, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def send_telegram_alert(self, message: str):
        if not self.tg_token or not self.tg_chat_id: return
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": f"🤖 【風林火山戰情室】\n{message}",
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=payload, timeout=3)
        except Exception as e:
            self.logger.error(f"Telegram 推播失敗: {e}")

    # =========================================================
    # 實體檔案匯入選股清單 (Dropzone)
    # =========================================================
    def check_and_import_watchlist_file(self):
        for ext in ['txt', 'csv']:
            import_path = os.path.join(self.watchlist_dir, f"import.{ext}")
            if os.path.exists(import_path):
                try:
                    self.logger.info(f"📥 偵測到選股匯入檔案: {import_path}，正在解析...")
                    with open(import_path, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                    extracted_codes = re.findall(r'\b\d{4}\b', content)
                    new_codes = list(set(extracted_codes))

                    if new_codes:
                        redis_db.set_json("system:config:watch_pool", new_codes)
                        self.logger.info(f"✅ 成功從檔案匯入 {len(new_codes)} 檔股票！")
                        self.send_telegram_alert(
                            f"📥 <b>選股清單已更新</b>\n透過檔案匯入 {len(new_codes)} 檔標的。"
                        )
                    else:
                        self.logger.warning(f"⚠️ 檔案 {import_path} 中未發現有效的股票代碼。")

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    os.rename(import_path, os.path.join(self.watchlist_dir, f"imported_{timestamp}.{ext}"))
                except Exception as e:
                    self.logger.error(f"匯入選股檔案發生錯誤: {e}")

    # =========================================================
    # 動態配置與熱更新機制 (Hot Reloading)
    # =========================================================
    def refresh_dynamic_configs(self, initial=False):
        updated = False

        new_pool = redis_db.get_json("system:config:watch_pool")
        if new_pool and new_pool != self.watch_pool:
            added_symbols = [s for s in new_pool if s not in self.watch_pool]
            self.watch_pool = new_pool
            if not initial:
                self.logger.info(f"🔄 [動態更新] 監控標的已更新為 {len(self.watch_pool)} 檔")
            if added_symbols and not initial and hasattr(self, 'sdk'):
                self.init_historical_klines(specific_symbols=added_symbols)
            updated = True

        new_strat_names = redis_db.get_json("system:config:active_strategies")
        if new_strat_names and new_strat_names != self.active_strategy_names:
            loaded_strats = []
            for name in new_strat_names:
                if hasattr(StrategyFactory, name):
                    loaded_strats.append(getattr(StrategyFactory, name))
            self.active_strategy_names = new_strat_names
            self.active_strategies = loaded_strats
            if not initial:
                self.logger.info(f"🔄 [動態更新] 啟用策略已切換為: {self.active_strategy_names}")
            updated = True

        new_mode = redis_db.get_flag("system:config:signal_mode")
        if new_mode and new_mode != self.signal_mode:
            self.signal_mode = new_mode
            if not initial:
                self.logger.info(f"🔄 [動態更新] 派發模式已切換為: {self.signal_mode}")
            updated = True

        new_sizing = redis_db.get_flag("system:config:sizing_mode")
        if new_sizing and new_sizing != self.position_sizing_mode:
            self.position_sizing_mode = new_sizing
            if not initial:
                self.logger.info(f"🔄 [動態更新] 資金控管模式已切換為: {self.position_sizing_mode}")
            updated = True

        pause_flag = redis_db.get_flag("system:flag:pause_entries") == "1"
        if pause_flag != self.pause_new_entries:
            self.pause_new_entries = pause_flag
            status = "⏸️ 已暫停新單進場" if self.pause_new_entries else "▶️ 已恢復新單進場"
            self.logger.warning(status)

        return updated

    # =========================================================
    # 歷史回測與繪圖系統
    # =========================================================
    def run_historical_backtest(self, symbols: list, period: str = "60d",
                                interval: str = "5m", strategy=None):
        self.logger.info("============== 啟動歷史批量回測系統 ==============")
        if not strategy:
            strategy = StrategyFactory.strategy_13_bollinger_macd_combo
        batch_tester = BatchBacktester(symbols, initial_capital=self.total_capital)
        results_df = batch_tester.run_batch(
            strategy, period=period, interval=interval,
            position_sizing=self.position_sizing_mode
        )
        return results_df

    def run_detailed_backtest(self, symbol: str, period: str = "60d",
                              interval: str = "5m",
                              strategy_name: str = "strategy_13_bollinger_macd_combo"):
        self.logger.info(f"============== 啟動單檔進階歷史回測: {symbol} ==============")
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            df = TechnicalIndicators.add_all_indicators(df)
            strategy_func = getattr(StrategyFactory, strategy_name, None)
            if not strategy_func: return None
            engine = BacktestEngine(
                df, initial_capital=self.total_capital,
                position_sizing="fixed_risk", risk_pct=self.risk_pct, verbose=True
            )
            summary = engine.run(strategy_func)
            engine.print_report()
            engine.plot_results(
                title=f"{symbol} 回測分析 - "
                      f"{self.strategy_name_map.get(strategy_name, strategy_name)} ({interval})"
            )
            return summary
        except Exception as e:
            self.logger.error(f"回測錯誤: {e}")
            return None

    # =========================================================
    # 歷史 K 線載入 (處理富邦 dict 回傳)
    # =========================================================
    def init_historical_klines(self, specific_symbols=None):
        symbols_to_fetch = specific_symbols if specific_symbols else self.watch_pool
        self.logger.info(f"開始載入 {len(symbols_to_fetch)} 檔標的之歷史 K 線資料...")

        if not hasattr(self, 'sdk') or self.sdk is None:
            self.logger.warning("⚠️ 富邦 SDK 未初始化，將由即時行情逐步建立 K 線。")
            return

        rest_stock = self.sdk.marketdata.rest_client.stock
        for symbol in symbols_to_fetch:
            try:
                response = rest_stock.intraday.candles(symbol=symbol, timeframe='5')
                if response:
                    data = None
                    if isinstance(response, dict) and 'data' in response:
                        data = response['data']
                    elif isinstance(response, list):
                        data = response

                    if data:
                        df = pd.DataFrame(data)
                        for col in ['close', 'open', 'high', 'low', 'volume', 'average']:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col])
                        df['datetime'] = pd.to_datetime(df['date'])
                        # ✅ 將小寫欄位名稱正規化為 TechnicalIndicators 所需的 Title Case
                        df = df.rename(columns={
                            'open': 'Open', 'high': 'High', 'low': 'Low',
                            'close': 'Close', 'volume': 'Volume', 'average': 'Average'
                        })
                        self.historical_klines[symbol] = df
                    else:
                        self.logger.debug(f"{symbol} 無 K 線資料")
            except Exception as e:
                self.logger.error(f"取得 {symbol} 歷史 K 線失敗: {e}")
            time.sleep(0.05)  # ✅ 使用 time 標準模組
        self.logger.info("✅ K 線快取載入完畢！")

    def update_kline_with_tick(self, symbol, current_price, current_volume):
        """
        以即時 tick 更新 K 棒快取。
        回傳 (updated_df, is_new_bar) 讓呼叫端判斷是否需要重算指標，
        避免每次 tick 都重算，降低 CPU 負荷。
        """
        df = self.historical_klines.get(symbol)
        if df is None or df.empty:
            return df, False

        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz)
        bin_minute = (now.minute // 5) * 5
        current_bin = now.replace(minute=bin_minute, second=0, microsecond=0)
        last_idx = df.index[-1]
        last_bin = df.at[last_idx, 'datetime']

        is_new_bar = current_bin.replace(tzinfo=None) > last_bin.replace(tzinfo=None)

        if is_new_bar:
            # ✅ 欄位名稱與 TechnicalIndicators 期望的 Title Case 保持一致
            new_row = pd.DataFrame([{
                'date': current_bin.strftime("%Y-%m-%dT%H:%M:%S.000+08:00"),
                'datetime': current_bin,
                'Open': current_price, 'High': current_price,
                'Low': current_price, 'Close': current_price,
                'Volume': current_volume, 'Average': current_price
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            if len(df) > 100:
                df = df.iloc[-100:].reset_index(drop=True)
            self.historical_klines[symbol] = df
        else:
            # ✅ 同步使用 Title Case
            df.at[last_idx, 'Close'] = current_price
            if current_price > df.at[last_idx, 'High']:
                df.at[last_idx, 'High'] = current_price
            if current_price < df.at[last_idx, 'Low']:
                df.at[last_idx, 'Low'] = current_price
            df.at[last_idx, 'Volume'] += current_volume

        return df.copy(), is_new_bar

    # =========================================================
    # 智能倉位計算 (固定風險 / 百分比 / 凱利公式)
    # =========================================================
    def calculate_position_size(self, action, exec_price, stop_loss_price, strategy_name=""):
        stats = self.performance_stats.get(strategy_name, {
            "trades": 0, "wins": 0, "total_pnl": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0
        })

        target_shares = 1000  # 預設最低 1 張

        if self.position_sizing_mode == "kelly":
            win_rate = 0.5
            payoff_ratio = 1.5
            if stats["trades"] >= 5:
                win_rate = stats["wins"] / stats["trades"]
                loss_trades = stats["trades"] - stats["wins"]
                if loss_trades > 0 and stats["wins"] > 0:
                    avg_win = stats["gross_profit"] / stats["wins"]
                    avg_loss = abs(stats["gross_loss"]) / loss_trades
                    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 1.5

            kelly_pct = win_rate - ((1 - win_rate) / payoff_ratio)
            kelly_pct = max(0.05, min(kelly_pct, 0.25))
            alloc_amount = self.total_capital * kelly_pct
            target_shares = int(alloc_amount / exec_price)

        elif self.position_sizing_mode == "capital_pct":
            alloc_amount = self.total_capital * self.capital_alloc_pct
            target_shares = int(alloc_amount / exec_price)

        else:  # fixed_risk
            if stop_loss_price:
                risk_amount = self.total_capital * self.risk_pct
                risk_per_share = abs(exec_price - stop_loss_price)
                if risk_per_share > 0:
                    target_shares = int(risk_amount / risk_per_share)

        # 正規化：向下取整為 1000 股 (1張) 的倍數
        target_shares = max(1000, (target_shares // 1000) * 1000)
        # 上限保護：不超過總資金的 90%
        max_shares = int((self.total_capital * 0.9) / exec_price)
        return min(target_shares, max_shares)

    def calculate_realized_pnl(self, action, entry_price, exit_price, qty):
        if action == "SELL":
            gross_pnl = (exit_price - entry_price) * qty
            cost    = entry_price * qty
            revenue = exit_price * qty
            fees    = (cost + revenue) * self.FEE_RATE
            tax     = revenue * self.DAY_TRADE_TAX
        elif action == "COVER":
            gross_pnl = (entry_price - exit_price) * qty
            revenue = entry_price * qty
            cost    = exit_price * qty
            fees    = (revenue + cost) * self.FEE_RATE
            tax     = revenue * self.DAY_TRADE_TAX
        else:
            return 0.0, 0.0
        net_pnl = gross_pnl - fees - tax
        return net_pnl, gross_pnl

    def update_performance_stats(self, strategy_name: str, net_pnl: float, gross_pnl: float):
        if strategy_name not in self.performance_stats:
            self.performance_stats[strategy_name] = {
                "trades": 0, "wins": 0,
                "total_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0
            }

        stats = self.performance_stats[strategy_name]
        stats["trades"]    += 1
        stats["total_pnl"] += net_pnl

        if gross_pnl > 0:
            stats["wins"]         += 1
            stats["gross_profit"] += gross_pnl
        else:
            stats["gross_loss"] += abs(gross_pnl)

        win_rate = (stats["wins"] / stats["trades"]) * 100
        chinese_name = self.strategy_name_map.get(strategy_name, strategy_name)
        self.logger.info(
            f"📊 [績效統計] 策略: {chinese_name} | "
            f"交易: {stats['trades']}次 | 勝率: {win_rate:.1f}% | 淨利: {stats['total_pnl']:.0f}"
        )

    def check_daily_loss_limit(self):
        if self.daily_realized_pnl <= self.max_daily_loss and not self.has_force_closed:
            self.logger.error(f"🚨🚨🚨 觸發每日虧損上限 ({self.max_daily_loss})！啟動全局熔斷！")
            self.send_telegram_alert(
                f"🚨 <b>全局熔斷觸發</b>\n"
                f"今日虧損達 {self.daily_realized_pnl:.0f} 元\n已強制清倉！"
            )
            self.execute_force_close_all()
            return True
        return False

    def execute_force_close_all(self):
        self.logger.warning("⏰ 執行系統強制平倉程序！")
        watchlist_data = {}

        for symbol, pos_data in self.positions.items():
            current_pos = pos_data.get('position', 0)
            if current_pos == 0: continue

            action    = "SELL" if current_pos > 0 else "COVER"
            close_qty = abs(current_pos)

            last_price = pos_data.get('entry_price', 0)
            try:
                trade_data = redis_db.get_json(f"market:trades:{symbol}")
                if trade_data:
                    last_price = trade_data.get('price', last_price)
            except Exception:
                pass

            net_pnl, gross_pnl = self.calculate_realized_pnl(
                action, pos_data.get('entry_price'), last_price, close_qty
            )
            self.daily_realized_pnl += net_pnl

            strategy_name = pos_data.get('strategy_code', '強制平倉')
            self.update_performance_stats(strategy_name, net_pnl, gross_pnl)

            self.logger.info(f"🚨 【強制平倉】 {symbol} 預估淨利: {net_pnl:.0f}")

            # ✅ 修正點：key 名稱統一為 "system:data:daily_watchlist"，
            # 儲存本次強制平倉資訊（含 realized_pnl），與一般出場格式一致
            watchlist_data[symbol] = {
                "action": action, "strategy": "系統保護性平倉",
                "target_price": last_price, "qty": close_qty,
                "realized_pnl": net_pnl, "trade_mode": self.trade_mode
            }

        self.positions.clear()
        self.has_force_closed = True
        redis_db.set_flag("system:mock:pnl", str(self.daily_realized_pnl))
        # ✅ 寫入全局熔斷旗標至 Redis，讓 system_monitor 與 Streamlit 面板同步感知
        redis_db.set_flag("system:flag:kill_switch", "1", expire_sec=86400)
        for sym in self.watch_pool:
            self.traded_today.add(sym)

        return watchlist_data

    # =========================================================
    # 多策略派發引擎
    # =========================================================
    def evaluate_multi_strategies(self, df, current_price, current_pos, book_data=None):
        buy_signals, sell_signals, short_signals, cover_signals = [], [], [], []

        for strat in self.active_strategies:
            result = strat(df, current_price, current_pos, book_data=book_data)
            if not result or not result[0]: continue
            a, r, sl = result if len(result) == 3 else (result[0], result[1], None)

            strat_name   = strat.__name__
            chinese_reason = f"{self.strategy_name_map.get(strat_name, r)} ({r})"

            if a == "BUY":   buy_signals.append((a, chinese_reason, sl, strat_name))
            elif a == "SELL":  sell_signals.append((a, chinese_reason, sl, strat_name))
            elif a == "SHORT": short_signals.append((a, chinese_reason, sl, strat_name))
            elif a == "COVER": cover_signals.append((a, chinese_reason, sl, strat_name))

        for exits in [sell_signals, cover_signals]:
            if exits: return exits[0][0], exits[0][1], exits[0][2], exits[0][3]

        if self.signal_mode == "FIRST_TRIGGER":
            for entries in [buy_signals, short_signals]:
                if entries: return entries[0][0], entries[0][1], entries[0][2], entries[0][3]

        elif self.signal_mode == "CONSENSUS":
            threshold = 2 if len(self.active_strategies) >= 2 else 1
            for entries in [buy_signals, short_signals]:
                if len(entries) >= threshold:
                    combined_reason = "【共識進場】 " + " & ".join([s[1].split(' ')[1] for s in entries])
                    sl_list   = [s[2] for s in entries if s[2] is not None]
                    final_sl  = max(sl_list) if entries[0][0] == "BUY" else min(sl_list) if sl_list else None
                    return entries[0][0], combined_reason, final_sl, entries[0][3]

        return None, "", None, ""

    # =========================================================
    # 主實戰迴圈
    # =========================================================
    def is_market_open(self):
        tz = pytz.timezone('Asia/Taipei')
        now_time = datetime.now(tz).time()
        return self.market_open_time <= now_time <= self.force_close_time

    def _get_trade_date(self) -> str:
        """
        取得今日「交易日日期字串」(YYYY-MM-DD)。
        凌晨 00:00～08:59 歸屬前一個自然日（夜間維護視窗），
        避免跨夜後 09:00 前就被誤判為新的一天而提早重置狀態。
        """
        from datetime import timedelta
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz)
        if now.time() < dt_time(9, 0):
            now = now - timedelta(days=1)
        return now.strftime('%Y-%m-%d')

    def _reset_daily_state(self, indicator_cache: dict):
        """
        每個交易日開盤前呼叫一次，重置所有每日狀態：
        - has_force_closed  : 強制平倉旗標歸 False
        - traded_today      : 當日已交易集合清空
        - daily_realized_pnl: 當日損益歸零
        - indicator_cache   : 技術指標快取清空（原地 clear，保持同一個 dict 物件）
        """
        self.has_force_closed   = False
        self.traded_today       = set()
        self.daily_realized_pnl = 0.0
        indicator_cache.clear()
        redis_db.set_flag("system:mock:pnl", "0")
        # ✅ 跨日重置：清除前一交易日的熔斷旗標，讓新的一天可以正常進場
        redis_db.delete_flag("system:flag:kill_switch")
        self.logger.info(
            "🌅 偵測到新交易日，已自動重置每日狀態"
            "（強制平倉旗標 / 今日交易集合 / 損益計數器 / 指標快取）。"
        )

    def run(self):
        self.init_historical_klines()
        self.logger.info(f"🚀 啟動即時策略大腦 ({self.trade_mode} 模式)...")

        loop_counter = 0
        # 記錄每個 symbol 上次計算指標的 df 快取，避免非新 K 棒時重複計算
        indicator_cache: dict = {}

        while True:
            try:
                loop_counter += 1
                tz = pytz.timezone('Asia/Taipei')
                now = datetime.now(tz)
                now_time = now.time()

                # ---------------------------------------------------------
                # 0. ✅ 新增：跨日自動重置每日狀態
                #    每次迴圈都比對「今日交易日」，日期改變時立即重置。
                #    解決「盤後或隔夜啟動後整天不工作」的根本問題。
                # ---------------------------------------------------------
                today_str = self._get_trade_date()
                if today_str != self._last_trade_date:
                    if self._last_trade_date:  # 非首次啟動才印 log，避免重複
                        self._reset_daily_state(indicator_cache)
                    self._last_trade_date = today_str

                # ---------------------------------------------------------
                # 1. 處理緊急事件與外部控制
                # ---------------------------------------------------------
                if loop_counter % 10 == 0:
                    self.check_and_import_watchlist_file()
                    self.refresh_dynamic_configs()

                    if redis_db.get_flag("system:flag:manual_close_all") == "1":
                        self.logger.warning("🚨 收到 UI 面板「一鍵全平倉」指令！")
                        self.send_telegram_alert("🚨 觸發手動一鍵全平倉！")
                        watchlist_data = self.execute_force_close_all()
                        if watchlist_data:
                            redis_db.set_json("system:data:positions", self.positions)
                            redis_db.set_json("system:data:daily_watchlist",
                                              watchlist_data, expire_sec=86400)
                            redis_db.set_flag("system:flag:screener_updated", "1", expire_sec=60)
                        redis_db.delete_flag("system:flag:manual_close_all")

                # ---------------------------------------------------------
                # 2. 自動風控防線：收盤強制平倉與每日虧損上限
                # ---------------------------------------------------------
                # ✅ 修正點：增加時間視窗限制。
                # 原條件 `now_time >= force_close_time` 在 23:48 啟動時也成立，
                # 導致系統立即執行強制平倉並永久鎖定（has_force_closed=True）。
                # 新條件：只有在「交易時段開始後到盤後緩衝截止（15:30）」之間
                # 才觸發強制平倉，非交易時間啟動不受影響。
                in_trading_day_window = self.market_open_time <= now_time <= self.trading_day_end
                if in_trading_day_window and now_time >= self.force_close_time and not self.has_force_closed:
                    self.send_telegram_alert("⏰ 觸發 13:25 強制清倉機制！")
                    watchlist_data = self.execute_force_close_all()
                    if watchlist_data:
                        redis_db.set_json("system:data:positions", self.positions)
                        redis_db.set_json("system:data:daily_watchlist",
                                          watchlist_data, expire_sec=86400)
                        redis_db.set_flag("system:flag:screener_updated", "1", expire_sec=60)
                    time.sleep(1)
                    continue

                # ✅ 修正點：has_force_closed 為 True 時，
                # 非交易時段（盤後、夜間、隔日開盤前）直接等待，不佔用 CPU。
                # 跨日後 _reset_daily_state 會將 has_force_closed 重置為 False。
                if self.has_force_closed:
                    time.sleep(5)
                    continue

                # ✅ 新增：從 Redis 讀取 kill_switch，確保 system_monitor 觸發的
                # 熔斷（例如：連續虧損超限）也能讓策略大腦立刻停止新進場。
                if redis_db.get_flag("system:flag:kill_switch") == "1":
                    if not self.has_force_closed:
                        self.logger.error("🚨 偵測到外部熔斷旗標 (kill_switch)，暫停所有新進場！")
                        self.has_force_closed = True
                    time.sleep(5)
                    continue

                if self.check_daily_loss_limit():
                    time.sleep(5)
                    continue

                # ---------------------------------------------------------
                # 3. 策略大腦洗價與運算
                # ---------------------------------------------------------
                watchlist_data = {}
                is_open = self.is_market_open()

                for symbol in self.watch_pool:
                    trade_data = redis_db.get_json(f"market:trades:{symbol}")
                    if not trade_data: continue
                    current_price = trade_data.get('price')
                    current_qty   = trade_data.get('size', 1)
                    if current_price is None: continue

                    # ✅ 優化：只有產生新 K 棒時才重新計算技術指標，降低 CPU 負載
                    updated_df, is_new_bar = self.update_kline_with_tick(symbol, current_price, current_qty)

                    if is_new_bar or symbol not in indicator_cache:
                        df_with_indicators = TechnicalIndicators.add_all_indicators(updated_df)
                        if df_with_indicators is not None and len(df_with_indicators) >= 20:
                            indicator_cache[symbol] = df_with_indicators
                        else:
                            continue
                    else:
                        df_with_indicators = indicator_cache.get(symbol)
                        if df_with_indicators is None: continue

                    book_data = redis_db.get_json(f"market:books:{symbol}")

                    pos_data            = self.positions.get(symbol, {})
                    current_pos         = pos_data.get('position', 0)
                    stop_loss_price     = pos_data.get('stop_loss_price')
                    entry_strategy_code = pos_data.get('strategy_code', 'manual')
                    # ✅ 使用 time.time()（標準 time 模組），不再與 dt_time 混淆
                    entry_timestamp     = pos_data.get('entry_timestamp', time.time())

                    action, reason, new_stop_loss, trigger_strat_code = None, "", None, ""

                    # 時間停損
                    if current_pos != 0 and (time.time() - entry_timestamp) > self.max_holding_seconds:
                        action = "SELL" if current_pos > 0 else "COVER"
                        reason = "⏰ 持倉超時 (時間動能耗盡停損)"
                        trigger_strat_code = entry_strategy_code

                    # 絕對防守線優先
                    elif current_pos > 0 and stop_loss_price and current_price <= stop_loss_price:
                        action, reason = "SELL", f"🚨 跌破防守線({stop_loss_price})停損"
                        trigger_strat_code = entry_strategy_code
                    elif current_pos < 0 and stop_loss_price and current_price >= stop_loss_price:
                        action, reason = "COVER", f"🚨 突破防守線({stop_loss_price})停損"
                        trigger_strat_code = entry_strategy_code

                    # 盤中正常策略評估
                    elif is_open:
                        action, reason, new_stop_loss, trigger_strat_code = \
                            self.evaluate_multi_strategies(
                                df_with_indicators, current_price, current_pos, book_data
                            )

                    # 訊號執行
                    if action:
                        if action in ["BUY", "SHORT"]:
                            if self.pause_new_entries or not is_open or symbol in self.traded_today:
                                continue

                            target_qty = self.calculate_position_size(
                                action, current_price, new_stop_loss, trigger_strat_code
                            )

                            self.logger.info(
                                f"💡 【進場】 {symbol} [{reason}] 數量: {target_qty}, 停損: {new_stop_loss}"
                            )
                            self.send_telegram_alert(
                                f"🟢 <b>訊號觸發 ({self.trade_mode})</b>\n"
                                f"標的: {symbol}\n動作: {action}\n策略: {reason}\n"
                                f"價格: {current_price}\n數量: {target_qty}股\n配置: {self.position_sizing_mode}"
                            )

                            watchlist_data[symbol] = {
                                "action": action, "strategy": reason,
                                "target_price": current_price, "qty": target_qty,
                                "trade_mode": self.trade_mode
                            }
                            self.positions[symbol] = {
                                "position": target_qty if action == "BUY" else -target_qty,
                                "strategy": reason, "strategy_code": trigger_strat_code,
                                "entry_price": current_price, "stop_loss_price": new_stop_loss,
                                "entry_timestamp": time.time()  # ✅ 標準 time 模組
                            }
                            self.traded_today.add(symbol)

                        elif action in ["SELL", "COVER"]:
                            close_qty   = abs(current_pos)
                            entry_price = pos_data.get('entry_price', current_price)

                            net_pnl, gross_pnl = self.calculate_realized_pnl(
                                action, entry_price, current_price, close_qty
                            )
                            self.daily_realized_pnl += net_pnl
                            self.update_performance_stats(trigger_strat_code, net_pnl, gross_pnl)
                            redis_db.set_flag("system:mock:pnl", str(self.daily_realized_pnl))

                            self.logger.info(f"💰 【結算】 {symbol} [{reason}] 淨利: {net_pnl:.0f}")
                            self.send_telegram_alert(
                                f"🔴 <b>結算平倉 ({self.trade_mode})</b>\n"
                                f"標的: {symbol}\n動作: {action}\n原因: {reason}\n"
                                f"淨利: {net_pnl:.0f} 元\n今日累計: {self.daily_realized_pnl:.0f} 元"
                            )

                            watchlist_data[symbol] = {
                                "action": action, "strategy": reason,
                                "target_price": current_price, "qty": close_qty,
                                "realized_pnl": net_pnl, "trade_mode": self.trade_mode
                            }
                            del self.positions[symbol]

                if watchlist_data:
                    redis_db.set_json("system:data:positions", self.positions)
                    redis_db.set_json("system:data:daily_watchlist",
                                      watchlist_data, expire_sec=86400)
                    redis_db.set_flag("system:flag:screener_updated", "1", expire_sec=60)

                time.sleep(0.1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"策略引擎發生錯誤: {e}")
                time.sleep(1)


if __name__ == "__main__":
    engine = RealtimeStrategyEngine()
    engine.run()