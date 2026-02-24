"""
修正版富邦實際交易整合
解決 API 參數不匹配問題
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import os

def setup_real_trading():
    """設定實際交易環境"""
    
    # 1. 檢查必要模組
    try:
        from fubon_api_enhanced import FubonTradeAPIV2
        from config_manager import SecureConfigManager
        return True
    except ImportError as e:
        st.error(f"❌ 缺少必要模組: {e}")
        st.code("pip install requests cryptography")
        return False

def load_fubon_config():
    """載入富邦設定"""
    config_paths = [
        'fubon_config.enc',  # 加密設定檔
        'fubon_config.json',  # 明文設定檔
        'fubon_config_test.json'  # 測試設定檔
    ]
    
    for config_file in config_paths:
        if os.path.exists(config_file):
            try:
                if config_file.endswith('.enc'):
                    # 需要解密
                    from config_manager import SecureConfigManager
                    manager = SecureConfigManager(config_file)
                    password = st.text_input(f"輸入 {config_file} 的密碼", 
                                           type="password")
                    if password:
                        return manager.load_config(password)
                else:
                    # 明文設定檔
                    import json
                    with open(config_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
            except Exception as e:
                st.warning(f"載入 {config_file} 失敗: {e}")
    
    return None

def initialize_fubon_api():
    """初始化富邦API"""
    
    # 檢查是否已初始化
    if 'fubon_api_v2' in st.session_state and st.session_state.fubon_api_v2:
        return st.session_state.fubon_api_v2
    
    # 載入設定
    config = load_fubon_config()
    if not config:
        st.warning("請先設定富邦API設定檔")
        return None
    
    try:
        # 初始化API
        from fubon_api_enhanced import FubonTradeAPIV2
        api = FubonTradeAPIV2(config)
        
        # 儲存到session state
        st.session_state.fubon_api_v2 = api
        return api
    except Exception as e:
        st.error(f"API初始化失敗: {e}")
        return None

def place_fubon_order_v2(symbol, action, quantity, price=None, order_type='LIMIT'):
    """使用新版API下單"""
    
    api = st.session_state.get('fubon_api_v2')
    if not api or not hasattr(api, 'logged_in') or not api.logged_in:
        st.error("API未連線或未登入")
        return None
    
    try:
        # 轉換動作格式
        side = 'BUY' if action.upper() == 'BUY' or action == '買進' else 'SELL'
        
        # 下單
        result = api.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type
        )
        
        return result
    except Exception as e:
        st.error(f"下單錯誤: {e}")
        return None

# 在Streamlit應用程式中使用
if __name__ == "__main__":
    st.set_page_config(page_title="富邦交易整合", layout="wide")
    
    st.title("富邦證券實際交易整合")
    
    # 初始化
    if setup_real_trading():
        api = initialize_fubon_api()
        
        if api:
            # 登入狀態
            if not api.logged_in:
                if st.button("登入富邦API"):
                    with st.spinner("登入中..."):
                        if api.login():
                            st.success("登入成功")
                            st.rerun()
                        else:
                            st.error("登入失敗")
            else:
                st.success("✅ 已登入富邦API")
                
                # 顯示帳戶資訊
                balance = api.get_account_balance()
                if balance:
                    st.metric("可用餘額", f"{balance.get('available_balance', 0):,.0f}")
                
                # 簡單下單介面
                st.subheader("下單測試")
                col1, col2 = st.columns(2)
                with col1:
                    symbol = st.text_input("股票代碼", "2330")
                    quantity = st.number_input("數量", 1000, 100000, 1000, 1000)
                with col2:
                    price = st.number_input("價格", 0.01, 10000.0, 600.0, 0.5)
                    action = st.selectbox("動作", ["買進", "賣出"])
                
                if st.button("測試下單"):
                    result = place_fubon_order_v2(symbol, action, quantity, price)
                    if result and result.get('success'):
                        st.success(f"下單成功: {result.get('order_id')}")