import os
from flask import Flask, request, abort, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage

# Pillowライブラリから画像処理に必要なモジュールをインポート
from PIL import Image, ImageDraw

app = Flask(__name__)

# --- 1. 環境変数の取得 ---
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
my_base_url = os.environ.get('MY_RENDER_URL') 

output_dir = "/tmp/generated_images"
os.makedirs(output_dir, exist_ok=True) 

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# --- 2. データ定義 ---

# ① 駅名と画像上の座標の辞書
STATION_COORDINATES = {
    "新宿": (350, 420),
    "渋谷": (380, 500),
    "池袋": (250, 300),
    "東京": (550, 450),
    "品川": (450, 600)
    # 必要なすべての駅の情報をここに追加
}

# ③ 鬼として扱うユーザー名のリスト (LINEの表示名)
ONI_LIST = [
    "山田太郎", 
    "田中花子"
]

BASE_MAP_PATH = "base_map.png"

# ★★★ 新しい要件（4人待機）のためのグローバル変数 ★★★
# グループIDをキーとして、各ユーザーの報告を保存します
# group_states = {
#   "C12345... (グループID)": {
#     "ユーザーA": {"station": "新宿", "color": "red"},
#     "ユーザーB": {"station": "渋谷", "color": "blue"}
#   }
# }
group_states = {}

# --- 3. LINEからのWebhook処理 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. 画像をLINEに送信するための専用ルート ---
@app.route("/generated_image/<filename>", methods=['GET'])
def serve_generated_image(filename):
    return send_from_directory(output_dir, filename)

# --- 5. メッセージ処理 (ロジック大幅変更) ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    
    # グループ以外からのメッセージは無視
    if event.source.type != 'group':
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="このBotはグループ専用です。")
        )
        return

    group_id = event.source.group_id
    user_id = event.source.user_id
    station_name = event.message.text.strip() # メッセージ(駅名)

    # ② ユーザーの名前を取得
    try:
        profile = line_bot_api.get_group_member_profile(group_id, user_id)
        user_name = profile.display_name
    except Exception as e:
        user_name = "名無しの逃走者" # 取得失敗時のデフォルト

    # ① 駅名が辞書に存在するかチェック
    if station_name not in STATION_COORDINATES:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"「{station_name}」は登録されていません。")
        )
        return # 処理を中断

    # ③ 名前のラベリング
    pin_color = "blue" # デフォルトは青
    if user_name in ONI_LIST:
        pin_color = "red"  # 鬼は赤

    # --- 状態管理ロジック ---

    # このグループ用のデータ保存場所がなければ作成
    if group_id not in group_states:
        group_states[group_id] = {}

    # データを保存 (同じ人が2回送ったら上書きされます)
    group_states[group_id][user_name] = {
        "station": station_name,
        "color": pin_color
    }

    current_count = len(group_states[group_id])

    # 4人に達したかどうかで処理を分岐
    if current_count < 4:
        # 4人未満の場合: 確認メッセージを返信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{user_name}さん ({station_name}) 登録完了。\n現在 {current_count}/4 人です。")
        )
    else:
        # 4人に達した場合: 画像を生成して送信
        try:
            # ④ 画像処理
            base_image = Image.open(BASE_MAP_PATH).convert("RGBA")
            draw = ImageDraw.Draw(base_image)
            
            # 登録された4人分のデータをループ処理
            for user, data in group_states[group_id].items():
                s_name = data["station"]
                color = data["color"]
                x, y = STATION_COORDINATES[s_name]
                
                radius = 15
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius),
                    fill=color,
                    outline="white",
                    width=3
                )
            
            # ⑤ 画像を保存・送信
            output_filename = f"{group_id}.png" # グループIDでファイル名を決定
            output_path = os.path.join(output_dir, output_filename)
            base_image.save(output_path, "PNG")

            image_url = f"{my_base_url}/generated_image/{output_filename}"
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
            
            # グループ全体に画像をプッシュ送信
            line_bot_api.push_message(group_id, image_message)
            
            # 処理が完了したので、このグループの状態をリセット
            del group_states[group_id]

        except Exception as e:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"画像生成エラー: {e}")
            )

# --- 6. サーバー起動 ---

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)