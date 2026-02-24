"""
安全設定檔管理器 (修正版)
處理API金鑰、憑證等敏感資訊
"""

import json
import os
import base64
import getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # 修正導入
from cryptography.hazmat.backends import default_backend


class SecureConfigManager:
    """安全設定檔管理器"""
    
    def __init__(self, config_file='fubon_config.enc'):
        self.config_file = config_file
        self.key = None
        
    def _get_key(self, password: str = None, salt: bytes = None) -> bytes:
        """產生加密金鑰"""
        if password is None:
            password = getpass.getpass("請輸入設定檔加密密碼: ")
        
        # 使用固定salt（實際應用中應使用隨機salt並儲存）
        if salt is None:
            salt = b'fubon_trading_system_salt'  # 固定salt，長度應為16位元組
            # 確保salt長度為16位元組
            if len(salt) < 16:
                salt = salt.ljust(16, b'0')
            else:
                salt = salt[:16]
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def save_config(self, config: dict, password: str = None):
        """儲存加密設定檔"""
        # 產生金鑰
        key = self._get_key(password)
        fernet = Fernet(key)
        
        # 加密設定
        config_json = json.dumps(config, ensure_ascii=False, indent=2)
        encrypted = fernet.encrypt(config_json.encode())
        
        # 將salt和加密資料一起儲存
        with open(self.config_file, 'wb') as f:
            # 寫入固定salt（實際應用中應儲存隨機salt）
            f.write(encrypted)
        
        print(f"✅ 設定檔已加密儲存至 {self.config_file}")
        
        # 也儲存一份明文範例（不含密碼）
        example_config = config.copy()
        if 'pwd' in example_config:
            example_config['pwd'] = '********'
        if 'cert_pwd' in example_config:
            example_config['cert_pwd'] = '********'
        
        with open('fubon_config_example.json', 'w', encoding='utf-8') as f:
            json.dump(example_config, f, ensure_ascii=False, indent=2)
        
        # 儲存設定檔說明
        self._save_config_instructions()
        
        return True
    
    def load_config(self, password: str = None) -> dict:
        """讀取加密設定檔"""
        if not os.path.exists(self.config_file):
            print(f"❌ 設定檔 {self.config_file} 不存在")
            return None
        
        try:
            # 讀取加密資料
            with open(self.config_file, 'rb') as f:
                encrypted = f.read()
            
            # 產生金鑰（使用與儲存時相同的salt）
            key = self._get_key(password)
            fernet = Fernet(key)
            
            # 解密
            decrypted = fernet.decrypt(encrypted)
            config = json.loads(decrypted.decode())
            
            print("✅ 設定檔載入成功")
            return config
            
        except Exception as e:
            print(f"❌ 設定檔解密失敗: {e}")
            print("請檢查密碼是否正確")
            return None
    
    def setup_wizard(self):
        """設定精靈"""
        print("=" * 60)
        print("富邦證券API設定精靈")
        print("=" * 60)
        
        config = {}
        
        # 帳號資訊
        config['id'] = input("1. 輸入富邦帳號 (ID): ").strip()
        config['pwd'] = getpass.getpass("2. 輸入富邦密碼 (不會顯示): ")
        
        # 憑證設定
        print("\n3. 憑證設定:")
        print("   請將憑證檔案(.pfx)放置於 cert/ 目錄下")
        
        # 檢查cert目錄是否存在
        if not os.path.exists('cert'):
            os.makedirs('cert', exist_ok=True)
            print("   已建立 cert/ 目錄")
        
        # 列出cert目錄中的檔案
        cert_files = [f for f in os.listdir('cert') if f.endswith('.pfx')]
        if cert_files:
            print(f"   找到憑證檔案: {', '.join(cert_files)}")
        
        cert_path = input("   輸入憑證檔案名稱 (例如: your_cert.pfx): ").strip()
        
        # 完整路徑
        full_cert_path = os.path.join('cert', cert_path)
        config['cert_path'] = full_cert_path
        
        # 檢查檔案是否存在
        if not os.path.exists(full_cert_path):
            print(f"⚠️  警告: 檔案 {full_cert_path} 不存在")
            print(f"   請將憑證檔案複製到: {os.path.abspath('cert')}")
            proceed = input("   是否繼續？ (y/n): ").lower()
            if proceed != 'y':
                print("❌ 設定取消")
                return None
        
        config['cert_pwd'] = getpass.getpass("4. 輸入憑證密碼: ")
        
        # API伺服器設定
        print("\n5. API伺服器設定:")
        print("   1) 模擬環境 (測試用)")
        print("   2) 正式環境 (實際交易)")
        env_choice = input("   請選擇 (1/2): ").strip()
        
        if env_choice == '1':
            config['api_url'] = 'https://test-api.fubon.com'
            print("   使用測試環境")
        else:
            config['api_url'] = 'https://api.fubon.com'
            print("   使用正式環境 (⚠️ 實際交易)")
        
        # 交易設定
        print("\n6. 交易設定:")
        try:
            max_amount = int(input("   單筆最大下單金額 (預設 100000): ") or "100000")
            config['max_order_amount'] = max_amount
        except ValueError:
            config['max_order_amount'] = 100000
        
        try:
            daily_loss = int(input("   單日最大虧損限制 (預設 50000): ") or "50000")
            config['daily_max_loss'] = daily_loss
        except ValueError:
            config['daily_max_loss'] = 50000
        
        # 加密密碼
        encrypt_pwd = getpass.getpass("\n7. 設定設定檔加密密碼 (請牢記): ")
        
        if self.save_config(config, encrypt_pwd):
            print("\n" + "=" * 60)
            print("✅ 設定完成！")
            print("=" * 60)
            print("\n重要資訊：")
            print(f"1. 設定檔位置: {os.path.abspath(self.config_file)}")
            print(f"2. 憑證路徑: {os.path.abspath(config['cert_path'])}")
            print("3. 請記住加密密碼，每次啟動都需要")
            print("\n啟動交易系統：")
            print("  streamlit run streamlit_app.py")
            
            return config
        
        return None
    
    def _save_config_instructions(self):
        """儲存設定檔說明"""
        instructions = """# 富邦證券API設定檔說明

## 設定檔位置
- 加密設定檔: fubon_config.enc
- 範例設定檔: fubon_config_example.json

## 如何修改設定
1. 執行 config_manager.py
2. 選擇重新設定
3. 或手動編輯 fubon_config_example.json 後加密

## 安全注意事項
1. 勿將 fubon_config.enc 分享給他人
2. 定期變更加密密碼
3. 憑證檔案妥善保管

## 故障排除
1. 忘記密碼：刪除 fubon_config.enc 重新設定
2. 憑證錯誤：確認憑證路徑和密碼正確
3. API連線失敗：檢查網路和API服務狀態
"""
        
        with open('CONFIG_INSTRUCTIONS.md', 'w', encoding='utf-8') as f:
            f.write(instructions)


