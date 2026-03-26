import os
import io
from PIL import Image, ImageDraw, ImageFont
import cloudinary
import cloudinary.uploader
from linebot.models import TextSendMessage, ImageSendMessage
from station_data import STATION_COORDINATES

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
    "りゅう": {"team": "青", "real_name": "澤澤"},
    "Bootaro": {"team": "赤", "real_name": "仁田"},
    "蒼真": {"team": "赤", "real_name": "工藤"},
    "koki": {"team": "白", "real_name": "猪狩"},
    "Null(教授)": {"team": "青", "real_name": "井原"},
    "@ゆうき@": {"team": "青", "real_name": "二宮"},
}

TEAM_COLORS = {
    "赤": (255, 0, 0),
    "青": (0, 191, 255),
    "白": (255, 255, 255),
    "重複": (0, 0, 0)
}

PIN_RADIUS = 10
PIN_OUTLINE_WIDTH = 2

CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

def send_map_with_pins(chat_id, participants, line_bot_api, reply_token=None):
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

        # --- フォント読み込み ---
        font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'NotoSansJP-Regular.ttf')
        try:
            font = ImageFont.truetype(font_path, 16) 
        except:
            font = ImageFont.load_default()

        # 1. データの集約
        station_to_users = {}
        report_buckets = {"赤": [], "青": [], "白": []}

        for username, data in participants.items():
            st_name = data.get("station")
            
            # --- 修正箇所: 駅名が None や空文字の場合はスキップ ---
            if not st_name:
                continue
            # -----------------------------------------------

            config = USER_CONFIG.get(username, {"team": "白", "real_name": username})
            team = config["team"]
            real_name = config["real_name"]
            report_buckets[team].append(f"「{team}:{real_name}」: {st_name}")

            if st_name in STATION_COORDINATES:
                if st_name not in station_to_users:
                    station_to_users[st_name] = []
                # 本名の1文字目を取得
                station_to_users[st_name].append({"team": team, "char": real_name[0]})

        # 2. 描画
        for st_name, users in station_to_users.items():
            x = int(STATION_COORDINATES[st_name][0] * scale_x)
            y = int(STATION_COORDINATES[st_name][1] * scale_y)
            pin_color = TEAM_COLORS["重複"] if len(users) > 1 else TEAM_COLORS.get(users[0]["team"], (255, 255, 255))

            draw.ellipse((x - (scaled_radius + outline_extra), y - (scaled_radius + outline_extra), 
                          x + (scaled_radius + outline_extra), y + (scaled_radius + outline_extra)), fill=(0, 0, 0))
            draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius), fill=pin_color)
            
            # --- テキストの生成（チームごとに1文字目を連結） ---
            team_summary = {"赤": [], "青": [], "白": []}
            for u in users:
                team_summary[u['team']].append(u['char'])

            display_lines = []
            for t in ["赤", "青", "白"]:
                if team_summary[t]:
                    line_txt = f"{t}:{ ''.join(team_summary[t]) }"
                    display_lines.append((t, line_txt))

            # --- 縁取り描画（中身はチーム色） ---
            current_y = y - scaled_radius
            for t_name, txt in display_lines:
                text_color = TEAM_COLORS.get(t_name, (255, 255, 255))
                text_pos = (x + scaled_radius + 5, current_y)
                
                # 縁取り（黒）
                for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1),(0,-1),(0,1),(-1,0),(1,0)]:
                    draw.text((text_pos[0]+dx, text_pos[1]+dy), txt, fill=(0,0,0), font=font)
                # 中身（チーム色）
                draw.text(text_pos, txt, fill=text_color, font=font)
                current_y += 18 

        # 3. 出力
        out_buf = io.BytesIO()
        img.save(out_buf, format='PNG')
        out_buf.seek(0)
        final_upload = cloudinary.uploader.upload(out_buf, resource_type="image", folder="tetsuoni_maps")
        image_url = final_upload.get("secure_url")

        report_text = f"🚨 参加者 {len(report_buckets['赤']) + len(report_buckets['青']) + len(report_buckets['白'])} 人のデータ 🚨\n"
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