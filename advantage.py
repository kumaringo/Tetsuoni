import requests

def start_game_logic(event, line_bot_api):
    # 【重要】新しくデプロイして発行されたURLに貼り替えてください
    gas_url = "https://script.google.com/macros/s/ここに新しいID/exec"
    
    try:
        # GASから集計データを取得
        response = requests.get(gas_url, allow_redirects=True)
        res = response.json()
        
        # GAS側でエラーが発生していないかチェック
        if "error" in res:
            print(f"GASエラー報告: {res['error']}")
            return f"エラー: {res['error']}", 0, []

        # スコアの取り出し
        red_score = res.get("red_score", 0)
        blue_score = res.get("blue_score", 0)
        white_score = res.get("white_score", 0)
        
        score_dict = {
            "赤": red_score,
            "青": blue_score,
            "白": white_score
        }
        
        # 判定ロジック
        max_val = max(score_dict.values())
        min_val = min(score_dict.values())
        difference_val = max_val - min_val

        # 点数差によるパス枠判定
        if difference_val >= 70:
            pass_limit = 3
        elif difference_val >= 50:
            pass_limit = 2
        elif difference_val >= 30:
            pass_limit = 1
        else:
            pass_limit = 0

        # 最下位チームの抽出
        min_teams = [color for color, score in score_dict.items() if score == min_val]
        min_teams_str = "と".join(min_teams)

        # メッセージ作成
        message = (
            f"【鉄道鬼ごっこ：ゲーム開始】\n"
            f"🔴赤:{red_score} / 🔵青:{blue_score} / ⚪白:{white_score}\n"
            f"⚡最大点差: {difference_val}点\n"
            f"🐢最下位: {min_teams_str}チーム\n"
            f"🎁特典: 対象チームは各【 {pass_limit}人 】までパス可能です！"
        )
        
        return message, pass_limit, min_teams

    except Exception as e:
        print(f"通信エラー詳細: {e}")
        return "スコア取得に失敗しました。URLや権限設定を確認してください。", 0, []