def simple_config_setup():
    """簡易設定精靈（避免加密問題）"""
    print("=" * 60)
    print("富邦證券API簡易設定")
    print("=" * 60)
    
    config = {}
    
    config['id'] = input("1. 輸入富邦帳號 (ID): ").strip()
    config['pwd'] = getpass.getpass("2. 輸入富邦密碼 (不會顯示): ")
    
    # 憑證設定
    print("\n3. 憑證設定:")
    if not os.path.exists('cert'):
        os.makedirs('cert', exist_ok=True)
    
    cert_files = [f for f in os.listdir('cert') if f.endswith('.pfx')]
    if cert_files:
        print(f"   找到憑證檔案: {', '.join(cert_files)}")
    
    cert_name = input("   輸入憑證檔案名稱 (例如: your_cert.pfx): ").strip()
    config['cert_path'] = os.path.join('cert', cert_name)
    config['cert_pwd'] = getpass.getpass("4. 輸入憑證密碼: ")
    
    # API設定
    print("\n5. API伺服器設定:")
    env = input("   使用測試環境？ (y/n): ").lower()
    config['api_url'] = 'https://test-api.fubon.com' if env == 'y' else 'https://api.fubon.com'
    
    # 儲存為JSON（未加密）
    config_file = 'fubon_config.json'
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 設定已儲存至 {config_file}")
    print("⚠️  注意：此設定檔未加密，請妥善保管！")
    
    return config


def main():
    """主程式"""
    print("=" * 60)
    print("富邦證券API設定工具")
    print("=" * 60)
    
    print("\n請選擇設定模式:")
    print("1. 安全模式 (加密設定檔)")
    print("2. 簡易模式 (未加密JSON)")
    print("3. 測試模式 (使用模擬數據)")
    
    choice = input("\n請選擇 (1/2/3): ").strip()
    
    if choice == '1':
        # 安全模式
        manager = SecureConfigManager()
        
        if os.path.exists('fubon_config.enc'):
            reconfig = input("設定檔已存在，要重新設定嗎？ (y/n): ").lower()
            if reconfig == 'y':
                manager.setup_wizard()
            else:
                # 測試載入現有設定
                password = getpass.getpass("輸入加密密碼測試載入: ")
                config = manager.load_config(password)
                if config:
                    print("\n✅ 設定檔載入成功！")
        else:
            manager.setup_wizard()
    
    elif choice == '2':
        # 簡易模式
        simple_config_setup()
    
    elif choice == '3':
        # 測試模式
        test_config = {
            'id': 'test_account',
            'pwd': 'test_password',
            'cert_path': 'cert/test.pfx',
            'cert_pwd': 'test123',
            'api_url': 'https://test-api.fubon.com',
            'max_order_amount': 100000,
            'daily_max_loss': 50000
        }
        
        with open('fubon_config_test.json', 'w', encoding='utf-8') as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)
        
        print("\n✅ 測試設定檔已建立: fubon_config_test.json")
        print("   使用此檔案進行API功能測試")
    
    else:
        print("❌ 無效選擇")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 使用者中斷")
    except Exception as e:
        print(f"\n❌ 發生錯誤: {e}")
        print("請確認已安裝必要套件:")
        print("  pip install cryptography")