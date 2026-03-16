import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw, ImageFont
import cloudinary
import cloudinary.uploader
# station_data.py から STATION_COORDINATES をインポート
from station_data import STATION_COORDINATES

app = Flask(__name__)

# --- ユーザー設定 ---
USER_CONFIG = {
    "麻生皐聖": {"team": "白", "real_name": "麻生"},
    "伊藤隆": {"team": "赤", "real_name": "伊藤"},
    "上山of鉄オタ": {"team": "赤", "real_name": "上山"},
    "川戸健裕": {"team": "青", "real_name": "川戸"},
    "小林礼旺": {"team": "赤", "real_name": "小林"},
    "うp主": {"team": "青", "real_name": "佐久間"},
    "茂人": {"team": "白", "real_name": "遠藤"},
    "たかぎ": {"team": "白", "real_name": "高木"},
    "村山　そう": {"team": "白", "real_name": "村山"},
    "りゅう": {"team": "青", "real_name": "小澤"},
    "Bootaro": {"team": "赤", "real_name": "仁田"},
    "蒼真": {"team": "赤", "real_name": "工藤"},
    "koki": {"team": "白", "real_name": "猪狩"},
    "Null(教授)": {"team": "青", "real_name": "井原"},
    "@ゆうき@": {"team": "青", "real_name": "二宮"},
}

# チーム名と色の対応（RGB）
TEAM_COLORS = {
    "赤": (255, 0, 0),
    "青": (0, 0, 255),
    "白": (255, 255, 255),
    "重複": (0, 0, 0)
}

# --- 基本設定 ---
try:
    REQUIRED_USERS = int(os.environ.get('REQUIRED_USERS', '15'))
except ValueError:
    REQUIRED_USERS = 15

PIN_RADIUS = 10
PIN_OUTLINE_WIDTH = 2

# LINE & Cloudinary 認証設定
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

# 状態保持用
participant_data = {}
users_participated = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip() if event.message and event.message.text else ""
    
    # 1. スラッシュで始まるメッセージは「完全に無視（無反応）」
    if text.startswith('/'):
        return

    # 2. 以降、スラッシュがないメッセージはすべて反応対象
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        chat_id = event.source.user_id

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

    # 駅名リストに存在する場合
    if text in STATION_COORDINATES:
        is_update = username in users_participated[chat_id]
        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)
        current_count = len(users_participated[chat_id])

        config = USER_CONFIG.get(username, {"team": "白", "real_name": username})
        team = config["team"]
        real_name = config["real_name"]
        
        status_line = "【報告更新】" if is_update else "【報告受理】"
        reply_text = f"{status_line}\n名前: {real_name}\nチーム: {team}\n駅名: {text}\n現在: {current_count} / {REQUIRED_USERS} 人"

        if current_count >= REQUIRED_USERS:
            send_map_with_pins(chat_id, participant_data[chat_id], reply_token=event.reply_token)
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    
    # 駅名リストに存在しないが、スラッシュも付いていない場合
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"「{text}」は駅名リストにありません。正しい駅名を報告してください。")
        )

