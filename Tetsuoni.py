# Tetsuoni.py
import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader

# station_data.py から座標データをインポート
from station_data import STATION_COORDINATES

# ==============================
# Flask app (トップレベルで app を定義)
# ==============================
app = Flask(__name__)

# ==============================
# 設定（必要ならここを編集）
# ==============================
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

# ==============================
# 環境変数読み込み / Cloudinary 設定
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
    """ユーザー名に基づいてピンの色を決定（RGBタプルを返す）"""
    if username in USER_GROUPS.get("BLUE_GROUP", []):
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED

# ==============================
# Webhook エンドポイント
# ==============================
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

# ==============================
# メッセージ処理
# ==============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip() if event.message and event.message.text else ""
    # グループ or ルーム ID を取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        # 個別トークの場合は user_id を使う（必要なら）
        chat_id = event.source.user_id

    # ユーザー名を取得
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

    # 駅名がSTATION_COORDINATESにあれば登録
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
            TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 {current_count} 人 / {REQUIRED_USERS} 人')
        )

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id])
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
    else:
        # 未知の駅名
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'「{text}」 はデータに存在しない駅名です。正しい駅名を報告してください。')
        )

# ==============================
# 画像処理: 実保存サイズに合わせてリサイズ → ピン描画 → 再アップロード → LINE送信
# ==============================
def send_map_with_pins(chat_id, participants):
    """
    Cloudinary 側の実際サイズに合わせて画像をリサイズ → ピンを描画 → 再アップロード → LINE送信
    participants: { username: {"username": str, "station": station_name}, ... }
    """
    try:
        # 1) 元画像を読み込み（Rosenzu.png はプロジェクトルートに配置）
        orig_path = "Rosenzu.png"
        orig_img = Image.open(orig_path).convert("RGB")
        orig_w, orig_h = orig_img.size  # 例: 1000,1000 (元基準)

        # 2) 元画像を変換なしで一度 Cloudinary にアップロードして、Cloudinary に保存されたサイズを取得
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

        # 3) Cloudinary に保存されたサイズに合わせてローカル画像をリサイズ
        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = orig_img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = orig_img.copy()

        draw = ImageDraw.Draw(img)

        # 4) 元座標(=STATION_COORDINATES の基準: e.g. 1000x1000) に対するスケールを計算
        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        avg_scale = (scale_x + scale_y) / 2.0
        scaled_radius = max(1, int(PIN_RADIUS * avg_scale))

        # 5) 各参加者の駅にピンを描画
        for username, data in participants.items():
            station_name = data.get("station")
            pin_color = get_pin_color(username)
            if station_name in STATION_COORDINATES:
                # STATION_COORDINATES は (x,y) タプルの辞書であることを想定
                x0, y0 = STATION_COORDINATES[station_name]
                x = int(x0 * scale_x)
                y = int(y0 * scale_y)
                draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                             fill=pin_color, outline=pin_color)

        # 6) 描画済み画像をメモリに保存して Cloudinary に再アップロード
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

        # 7) LINE に結果を送信
        if image_url:
            report_text = f"🚨 参加者 {REQUIRED_USERS} 人分のデータが集まりました！ 🚨\n\n"
            for username, data in participants.items():
                group_color = "赤" if username in USER_GROUPS.get("RED_GROUP", []) else "青" if username in USER_GROUPS.get("BLUE_GROUP", []) else "不明(赤)"
                report_text += f"- {data.get('username')} ({group_color}G): {data.get('station')}\n"

            # デバッグ情報（Cloudinary に保存された実サイズ）
            debug_text = f"(Cloudinary 保存サイズ: {uploaded_w}x{uploaded_h})"
            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text + "\n" + debug_text))

            # 画像を送信
            line_bot_api.push_message(
                chat_id,
                ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            )
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 描画済み画像のアップロードに失敗しました。"))

    except FileNotFoundError:
        line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
    except Exception as e:
        line_bot_api.push_message(chat_id, TextSendMessage(text=f"エラー: 画像処理で問題が発生しました: {e}"))

# ==============================
# 補助: (必要なら別途使う) upload_to_cloudinary 関数
# ==============================
def upload_to_cloudinary(img_data):
    """
    画像をCloudinaryにアップロードし、(secure_url, upload_result) を返す
    （変換を避けたい場合は transformation を付けないで利用）
    """
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
            overwrite=True,
            # transformation=[{"width": 1000, "height": 1000, "crop": "limit"}]  # 必要なら有効化
        )
        secure_url = upload_result.get('secure_url')
        return secure_url, upload_result
    except Exception as e:
        print(f"Cloudinaryアップロードエラー: {e}")
        return None, {}

# ==============================
# アプリ起動（ローカル用）
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
