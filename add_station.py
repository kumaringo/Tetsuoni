# add_station.py
from linebot.models import TextSendMessage
from station_data import STATION_COORDINATES # STATION_DATAからインポート
from pin import send_map_with_pins

def handle_registration_logic(event, line_bot_api, participant_data, users_participated, USER_CONFIG, REQUIRED_USERS):
    text = event.message.text.strip()
    
    # 1. チャットIDの取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    # 2. ユーザー名の取得
    try:
        user_id = event.source.user_id
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(chat_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        username = profile.display_name
    except Exception:
        username = "Unknown User"

    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    # 3. 駅名判定とデータ更新
    if station_name == "パス":
        # 座標を None として登録（カウントには含める）
        participant_data[chat_id].append({"name": "パス", "coords": None})
        users_participated.add(chat_id)
    # --- ここまで追加 ---
    
    elif station_name in STATION_COORDINATES:
        # 通常の駅登録処理
        coords = STATION_COORDINATES[station_name]
        participant_data[chat_id].append({"name": station_name, "coords": coords})
        users_participated.add(chat_id)
    else:
        # 駅が見つからない場合（スルーまたはエラー返信）
        return
        # --- ここからが「丸投げ」のための追加ロジック ---

        if current_count >= REQUIRED_USERS:
            # 【重要】人数が揃ったので pin.py の関数を呼び出す
            send_map_with_pins(
                chat_id, 
                participant_data[chat_id], 
                line_bot_api, 
                reply_token=event.reply_token
            )
            # データの初期化
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
        else:
            # まだ人数が揃っていないので、受理メッセージを送る
            status_line = "【報告更新】" if is_update else "【報告受理】"
            reply_text = f"{status_line}\n名前: {real_name}\nチーム: {team}\n駅名: {text}\n現在: {current_count} / {REQUIRED_USERS} 人"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            
    else:
        # 駅名リストにない場合
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"「{text}」は駅名リストにありません。")
        )
