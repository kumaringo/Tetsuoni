# Tetsuoni.py

import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import requests

# 💡 修正 1: インポートする変数を STATION_COORDINATES のみに変更
from station_data import STATION_COORDINATES 

# 💡 修正 2: ピンの設定を Tetsuoni.py 内に定義
PIN_COLOR = (255, 0, 0) # 赤
PIN_RADIUS = 10 # 半径

# --- 環境変数から設定を読み込み ---
# ... (以降のコードは変更なし)
# --- 環境変数から設定を読み込み ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY')
# x人のグループ参加者
try:
    REQUIRED_USERS = int(os.environ.get('REQUIRED_USERS', 2)) # デフォルトを2人に設定
except ValueError:
    REQUIRED_USERS = 2

# --- LINE APIとFlaskの初期化 ---
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 参加者のデータ保持 ---
# キーはgroup_id/room_id、値は参加者の辞書 {user_id: {"username": str, "station": str}}
participant_data = {} 
# 参加済みユーザーのセット {group_id: {user_id1, user_id2, ...}}
users_participated = {}


# --- WebhookのコールバックURL ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    return 'OK'

# --- メッセージイベントの処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    user_id = event.source.user_id
    
    # グループIDまたはルームIDを取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        # グループ/ルーム以外のメッセージは無視または個別処理
        return

    # ユーザー名を取得
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(chat_id, user_id)
        username = profile.display_name
    except Exception:
        username = "Unknown User"


    # 参加者データと参加済みユーザーセットを初期化
    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    
    # --- 💡 修正: 駅名チェックと応答処理 ---
    # 駅名リストに含まれるかチェック
    if text in STATION_COORDINATES:
        
        # ユーザーがすでに駅を言っているかチェック
        if user_id in users_participated[chat_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。')
            )
            return
            
        # データ記録
        participant_data[chat_id][user_id] = {"username": username, "station": text}
        users_participated[chat_id].add(user_id)
        
        # 報告メッセージ
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 **{len(users_participated[chat_id])} 人** / **{REQUIRED_USERS} 人**')
        )

        # 人数が集まったかチェック
        if len(users_participated[chat_id]) >= REQUIRED_USERS:
            # ピン打ち処理と送信
            send_map_with_pins(chat_id, participant_data[chat_id])

            # データリセット
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()

    else:
        # 💡 修正: 未知の駅名への応答（「存在しない駅名」として返信）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'**「{text}」** はデータに存在しない駅名です。正しい駅名を報告してください。')
        )

# --- ピン打ちと送信のメイン関数 ---
def send_map_with_pins(chat_id, participants):
    """路線図にピンを打ち、IMGBBにアップロード後、LINEに送信する"""
    
    # 1. 画像処理（ピン打ち）
    try:
        # Rosenzu.pngを読み込み
        img = Image.open("Rosenzu.png").convert("RGB")
        draw = ImageDraw.Draw(img)
        
        # ピンを打つ処理
        for user_id, data in participants.items():
            station_name = data["station"]
            if station_name in STATION_COORDINATES:
                x, y = STATION_COORDINATES[station_name]
                # 円（ピン）を描画
                draw.ellipse((x - PIN_RADIUS, y - PIN_RADIUS, x + PIN_RADIUS, y + PIN_RADIUS), 
                             fill=PIN_COLOR, outline=PIN_COLOR)

        # 一時ファイルに保存
        temp_filename = "temp_rosenzu_pinned.png"
        img.save(temp_filename, "PNG")

    except FileNotFoundError:
        message = "エラー: Rosenzu.pngファイルが見つかりません。"
        line_bot_api.push_message(chat_id, TextSendMessage(text=message))
        return
    except Exception as e:
        message = f"エラー: 画像処理中に問題が発生しました。{e}"
        line_bot_api.push_message(chat_id, TextSendMessage(text=message))
        return

    # 2. IMGBBにアップロード
    image_url = upload_to_imgbb(temp_filename)
    
    # 3. LINEに送信
    if image_url:
        # 報告内容のテキストを生成
        report_text = f"🚨 参加者 **{REQUIRED_USERS} 人**分のデータが集まりました！ 🚨\n\n"
        for user_id, data in participants.items():
            report_text += f"- **{data['username']}**: **{data['station']}**\n"
        
        # 画像とテキストを同時に送信
        line_bot_api.push_message(
            chat_id,
            [
                TextSendMessage(text=report_text),
                ImageSendMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url # プレビュー画像も同じURLを使用
                )
            ]
        )
    else:
        # アップロード失敗時のメッセージ
        line_bot_api.push_message(
            chat_id,
            TextSendMessage(text="エラー: 路線図画像のアップロードに失敗しました。")
        )
        
    # 一時ファイルを削除
    if os.path.exists(temp_filename):
        os.remove(temp_filename)


# --- IMGBBアップロード関数 (変更なし) ---
def upload_to_imgbb(filepath):
    """画像をIMGBBにアップロードし、URLを返す"""
    if not IMGBB_API_KEY:
        print("IMGBB API Keyが設定されていません。")
        return None

    url = "https://api.imgbb.com/1/upload"
    try:
        with open(filepath, "rb") as file:
            response = requests.post(url, 
                                     params={"key": IMGBB_API_KEY}, 
                                     files={"image": file})
            response.raise_for_status() # HTTPエラーを確認

            result = response.json()
            if result.get("success"):
                return result["data"]["url"]
            else:
                print(f"IMGBBアップロード失敗: {result.get('error', {}).get('message', '不明なエラー')}")
                return None
    except Exception as e:
        print(f"IMGBBアップロードエラー: {e}")
        return None

# --- アプリの実行（Renderではgunicornが実行） ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)