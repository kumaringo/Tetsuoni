import requests

def start_game_logic(event, line_bot_api):
    gas_url = "https://script.google.com/macros/s/AKfycbw9Oq4m-B6qjJr3GEMoaeZTZE62K2eFr46WoEjWm7BQ920dOS2aMWndDFDXitVtBiqB/exec"
    
    try:
        # GASからスコアデータを取得
        res = requests.get(gas_url, timeout=5).json()
        
        red_score = res.get("red_score", 0)
        blue_score = res.get("blue_score", 0)
        white_score = res.get("white_score", 0)
        
        # スコア辞書を作成
        score_dict = {
            "赤": red_score,
            "青": blue_score,
            "白": white_score
        }
        
        # 最大値・最小値・点数差の計算
        max_val = max(score_dict.values())
        min_val = min(score_dict.values())
        difference_val = max_val - min_val

        # 点数差による「1チームあたりのパス枠」判定
        if difference_val >= 70:
            pass_limit = 3
        elif difference_val >= 50:
            pass_limit = 2
        elif difference_val >= 30:
            pass_limit = 1
        else:
            pass_limit = 0

        # 最下位チームをすべて抽出
        min_teams = [color for color, score in score_dict.items() if score == min_val]
        min_teams_str = "と".join(min_teams)

        # 通知用メッセージの作成
        message = (
            f"【鉄道鬼ごっこ：ゲーム開始】\n"
            f"🔴赤:{red_score} / 🔵青:{blue_score} / ⚪白:{white_score}\n"
            f"⚡最大点差: {difference_val}点\n"
            f"🐢最下位: {min_teams_str}チーム\n"
            f"🎁特典: 対象チームは各【 {pass_limit}人 】までパス可能です！"
        )
        
        return message, pass_limit, min_teams

    except Exception as e:
        print(f"GAS取得エラー: {e}")
        # エラー時はパス枠なしで開始
        return "スコア取得に失敗しましたが、受付を開始します！", 0, []