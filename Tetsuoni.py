import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader

# 駅座標データ（ピクセル単位）
# station_data.py が同じディレクトリにあることを確認してください
from station_data import STATION_COORDINATES

# ==============================
# Flask app
# ==============================
app = Flask(__name__)

# ==============================
# 定数設定
# ==============================
REQUIRED_USERS = 1  # 必要人数
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
# 環境変数
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
# データ保持
# ==============================
participant_data = {}
users_participated = {}

# ==============================
# ユーティリティ
# ==============================
def get_pin_color(username):
    """ユーザー名でピン色を決定"""
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

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature.")
        abort(400)

    return 'OK'

# ==============================
# メッセージ処理
# ==============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip() if event.message and event.message.text else ""

    # グループ / ルーム / 個別トークを区別
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

    # ユーザー名取得
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

    # グループごとの初期化
    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    # 駅名が存在するかチェック
    if text in STATION_COORDINATES:
        if username in users_participated[chat_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さん、すでに報告済みです。')
            )
            return

        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 {current_count} / {REQUIRED_USERS} 人')
        )

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id])
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()

    else:
        # 未知の駅名
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f'「{text}」 はデータに存在しません。')
        )

# ==============================
# ピン付きマップ送信 (★★★ 修正版 ★★★)
# ==============================
def send_map_with_pins(chat_id, participants):
    """
    ピクセル座標に基づいてピンを描画し、Cloudinaryにアップロードして送信
    (ローカルでのスケーリング処理を維持しつつ、LINE API要件に対応)
    """
    try:
        base_img = Image.open("Rosenzu.png").convert("RGB")
        orig_w, orig_h = base_img.size

        # --- 既存のスケーリングロジック (変更なし) ---
        # 1. Cloudinaryにベース画像をアップロードし、実際のサイズを取得
        buf = io.BytesIO()
        base_img.save(buf, format='PNG')
        buf.seek(0)

        upload_info = cloudinary.uploader.upload(
            buf,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True,
            transformation=[]  # Cloudinaryの自動リサイズ防止
        )

        uploaded_w = int(upload_info.get("width", orig_w))
        uploaded_h = int(upload_info.get("height", orig_h))
        
        # (デバッグ用) どのサイズで認識されたか確認
        print(f"Original size: {orig_w}x{orig_h}, Cloudinary base size: {uploaded_w}x{uploaded_h}")

        # 2. 取得したサイズに基づいてローカルでリサイズ
        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = base_img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = base_img.copy()

        draw = ImageDraw.Draw(img)

        # 3. スケールを計算
        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        scaled_radius = max(2, int(PIN_RADIUS * (scale_x + scale_y) / 2))

        # 4. ピンをローカルの 'img' に描画
        print("描画対象:", participants)
        for username, data in participants.items():
            station = data["station"]
            if station not in STATION_COORDINATES:
                continue

            x_raw, y_raw = STATION_COORDINATES[station]  # 元のピクセル座標
            x = int(x_raw * scale_x) # スケーリング適用
            y = int(y_raw * scale_y) # スケーリング適用

            color = get_pin_color(username)

            draw.ellipse(
                (x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                fill=color,
                outline=(0, 0, 0),
                width=2
            )
        # --- 既存のスケーリングロジック (ここまで) ---


        # ==== ★★★ 修正点 ここから ★★★ ====
        # ローカルで描画済みの画像(img)を、LINE要件に合わせてアップロード

        buf_out = io.BytesIO()
        img.save(buf_out, format='PNG') # ピン描画済みの画像を保存
        buf_out.seek(0)

        # 1. 本画像用 (1024x1024以内のPNG)
        main_image_transform = [
            {'width': 1024, 'height': 1024, 'crop': 'limit', 'format': 'png'}
        ]
        
        # 2. プレビュー用 (240x240以内のJPEG)
        eager_preview_transform = {
            'width': 240, 'height': 240, 'crop': 'limit', 'format': 'jpg'
        }

        # 描画済みの画像を、LINE要件に合わせて2種類生成するようアップロード
        final_upload = cloudinary.uploader.upload(
            buf_out, 
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=True,
            transformation=main_image_transform, # ← 本画像用 (1024x1024 PNG)
            eager=[eager_preview_transform]      # ← プレビュー用 (240x240 JPG)
        )

        # 2つの異なるURLを正しく取得する
        final_url = final_upload.get("secure_url") # 1024x1024 PNGのURL
        
        preview_url = None
        if final_upload.get("eager"):
            preview_url = final_upload["eager"][0].get("secure_url") # 240x240 JPGのURL

        print("✅ Cloudinary final_url (Original):", final_url)
        print("✅ Cloudinary preview_url (Preview):", preview_url)

        if not final_url or not preview_url:
            line_bot_api.push_message(chat_id, TextSendMessage(text="画像アップロードに失敗しました。"))
            return
        # ==== ★★★ 修正点 ここまで ★★★ ====

        # 集計テキスト
        summary = "🚉 全員の報告が揃いました！\n\n"
        for u, d in participants.items():
            group_color = (
                "赤" if u in USER_GOVERNMENT.get("RED_GROUP", []) else
                "青" if u in USER_GROUPS.get("BLUE_GROUP", []) else "不明"
            )
            summary += f"- {d['username']} ({group_color}G): {d['station']}\n"

        # 送信
        try:
            line_bot_api.push_message(chat_id, TextSendMessage(text=summary))
            
            # ★★★ 修正点 ★★★
            # 2つの異なるURLを正しく指定する
            line_bot_api.push_message(chat_id, ImageSendMessage(
                original_content_url=final_url,    # 本画像URL (1024x1024 PNG)
                preview_image_url=preview_url      # プレビュー専用URL (240x240 JPG)
            ))
            print("✅ LINE送信完了")
        except Exception as e:
            print("❌ 送信エラー:", e)
            line_bot_api.push_message(chat_id, TextSendMessage(text=f"送信エラー: {e}"))

    except Exception as e:
        print("❌ 全体エラー:", e)
        line_bot_api.push_message(chat_id, TextSendMessage(text=f"エラーが発生しました: {e}"))

# ==============================
# ローカル起動
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)