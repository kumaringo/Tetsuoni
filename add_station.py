from linebot.models import TextSendMessage
from station_data import STATION_COORDINATES
from pin import send_map_with_pins

def handle_registration_logic(event, line_bot_api, participant_data, users_participated, USER_CONFIG, REQUIRED_USERS, start_command):
    text = event.message.text.strip() # ここで text として取得
    if not start_command[0]:
        return 
    
    # 1. チャットIDの取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    # 2. ユーザー情報の取得
    user_id = event.source.user_id
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        username = profile.display_name
    except Exception:
        username = "Unknown User"

    # ユーザー設定（チーム・本名）の取得
    config = USER_CONFIG.get(username, {"team": "白", "real_name": username})
    team = config["team"]
    real_name = config["real_name"]

    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    # すでに参加しているか（更新かどうか）の判定
    is_update = username in participant_data[chat_id]

    # 3. 駅名（またはパス）判定とデータ更新
    # 辞書形式 {ユーザー名: {"station": 駅名}} で保存
    if text == "パス":
        participant_data[chat_id][username] = {"station": "パス"}
        users_participated[chat_id].add(username)
    elif text in STATION_COORDINATES:
        participant_data[chat_id][username] = {"station": text}
        users_participated[chat_id].add(username)
    else:
        # リストにない場合はエラー返信して終了
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"「{text}」は駅名リストにありません。")
        )
        return

    # 人数チェック
    current_count = len(users_participated[chat_id])

    if current_count >= REQUIRED_USERS:

        start_command[0] = False
        
        # 地図送信
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
        # 受理メッセージ
        status_line = "【報告更新】" if is_update else "【報告受理】"
        reply_text = f"{status_line}\n名前: {real_name}\nチーム: {team}\n駅名: {text}\n現在: {current_count} / {REQUIRED_USERS} 人"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