def send_map_with_pins(chat_id, participants, reply_token=None):
    try:
        orig_img = Image.open("Rosenzu.png").convert("RGBA")
        orig_w, orig_h = orig_img.size

        # 背景の加工
        target_alpha = int(255 * 0.7)
        new_alpha = Image.new('L', orig_img.size, color=target_alpha)
        orig_img.putalpha(new_alpha)
        img = Image.new("RGBA", (orig_w, orig_h), (255, 255, 255, 255))
        img.paste(orig_img, (0, 0), orig_img)

        # Cloudinary アップロード
        buf_base = io.BytesIO()
        img.save(buf_base, format='PNG')
        buf_base.seek(0)
        base_upload = cloudinary.uploader.upload(buf_base, resource_type="image", folder="tetsuoni_maps", overwrite=True)

        uploaded_w = int(base_upload.get("width", orig_w))
        uploaded_h = int(base_upload.get("height", orig_h))
        img = img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        
        draw = ImageDraw.Draw(img)
        scale_x, scale_y = uploaded_w / orig_w, uploaded_h / orig_h
        scaled_radius = max(1, int(PIN_RADIUS * ((scale_x + scale_y) / 2)))
        outline_extra = max(1, int(PIN_OUTLINE_WIDTH * ((scale_x + scale_y) / 2)))

        # --- フォント読み込み（12pxに設定） ---
        font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'NotoSansJP-Regular.ttf')
        try:
            font = ImageFont.truetype(font_path, 12) 
        except:
            font = ImageFont.load_default()

        # 1. データの集約
        station_to_users = {}
        report_buckets = {"赤": [], "青": [], "白": []}

        for username, data in participants.items():
            st_name = data.get("station")
            config = USER_CONFIG.get(username, {"team": "白", "real_name": username})
            team = config["team"]
            real_name = config["real_name"]
            report_buckets[team].append(f"「{team}:{real_name}」: {st_name}")

            if st_name in STATION_COORDINATES:
                if st_name not in station_to_users:
                    station_to_users[st_name] = []
                station_to_users[st_name].append({"team": team, "name": real_name})

        # 2. 描画
        for st_name, users in station_to_users.items():
            x = int(STATION_COORDINATES[st_name][0] * scale_x)
            y = int(STATION_COORDINATES[st_name][1] * scale_y)
            pin_color = TEAM_COLORS["重複"] if len(users) > 1 else TEAM_COLORS.get(users[0]["team"], (255, 255, 255))

            draw.ellipse((x - (scaled_radius + outline_extra), y - (scaled_radius + outline_extra), 
                          x + (scaled_radius + outline_extra), y + (scaled_radius + outline_extra)), fill=(0, 0, 0))
            draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius), fill=pin_color)
            
            # --- テキストの生成と描画（縁取り＆チーム別まとめ） ---
            team_summary = {"赤": [], "青": [], "白": []}
            for u in users:
                team_summary[u['team']].append(u['name'][0]) # 1文字目のみ

            display_lines = []
            for t in ["赤", "青", "白"]:
                if team_summary[t]:
                    # 例：「赤:麻遠」
                    line_txt = f"{t}:{ ''.join(team_summary[t]) }"
                    display_lines.append((t, line_txt))

            current_y = y - scaled_radius
            for t_name, txt in display_lines:
                text_color = TEAM_COLORS.get(t_name, (255, 255, 255))
                text_pos = (x + scaled_radius + 5, current_y)
                
                # 縁取り描画（周囲8方向を黒で描画）
                for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1),(0,-1),(0,1),(-1,0),(1,0)]:
                    draw.text((text_pos[0]+dx, text_pos[1]+dy), txt, fill=(0,0,0), font=font)
                # 本体描画（チーム色）
                draw.text(text_pos, txt, fill=text_color, font=font)
                current_y += 14 # 改行幅

        # 3. 出力
        out_buf = io.BytesIO()
        img.save(out_buf, format='PNG')
        out_buf.seek(0)
        final_upload = cloudinary.uploader.upload(out_buf, resource_type="image", folder="tetsuoni_maps")
        image_url = final_upload.get("secure_url")

        report_text = f"🚨 参加者 {len(participants)} 人のデータ 🚨\n"
        for t in ["赤", "青", "白"]:
            if report_buckets[t]:
                report_text += "\n" + "\n".join(report_buckets[t])

        if image_url:
            msg = [TextSendMessage(text=report_text.strip()), ImageSendMessage(image_url, image_url)]
            if reply_token:
                line_bot_api.reply_message(reply_token, msg)
            else:
                line_bot_api.push_message(chat_id, msg)

    except Exception as e:
        if reply_token:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"描画エラー: {e}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
