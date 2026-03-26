import os
from linebot.models import TextSendMessage
from station_data import STATION_COORDINATES
from pin import send_map_with_pins

def handle_registration_logic(event, line_bot_api, participant_data, users_participated, USER_CONFIG, REQUIRED_USERS):
    text = event.message.text.strip()
    print(f"--- DEBUG: メッセージ受信 [{text}] ---")

    # 1. チャットIDとユーザー情報の取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    user_id = event.source.user_id
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        username = profile.display_name
        print(f"DEBUG: ユーザー名確認 [{username}]")
    except Exception as e:
        print(f"DEBUG: プロフィール取得失敗: {e}")
        username = "Unknown User"

    # ユーザー設定（チーム・本名）の取得
    config = USER_CONFIG.get(username, {"team": "白", "real_name": username})
    team = config["team"]
    real_name = config["real_name"]

    # データの初期化
    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()
        print(f"DEBUG: チャットID {chat_id} のデータを初期化しました")

    # スコア情報用変数の初期化
    score_info = ""

    # --- 初回投稿（1人目）の特別処理 ---
    if len(users_participated[chat_id]) == 0:
        print("DEBUG: 1人目の投稿です。advantage.py を呼び出します")
        try:
            from advantage import start_game_logic
            score_msg, p_limit, m_teams = start_game_logic(event, line_bot_api)
            score_info = score_msg + "\n\n"
            
            team_pass_limits = {t: p_limit for t in m_teams}
            participant_data[chat_id]["_rules"] = {
                "team_pass_limits": team_pass_limits
            }
        except Exception as e:
            print(f"DEBUG: advantage.py の処理でエラー: {e}")

    # すでに参加しているか（更新かどうか）の判定
    is_update = username in participant_data[chat_id]

    # --- 3. 駅名（またはパス）判定とデータ更新 ---
    display_text = ""
    if text == "パス":
        rules = participant_data[chat_id].get("_rules", {"team_pass_limits": {}})
        limits = rules.get("team_pass_limits", {})

        if team not in limits:
            print(f"DEBUG: {team} チームにパス権がありません")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌{team}チームは現在パス権を持っていません。"))
            return
        if limits[team] <= 0:
            print(f"DEBUG: {team} チームのパス枠が終了しています")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️{team}チームのパス枠は使い切られました！"))
            return

        limits[team] -= 1
        participant_data[chat_id][username] = {"station": "パス"}
        users_participated[chat_id].add(username)
        display_text = f"パス（{team}残り枠:{limits[team]}）"
        print(f"DEBUG: パス受理（残り {limits[team]}）")
    
    elif text in STATION_COORDINATES:
        participant_data[chat_id][username] = {"station": text}
        users_participated[chat_id].add(username)
        display_text = text
        print(f"DEBUG: 駅名受理 [{text}]")
    
    else:
        print(f"DEBUG: リスト外の入力です [{text}]")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"「{text}」は駅名リストにありません。"))
        return

    # 人数チェックとメッセージ送信
    current_count = len(users_participated[chat_id])
    print(f"DEBUG: 現在の参加人数: {current_count} / {REQUIRED_USERS}")

    if current_count >= REQUIRED_USERS:
        print("DEBUG: 目標人数に到達。地図を生成します")
        try:
            send_map_with_pins(chat_id, participant_data[chat_id], line_bot_api, reply_token=event.reply_token)
            # データの初期化
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
        except Exception as e:
            print(f"DEBUG: 地図送信エラー: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"地図送信中にエラーが発生しました: {e}"))
    else:
        status_line = "【報告更新】" if is_update else "【報告受理】"
        reply_text = f"{score_info}{status_line}\n名前: {real_name}\nチーム: {team}\n内容: {display_text}\n現在: {current_count} / {REQUIRED_USERS} 人"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        print("DEBUG: 受理メッセージを送信しました")