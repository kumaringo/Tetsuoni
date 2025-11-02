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
    - STATION_COORDINATES の座標が 0..1 の値なら「比率(normalized)」
      それ以外（例えば 300, 500）なら「ピクセル座標（orig基準）」と判定します。
    - ワークフロー:
      1) 元画像を base upload（変換なし）して Cloudinary に保存された実サイズを取得
      2) 実サイズに合わせてローカル画像をリサイズ
      3) 比率 or ピクセルに応じて座標を算出してピン描画
      4) 描画済み画像を再アップロードして LINE に送信
    """
    try:
        orig_path = "Rosenzu.png"
        orig_img = Image.open(orig_path).convert("RGB")
        orig_w, orig_h = orig_img.size  # 例: 1000x1000 を想定

        # base upload（変換なし）で Cloudinary に保存される実サイズを取得
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
            line_bot_api.push_message(chat_id, TextSendMessage(text="Cloudinary にベース画像をアップできませんでした。"))
            return

        uploaded_w = int(base_upload.get("width", orig_w))
        uploaded_h = int(base_upload.get("height", orig_h))

        # 実保存サイズにリサイズ
        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = orig_img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = orig_img.copy()

        draw = ImageDraw.Draw(img)

        # 縮尺（ピン半径用）
        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        avg_scale = (scale_x + scale_y) / 2.0
        scaled_radius = max(1, int(PIN_RADIUS * avg_scale))

        # 各参加者のピン描画
        for username, data in participants.items():
            station_name = data.get("station")
            pin_color = get_pin_color(username)
            if station_name not in STATION_COORDINATES:
                continue

            x0, y0 = STATION_COORDINATES[station_name]

            # 判定: 正規化座標（0..1）かピクセル座標か
            is_normalized = (0.0 <= float(x0) <= 1.0) and (0.0 <= float(y0) <= 1.0)

            if is_normalized:
                # 比率座標 -> 実保存サイズに直接掛ける
                x = int(float(x0) * uploaded_w)
                y = int(float(y0) * uploaded_h)
            else:
                # ピクセル座標（orig基準） -> uploaded サイズへスケーリング
                x = int(float(x0) * (uploaded_w / orig_w))
                y = int(float(y0) * (uploaded_h / orig_h))

            draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                         fill=pin_color, outline=pin_color)

        # 描画済み画像を再アップロード
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

        if image_url:
            report_text = f"🚨 参加者 {REQUIRED_USERS} 人分のデータが集まりました！ 🚨\n\n"
            for username, data in participants.items():
                group_color = "赤" if username in USER_GROUPS.get("RED_GROUP", []) else "青" if username in USER_GROUPS.get("BLUE_GROUP", []) else "不明(赤)"
                report_text += f"- {data.get('username')} ({group_color}G): {data.get('station')}\n"

            debug_text = f"(Cloudinary 保存サイズ: {uploaded_w}x{uploaded_h})"
            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text + "\n" + debug_text))
            line_bot_api.push_message(chat_id, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 描画済み画像のアップロードに失敗しました。"))

    except FileNotFoundError:
        line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
    except Exception as e:
        line_bot_api.push_message(chat_id, TextSendMessage(text=f"エラー: 画像処理で問題が発生しました: {e}"))

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
