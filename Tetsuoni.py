# Tetsuoni.py

import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import requests
import io 
import cloudinary 
import cloudinary.uploader 
# import cloudinary.utils # URL生成にsecure_urlを直接使うため不要

# station_data.py から座標データをインポート
from station_data import STATION_COORDINATES 

# --- 設定項目（ここを変更して再デプロイしてください） ---

# 1. 何人分のデータを集めるかの人数 (x)
REQUIRED_USERS = 1 

# 2. ピン設定
PIN_COLOR_RED = (255, 0, 0)      # 赤グループのピンの色 (RGB)
PIN_COLOR_BLUE = (0, 0, 255)    # 青グループのピンの色 (RGB)
PIN_RADIUS = 10                  # ピンの半径（ピクセル）

# 3. グループ分け設定
USER_GROUPS = {
    "RED_GROUP": [
        "茂野大雅",
        "茂野大雅あ"
    ],
    "BLUE_GROUP": [
        "茂野大雅い",
        "茂野大雅う"
    ]
}
# --- 設定項目 終了 ---


# --- 環境変数からAPIキーを読み込み ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME') 
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

# 👈 Cloudinaryの設定
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

# --- LINE APIとFlaskの初期化 ---
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 参加者のデータ保持 ---
participant_data = {} 
users_participated = {} 

# --- グループ判定ヘルパー関数 ---
def get_pin_color(username):
    """ユーザー名に基づいてピンの色を決定する"""
    if username in USER_GROUPS["BLUE_GROUP"]:
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED


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
    
    # グループIDまたはルームIDを取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        return

    # ユーザー名を取得
    try:
        user_id = event.source.user_id 
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

    
    # 駅名リストに含まれるかチェック
    if text in STATION_COORDINATES:
        
        # ユーザー名で重複チェック
        if username in users_participated[chat_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。')
            )
            return
            
        # データ記録
        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username) 
        
        # 報告メッセージ
        current_count = len(users_participated[chat_id])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 **{current_count} 人** / **{REQUIRED_USERS} 人**')
        )

        # 人数が集まったかチェック
        if current_count >= REQUIRED_USERS:
            # ピン打ち処理と送信
            send_map_with_pins(chat_id, participant_data[chat_id])

            # データリセット
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()

    else:
        # 未知の駅名への応答
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'**「{text}」** はデータに存在しない駅名です。正しい駅名を報告してください。')
        )

# --- ピン打ちと送信のメイン関数 ---
def send_map_with_pins(chat_id, participants):
    """路線図にピンを打ち、Cloudinaryにアップロード後、LINEに送信する"""
    
    # 1. 画像処理（ピン打ち）
    img_byte_arr = io.BytesIO()
    
    try:
        # Rosenzu.pngを読み込み (サイズ 1000x1000 を想定)
        img = Image.open("Rosenzu.png").convert("RGB")
        draw = ImageDraw.Draw(img)
        
        # ピンを打つ処理
        for username, data in participants.items():
            station_name = data["station"]
            pin_color = get_pin_color(username) 
            
            if station_name in STATION_COORDINATES:
                # 📌 station_dataの座標をそのまま使用（拡大・割り戻しなし）
                x, y = STATION_COORDINATES[station_name]
                
                # 円（ピン）を描画
                draw.ellipse((x - PIN_RADIUS, y - PIN_RADIUS, x + PIN_RADIUS, y + PIN_RADIUS), 
                             fill=pin_color, outline=pin_color)

        # メモリ内のバッファにPNG形式で保存
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0) 

    except FileNotFoundError:
        message = "エラー: Rosenzu.pngファイルが見つかりません。デプロイを確認してください。"
        line_bot_api.push_message(chat_id, TextSendMessage(text=message))
        return
    except Exception as e:
        message = f"エラー: 画像処理中に問題が発生しました。{e}"
        line_bot_api.push_message(chat_id, TextSendMessage(text=message))
        return

    # 2. Cloudinaryにアップロード
    # 👈 secure_url を取得
    image_url = upload_to_cloudinary(img_byte_arr) 
    
    # 3. LINEに送信
    if image_url:
        # 報告内容のテキストを生成
        report_text = f"🚨 参加者 **{REQUIRED_USERS} 人**分のデータが集まりました！ 🚨\n\n"
        for username, data in participants.items():
            # どのグループかを付記
            group_color = "赤" if username in USER_GROUPS["RED_GROUP"] else "青" if username in USER_GROUPS["BLUE_GROUP"] else "不明(赤)"
            report_text += f"- **{data['username']}** ({group_color}G): **{data['station']}**\n"
        
        # 画像とテキストを同時に送信
        line_bot_api.push_message(
            chat_id,
            [
                TextSendMessage(text=report_text),
                ImageSendMessage(
                    original_content_url=image_url, # 📌 secure_url を使用
                    preview_image_url=image_url    # 📌 secure_url を使用
                )
            ]
        )
    else:
        # アップロード失敗時のメッセージ
        line_bot_api.push_message(
            chat_id,
            TextSendMessage(text="エラー: 路線図画像のアップロードに失敗しました。")
        )
        
    # メモリ内なので削除処理は不要


# --- Cloudinaryアップロード関数 ---
def upload_to_cloudinary(img_data):
    """画像をCloudinaryにアップロードし、URLを返す（変換設定なし）"""
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        print("Cloudinaryの認証情報が設定されていません。")
        return None

    try:
        # Cloudinary Uploaderを使用してアップロード
        # 📌 変換パラメータなしで、Cloudinaryのデフォルト設定に任せる
        upload_result = cloudinary.uploader.upload(
            img_data, 
            resource_type="image", 
            folder="tetsuoni_maps" 
        )
        
        # アップロードが成功した場合、URLを返す
        return upload_result.get("secure_url")
        
    except Exception as e:
        print(f"Cloudinaryアップロードエラー: {e}")
        return None

# --- アプリの実行（Renderではgunicornが実行） ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)