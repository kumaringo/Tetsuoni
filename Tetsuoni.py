# Tetsuoni.py（保存サイズ非表示 + デフォルト青ピン 修正版）

import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader
from station_data import STATION_COORDINATES

app = Flask(__name__)

# REQUIRED_USERS を環境変数で上書き可能に（デフォルト 2）
try:
    REQUIRED_USERS = int(os.environ.get('REQUIRED_USERS', '2'))
except ValueError:
    REQUIRED_USERS = 2

PIN_COLOR_RED = (255, 0, 0)
PIN_COLOR_BLUE = (0, 0, 255)
# PIN_RADIUS を環境変数で調整できるように（省略時は 10）
try:
    PIN_RADIUS = int(os.environ.get('PIN_RADIUS', '10'))
except ValueError:
    PIN_RADIUS = 10
# 外枠幅（ピクセル）
try:
    PIN_OUTLINE_WIDTH = int(os.environ.get('PIN_OUTLINE_WIDTH', '2'))
except ValueError:
    PIN_OUTLINE_WIDTH = 2

USER_GROUPS = {
    "RED_GROUP": [
        "なりこう",
        "ひさちゃん",
        "上山of鉄オタ",
        "小林　礼旺"
    ],
    "BLUE_GROUP": [
        
    ]
}

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

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# chat_id 単位で集計
participant_data = {}
users_participated = {}

def get_pin_color(username):
    if username in USER_GROUPS.get("RED_GROUP", []):
        return PIN_COLOR_RED
    return PIN_COLOR_BLUE  # デフォルト青ピン

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
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
    text = event.message.text.strip() if event.message and event.message.text else ""

    # group/room/user の id を chat_id にする
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    # ユーザー名を取得（失敗したら Unknown User）
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

    # 駅名が正しければ participants に追加／更新
    if text in STATION_COORDINATES:
        is_update = username in users_participated[chat_id]
        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])

        if is_update:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さんの報告を「{text}」に更新しました。\n現在 {current_count} 人 / {REQUIRED_USERS} 人')
            )
            if current_count >= REQUIRED_USERS:
                send_map_with_pins(chat_id, participant_data[chat_id], reply_token=event.reply_token)
                participant_data[chat_id] = {}
                users_participated[chat_id] = set()
            return

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id], reply_token=event.reply_token)
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 {current_count} 人 / {REQUIRED_USERS} 人')
            )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'「{text}」 はデータに存在しない駅名です。正しい駅名を報告してください。')
        )

def send_map_with_pins(chat_id, participants, reply_token=None):
    try:
        orig_path = "Rosenzu.png"
        orig_img = Image.open(orig_path).convert("RGBA")
        orig_w, orig_h = orig_img.size

        # ---- 透過 70% の処理 ----
        target_alpha = int(255 * 0.7)
        r, g, b, a = orig_img.split()
        new_alpha = Image.new('L', orig_img.size, color=target_alpha)
        orig_img.putalpha(new_alpha)

        background = Image.new("RGBA", (orig_w, orig_h), (255, 255, 255, 255))
        background.paste(orig_img, (0, 0), orig_img)
        img = background

        buf_base = io.BytesIO()
        img.save(buf_base, format='PNG')
        buf_base.seek(0)

        base_upload = cloudinary.uploader.upload(
            buf_base,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True
        )
        if not base_upload:
            msg = "Cloudinary にベース画像をアップできませんでした。"
            if reply_token:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
            else:
                line_bot_api.push_message(chat_id, TextSendMessage(text=msg))
            return

        uploaded_w = int(base_upload.get("width", orig_w))
        uploaded_h = int(base_upload.get("height", orig_h))

        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = img.copy()

        draw = ImageDraw.Draw(img)

        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        avg_scale = (scale_x + scale_y) / 2.0
        scaled_radius = max(1, int(PIN_RADIUS * avg_scale))
        outline_extra = max(1, int(PIN_OUTLINE_WIDTH * avg_scale))

        for username, data in participants.items():
            station_name = data.get("station")
            pin_color = get_pin_color(username)
            if station_name in STATION_COORDINATES:
                x0, y0 = STATION_COORDINATES[station_name]
                x = int(x0 * scale_x)
                y = int(y0 * scale_y)
                outline_radius = scaled_radius + outline_extra
                draw.ellipse(
                    (x - outline_radius, y - outline_radius, x + outline_radius, y + outline_radius),
                    fill=(0, 0, 0),
                    outline=(0, 0, 0)
                )
                draw.ellipse(
                    (x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                    fill=pin_color,
                    outline=pin_color
                )

        out_buf = io.BytesIO()
        img.save(out_buf, format='PNG')
        out_buf.seek(0)

        final_upload = cloudinary.uploader.upload(
            out_buf,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=True
        )

        image_url = final_upload.get("secure_url") if final_upload else None

        report_text = f"🚨 参加者 {len(participants)} 人分のデータが集まりました！ 🚨\n\n"
        for username, data in participants.items():
            group_color = "赤" if username in USER_GROUPS.get("RED_GROUP", []) else "青" if username in USER_GROUPS.get("BLUE_GROUP", []) else "青(不明)"
            report_text += f"- {data.get('username')} ({group_color}G): {data.get('station')}\n"

        if image_url and reply_token:
            line_bot_api.reply_message(
                reply_token,
                [
                    TextSendMessage(text=report_text),
                    ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
                ]
            )
        elif image_url:
            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text))
            line_bot_api.push_message(chat_id, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        else:
            msg = "エラー: 描画済み画像のアップロードに失敗しました。"
            if reply_token:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
            else:
                line_bot_api.push_message(chat_id, TextSendMessage(text=msg))

    except FileNotFoundError:
        msg = "エラー: Rosenzu.png が見つかりません。"
        if reply_token:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text=msg))
    except Exception as e:
        msg = f"エラー: 画像処理で問題が発生しました: {e}"
        if reply_token:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
