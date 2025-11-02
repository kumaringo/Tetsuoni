# Tetsuoni_fixed_upload_normalized_support.py
import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader

# station_data.py から座標データ（比率 or ピクセル）をインポート
from station_data import STATION_COORDINATES

# ==============================
# Flask app
# ==============================
app = Flask(__name__)

# ==============================
# 設定（必要なら編集）
# ==============================
REQUIRED_USERS = 2
PIN_COLOR_RED = (255, 0, 0)
PIN_COLOR_BLUE = (0, 0, 255)
PIN_RADIUS = 10  # 元画像（orig）基準での半径（例: orig が 1000px のときの px）
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

# ==============================
# 環境変数 / Cloudinary 設定
# ==============================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# ==============================
# LINE API 初期化
# ==============================
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==============================
# 参加者データ保持
# ==============================
participant_data = {}
users_participated = {}

# ==============================
# ヘルパー
# ==============================
def get_pin_color(username):
    if username in USER_GROUPS.get("BLUE_GROUP", []):
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED

# ==============================
# Webhook
# ==============================
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

# ==============================
# メッセージ処理（簡易）
# ==============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip() if event.message and event.message.text else ""
    # chat_id 判定（group/room/user）
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    # username 取得（失敗時は Unknown）
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

    # 初期化
    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    # 駅名登録
    if text in STATION_COORDINATES:
        if username in users_participated[chat_id]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。'))
            return

        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 {current_count} 人 / {REQUIRED_USERS} 人'))

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id])
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'「{text}」 はデータに存在しない駅名です。'))

# ==============================
# 画像処理本体（比率 or ピクセル座標を自動判別）
# ==============================
def send_map_with_pins(chat_id, participants):
    """
    ピン位置補正版:
    - Cloudinary へのアップロードによるサイズ変更を無視。
    - ローカルの Rosenzu.png のピクセルサイズ（orig_w, orig_h）を座標の基準にする。
    """

    try:
        orig_path = "Rosenzu.png"
        orig_img = Image.open(orig_path).convert("RGB")
        orig_w, orig_h = orig_img.size  # 例: 1000x1000

        draw = ImageDraw.Draw(orig_img)

        # ピンサイズは固定 (px単位)
        scaled_radius = PIN_RADIUS

        # 各参加者のピンを描画
        for username, data in participants.items():
            station_name = data.get("station")
            pin_color = get_pin_color(username)
            if station_name not in STATION_COORDINATES:
                continue

            x0, y0 = STATION_COORDINATES[station_name]

            # 比率かピクセルか自動判定
            is_normalized = (0.0 <= float(x0) <= 1.0) and (0.0 <= float(y0) <= 1.0)

            if is_normalized:
                x = int(float(x0) * orig_w)
                y = int(float(y0) * orig_h)
            else:
                x = int(float(x0))
                y = int(float(y0))

            # ピン描画
            draw.ellipse(
                (x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                fill=pin_color,
                outline=pin_color
            )

        # Cloudinary にアップロード
        out_buf = io.BytesIO()
        orig_img.save(out_buf, format='PNG')
        out_buf.seek(0)

        final_upload = cloudinary.uploader.upload(
            out_buf,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=True,
            overwrite=True
        )

        image_url = final_upload.get("secure_url") if final_upload else None

        if image_url:
            report_text = f"🚨 参加者 {REQUIRED_USERS} 人分のデータが集まりました！ 🚨\n\n"
            for username, data in participants.items():
                group_color = (
                    "赤" if username in USER_GROUPS.get("RED_GROUP", [])
                    else "青" if username in USER_GROUPS.get("BLUE_GROUP", [])
                    else "不明(赤)"
                )
                report_text += f"- {data.get('username')} ({group_color}G): {data.get('station')}\n"

            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text))
            line_bot_api.push_message(chat_id, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text="❌ エラー: Cloudinary アップロードに失敗しました。"))

    except FileNotFoundError:
        line_bot_api.push_message(chat_id, TextSendMessage(text="❌ エラー: Rosenzu.png が見つかりません。"))
    except Exception as e:
        line_bot_api.push_message(chat_id, TextSendMessage(text=f"❌ 画像処理エラー: {e}"))
     
# ==============================
# 補助関数（必要なら使う）
# ==============================
def upload_to_cloudinary(img_data):
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        print("Cloudinaryの認証情報が設定されていません。")
        return None, {}

    try:
        upload_result = cloudinary.uploader.upload(
            img_data,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True
        )
        secure_url = upload_result.get('secure_url')
        return secure_url, upload_result
    except Exception as e:
        print(f"Cloudinaryアップロードエラー: {e}")
        return None, {}

# ==============================
# ローカル実行用
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
