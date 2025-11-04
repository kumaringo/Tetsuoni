# Tetsuoni.py (修正版)
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

REQUIRED_USERS = 1
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

participant_data = {}
users_participated = {}

def get_pin_color(username):
    if username in USER_GROUPS.get("BLUE_GROUP", []):
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED

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

    # 駅名が正しければ先に participants に追加（ただし重複報告は弾く）
    if text in STATION_COORDINATES:
        if username in users_participated[chat_id]:
            # 既報告者には即座に reply（閾値未満での簡易応答）
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。')
            )
            return

        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])

        # ここで閾値に達したかをチェックして、達していれば**reply_token を使って一度に**結果（テキスト＋画像）を返す
        if current_count >= REQUIRED_USERS:
            # reply_token を渡して reply で画像を送る（reply_token は1回だけ使える点に注意）
            send_map_with_pins(chat_id, participant_data[chat_id], reply_token=event.reply_token)
            # 送ったらデータ初期化
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
        else:
            # 閾値に達していない場合は通常の確認メッセージを reply
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
        orig_img = Image.open(orig_path).convert("RGB")
        orig_w, orig_h = orig_img.size

        buf_base = io.BytesIO()
        orig_img.save(buf_base, format='PNG')
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
            if reply_token:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="Cloudinary にベース画像をアップできませんでした。"))
            else:
                line_bot_api.push_message(chat_id, TextSendMessage(text="Cloudinary にベース画像をアップできませんでした。"))
            return

        uploaded_w = int(base_upload.get("width", orig_w))
        uploaded_h = int(base_upload.get("height", orig_h))

        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = orig_img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = orig_img.copy()

        draw = ImageDraw.Draw(img)

        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        avg_scale = (scale_x + scale_y) / 2.0
        scaled_radius = max(1, int(PIN_RADIUS * avg_scale))

        for username, data in participants.items():
            station_name = data.get("station")
            pin_color = get_pin_color(username)
            if station_name in STATION_COORDINATES:
                x0, y0 = STATION_COORDINATES[station_name]
                x = int(x0 * scale_x)
                y = int(y0 * scale_y)
                draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                             fill=pin_color, outline=pin_color)

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
            group_color = "赤" if username in USER_GROUPS.get("RED_GROUP", []) else "青" if username in USER_GROUPS.get("BLUE_GROUP", []) else "不明(赤)"
            report_text += f"- {data.get('username')} ({group_color}G): {data.get('station')}\n"
        debug_text = f"(Cloudinary 保存サイズ: {uploaded_w}x{uploaded_h})"

        # reply_token がある時は reply_message で一度に返す（安全で確実）
        if image_url and reply_token:
            # 送信：テキスト（報告） + 画像
            line_bot_api.reply_message(
                reply_token,
                [
                    TextSendMessage(text=report_text + "\n" + debug_text),
                    ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
                ]
            )
        elif image_url:
            # reply_token が無い（外部トリガなど）場合は push_message にフォールバック
            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text + "\n" + debug_text))
            line_bot_api.push_message(chat_id, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        else:
            # 画像 URL が取れなかった場合
            if reply_token:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="エラー: 描画済み画像のアップロードに失敗しました。"))
            else:
                line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 描画済み画像のアップロードに失敗しました。"))

    except FileNotFoundError:
        if reply_token:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
    except Exception as e:
        # ここではエラーメッセージを送ってデバッグしやすくする
        if reply_token:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"エラー: 画像処理で問題が発生しました: {e}"))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text=f"エラー: 画像処理で問題が発生しました: {e}"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
