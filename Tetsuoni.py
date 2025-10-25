# -*- coding: utf-8 -*-
import os
import io
import json
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageSendMessage, TextSendMessage
from PIL import Image, ImageDraw

# 外部ファイルから駅データをインポート
from station_data import STATION_COORDINATES

# --- 環境変数設定 ---
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
IMGBB_API_KEY = os.getenv('IMGUR_CLIENT_ID')

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 状態管理 ---
player_stations = {}  # user_id: station_name
REQUIRED_PLAYERS = 4  # 4人で確定


# --- ImgBBへのアップロード関数 ---
def upload_image_to_imgbb(image_io):
    if not IMGBB_API_KEY:
        print("Error: IMGBB_API_KEY is not set.")
        return None

    image_io.seek(0)
    base64_image = base64.b64encode(image_io.read()).decode('utf-8')
    url = "https://api.imgbb.com/1/upload"
    data = {'key': IMGBB_API_KEY, 'image': base64_image, 'name': 'rosenzu.jpeg'}

    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get('success'):
            return result['data']['url']
        else:
            print("ImgBB upload failed:", result)
            return None
    except Exception as e:
        print("Error during upload:", e)
        return None


# --- 駅ピン描画 ---
def draw_multiple_pins(stations):
    try:
        image = Image.open("Rosenzu.png").convert("RGB")
    except FileNotFoundError:
        print("Error: Rosenzu.png not found.")
        return None

    draw = ImageDraw.Draw(image)

    for station_name in stations:
        if station_name not in STATION_COORDINATES:
            print(f"Error: {station_name} not found in coordinates.")
            continue

        x, y = STATION_COORDINATES[station_name]
        radius = 20
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill="red",
            outline="white",
            width=4
        )

    img_io = io.BytesIO()
    image.save(img_io, format='JPEG')
    img_io.seek(0)
    return img_io


# --- LINE Webhook ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# --- メッセージ処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    user_id = event.source.user_id

    # --- 駅名が有効か ---
    if msg in STATION_COORDINATES:
        player_stations[user_id] = msg
        current_count = len(player_stations)
        remaining = REQUIRED_PLAYERS - current_count

        if current_count < REQUIRED_PLAYERS:
            # まだ人数が足りない
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"{msg} を登録しました！（残り {remaining} 人）")
            )
        else:
            # 4人そろった！
            stations = list(player_stations.values())
            image_io = draw_multiple_pins(stations)

            if image_io:
                image_url = upload_image_to_imgbb(image_io)
                if image_url:
                    line_bot_api.reply_message(
                        event.reply_token,
                        ImageSendMessage(
                            original_content_url=image_url,
                            preview_image_url=image_url
                        )
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="画像アップロードに失敗しました。")
                    )
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="画像生成に失敗しました。Rosenzu.png が見つからない可能性があります。")
                )

            # 次のラウンドに備えてリセット
            player_stations.clear()

    # --- デバッグコマンド ---
    elif msg == 'リセット':
        player_stations.clear()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="プレイヤーデータをリセットしました。")
        )

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="駅名を入力してください。4人そろうと路線図にピンを打ちます。")
        )


# --- Flask起動 ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
