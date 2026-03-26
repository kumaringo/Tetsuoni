import os
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader
from linebot.models import ImageSendMessage, TextSendMessage

# ユーザー設定（チーム分けなど）
USER_CONFIG = {
    "茂野大雅": {"team": "白", "real_name": "茂野大雅"},
    "Bootaro": {"team": "青", "real_name": "ぷーたろう"},
    # 必要に応じてここに追加
}

# Cloudinaryの設定（Renderの環境変数から読み込み）
cloudinary.config(
    cloudinary_url=os.environ.get('CLOUDINARY_URL')
)

def send_map_with_pins(chat_id, participant_data, line_bot_api, reply_token=None):
    from station_data import STATION_COORDINATES
    
    # 1. 地図の下に表示する「テキスト一覧」を作成
    display_lines = []
    for name, data in participant_data.items():
        # 【重要】管理用データ（_rules）は無視して、人間だけをリストに入れる
        if name.startswith('_'):
            continue
            
        config = USER_CONFIG.get(name, {"team": "白", "real_name": name})
        team = config["team"]
        real_name = config["real_name"]
        station = data.get("station", "不明")
        display_lines.append(f"「{team}:{real_name}」: {station}")

    summary_text = f"🚨 参加者 {len(display_lines)} 人のデータ 🚨\n" + "\n".join(display_lines)

    # 2. 地図画像の生成（Pillow）
    base_map_path = "Rosenzu.PNG" # サーバー上の地図画像
    if not os.path.exists(base_map_path):
        line_bot_api.reply_message(reply_token, TextSendMessage(text="地図ファイルが見つかりません。"))
        return

    img = Image.open(base_map_path)
    draw = ImageDraw.Draw(img)

    # ピンを打つ処理
    for name, data in participant_data.items():
        if name.startswith('_'): continue
        station_name = data.get("station")
        if station_name in STATION_COORDINATES:
            x, y = STATION_COORDINATES[station_name]
            # 赤い丸を打つ
            radius = 10
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(255, 0, 0), outline=(0, 0, 0))

    # 3. 画像を一時保存して Cloudinary にアップロード
    temp_path = "temp_result.png"
    img.save(temp_path)
    
    upload_result = cloudinary.uploader.upload(temp_path)
    image_url = upload_result['secure_url']

    # 4. LINEに送信（画像とテキストの両方）
    messages = [
        TextSendMessage(text=summary_text),
        ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
    ]
    
    if reply_token:
        line_bot_api.reply_message(reply_token, messages)
    else:
        line_bot_api.push_message(chat_id, messages)
