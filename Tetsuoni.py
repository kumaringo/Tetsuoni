# Tetsuoni_fixed_upload.py
# 元の Tetsuoni.py をベースに、Cloudinary にオリジナル (1000x1000) のままアップロードする
# 変更点:
# - cloudinary.config に secure=True を追加
# - upload_to_cloudinary で transformation={'width':1000,'height':1000,'crop':'limit'} を付け、
#   アップロード後に返る width/height を確認して、もし1000x1000 でなければ LINE に警告を送る
# - 既存の処理ロジックは維持

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
# station_data.py から座標データをインポート
from station_data import STATION_COORDINATES

# --- 設定項目（ここを変更して再デプロイしてください） ---
REQUIRED_USERS = 2
PIN_COLOR_RED = (255, 0, 0)
PIN_COLOR_BLUE = (0, 0, 255)
PIN_RADIUS = 10
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

# 👈 Cloudinaryの設定（secure=True を明示）
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# --- LINE APIとFlaskの初期化 ---
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

participant_data = {}
users_participated = {}


def get_pin_color(username):
    if username in USER_GROUPS["BLUE_GROUP"]:
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED


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


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        return

    try:
        user_id = event.source.user_id
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(chat_id, user_id)
        username = profile.display_name
    except Exception:
        username = "Unknown User"

    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    if text in STATION_COORDINATES:
        if username in users_participated[chat_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。')
            )
            return

        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 **{current_count} 人** / **{REQUIRED_USERS} 人**')
        )

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id])
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'**「{text}」** はデータに存在しない駅名です。正しい駅名を報告してください。')
        )


def send_map_with_pins(chat_id, participants):
    img_byte_arr = io.BytesIO()

    try:
        # 元画像は 1000x1000 を想定
        img = Image.open("Rosenzu.png").convert("RGB")
        draw = ImageDraw.Draw(img)

        for username, data in participants.items():
            station_name = data["station"]
            pin_color = get_pin_color(username)
            if station_name in STATION_COORDINATES:
                x, y = STATION_COORDINATES[station_name]
                draw.ellipse((x - PIN_RADIUS, y - PIN_RADIUS, x + PIN_RADIUS, y + PIN_RADIUS),
                             fill=pin_color, outline=pin_color)

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

    # アップロード（オリジナル 1000x1000 を維持するため transform: limit を指定）
    image_url, upload_info = upload_to_cloudinary(img_byte_arr)

    if image_url:
        # アップロード後に Cloudinary 側で実際に保存されたサイズを確認
        uploaded_w = upload_info.get('width')
        uploaded_h = upload_info.get('height')

        if uploaded_w != 1000 or uploaded_h != 1000:
            warn_text = f"警告: Cloudinary に保存された画像サイズが期待(1000x1000)と異なります: {uploaded_w}x{uploaded_h}"
            line_bot_api.push_message(chat_id, TextSendMessage(text=warn_text))

        report_text = f"🚨 参加者 **{REQUIRED_USERS} 人**分のデータが集まりました！ 🚨\n\n"
        for username, data in participants.items():
            group_color = "赤" if username in USER_GROUPS["RED_GROUP"] else "青" if username in USER_GROUPS["BLUE_GROUP"] else "不明(赤)"
            report_text += f"- **{data['username']}** ({group_color}G): **{data['station']}**\n"

        line_bot_api.push_message(
            chat_id,
            [
                TextSendMessage(text=report_text),
                ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            ]
        )
    else:
        line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 路線図画像のアップロードに失敗しました。"))


def upload_to_cloudinary(img_data):
    """画像をCloudinaryにアップロードし、(secure_url, upload_result) を返す
       重要: transformation に crop: 'limit' を付けることで "拡大" を防ぎ、1000x1000 を維持するよう指示する
    """
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        print("Cloudinaryの認証情報が設定されていません。")
        return None, {}

    try:
        # ここが重要: width/heightを1000に limit 指定 (アップロード時に拡大はされない)
        upload_result = cloudinary.uploader.upload(
            img_data,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True,
            transformation=[{"width": 1000, "height": 1000, "crop": "limit"}]
        )

        secure_url = upload_result.get('secure_url')
        return secure_url, upload_result

    except Exception as e:
        print(f"Cloudinaryアップロードエラー: {e}")
        return None, {}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
