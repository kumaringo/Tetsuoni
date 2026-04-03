import requests

def start_game_logic(event, line_bot_api):
    gas_url = "https://script.google.com/macros/s/AKfycrNxW3fEZMlctHemgYvBQX2nwFZu6AzAle8xDfyclc8CsxE7fmyiZUZVwDKx2HSycD/exec"
    
    try:
        # 1. まずは生データ（テキスト）として取得してみる
        response = requests.get(gas_url, allow_redirects=True)
        print(f"ステータスコード: {response.status_code}")
        print(f"届いた中身: {response.text}") # ← ここにエラー内容が出るはずです
        
        # 2. JSONに変換
        res = response.json()
        
        red_score = res.get("red_score", 0)
        blue_score = res.get("blue_score", 0)
        white_score = res.get("white_score", 0)
        
        # （以下、メッセージ作成ロジック...）
        # ※確認のため一旦短く返します
        return f"取得成功！ 赤:{red_score} 青:{blue_score} 白:{white_score}", 0, []

    except Exception as e:
        # 3. 具体的にどこでコケたか出力
        import traceback
        error_detail = traceback.format_exc()
        print(f"詳細エラー:\n{error_detail}")
        return f"取得失敗。原因: {e}", 0, []
