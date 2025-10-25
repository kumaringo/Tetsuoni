import os
import random
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage,
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from station_data import STATION_DATA, VALID_STATIONS

app = Flask(__name__)

channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

if not channel_secret or not channel_access_token:
    app.logger.error("LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN is not set.")
    exit()

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

player_data = []

# --- マップ画像の設定 ---
MAP_FILE_NAME = "Rosenzu.png" 
# --------------------
PIN_RADIUS = 12
TEAM_COLORS = {"赤": "red", "青": "blue"}
FONT_PATH = "arial.ttf" 
# リサイズしないため、TARGET_IMAGE_SIZEは不要になります。
# ただし、フォントのロードのために残します。

try:
    # フォントサイズを小さくします
    font = ImageFont.truetype(FONT_PATH, 16)
except IOError:
    font = ImageFont.load_default()
    app.logger.warning("Custom font not found. Using default font.")


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Check your channel secret.")
        abort(400)

    return 'OK'

# --- 画像生成ロジック ---
def generate_map_image(data):
    """
    指定された路線図にピンをプロットした画像を生成する
    """
    try:
        # 路線図画像を読み込み（リサイズなし）
        base_img = Image.open(MAP_FILE_NAME).convert("RGBA")
    except FileNotFoundError:
        # ファイルがない場合、エラーをログに出力してNoneを返し、処理を中断
        app.logger.error(f"路線図ファイルが見つかりません: {MAP_FILE_NAME}")
        return None

    # --- 描画処理 ---
    # MAP_SIZE_X, MAP_SIZE_Y = base_img.size
    draw = ImageDraw.Draw(base_img)

    # データをプロット
    for p in data:
        station = p['station']
        team_color = TEAM_COLORS.get(p['team'], 'white')
        
        # STATION_DATAから座標を取得
        if station in STATION_DATA:
            # station_data.pyは (X_元座標, Y_元座標, 路線名) の形式
            x, y, line = STATION_DATA[station]
            
            # 座標のスケーリングは不要になりました。station_data.pyの値が直接使われます。
            
            # ピン（円）を描画
            draw.ellipse(
                (x - PIN_RADIUS, y - PIN_RADIUS, x + PIN_RADIUS, y + PIN_RADIUS),
                fill=team_color, 
                outline="black", # 路線図上で目立つようにアウトラインを黒に
                width=3
            )
            
            # 駅名とユーザー名、チーム名を表示 (ピンの右下に配置)
            text_x = x + PIN_RADIUS + 5
            text_y = y - PIN_RADIUS - 10
            
            info_text = f"[{p['team']}] {p['name']}: {station}"
            # 背景が複雑な路線図上で文字が読めるよう、文字の輪郭を描画（簡易的なシャドウ）
            # 黒いアウトラインを付けて視認性を向上
            draw.text((text_x + 1, text_y + 1), info_text, fill="black", font=font)
            draw.text((text_x, text_y), info_text, fill="white", font=font)

    # 画像をメモリ上のバイトストリームに保存
    buffer = io.BytesIO()
    base_img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

# --- メッセージ処理ロジック (変更なし) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    global player_data

    user_id = event.source.user_id
    text = event.message.text.strip()
    
    # ユーザー名を取得
    try:
        profile = line_bot_api.get_profile(user_id)
        display_name = profile.display_name
    except Exception as e:
        app.logger.error(f"ユーザー名の取得に失敗: {e}")
        display_name = f"不明なユーザー({user_id[-4:]})"

    app.logger.info(f"名前: {display_name}, メッセージ: {text}")

    # ① 東京メトロの駅名かチェック (VALID_STATIONSはstation_data.pyからインポート済み)
    if text not in VALID_STATIONS:
        reply_text = (
            f"{display_name}さん、入力された「{text}」は有効な東京メトロの駅名ではありません。\n"
            f"例: {', '.join(VALID_STATIONS[:5])} のいずれかを入力してください。"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        return

    # 既にこのユーザーが参加済みかチェック
    for data in player_data:
        if data['name'] == display_name:
            reply_text = f"{display_name}さんは既に「{data['station']}」で参加済みです。次の対決を待ってください。"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return

    # ② チームのラベリング (赤/青で交互に割り当て)
    if not player_data:
        assigned_team = "赤"
    else:
        last_team = player_data[-1]['team']
        assigned_team = "青" if last_team == "赤" else "赤"
        
    # データを保存
    player_data.append({
        "name": display_name,
        "station": text,
        "team": assigned_team
    })
    
    current_count = len(player_data)
    
    # --- データの集計と返信 ---
    if current_count < 4:
        # 3人以下のとき: 途中経過を返信
        status_lines = [f"{i+1}. {d['name']} ({d['team']}チーム): {d['station']}" 
                        for i, d in enumerate(player_data)]
        status_text = "\n".join(status_lines)
        
        reply_text = (
            f"【参加登録完了】\n"
            f"名前: {display_name}, チーム: {assigned_team}, 駅: {text}\n\n"
            f"--- 現在の状況 ({current_count}/4人) ---\n"
            f"{status_text}\n"
            f"あと{4 - current_count}人、駅名を入力してください！"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

    else:
        # ③ 4人分のデータが集まったら路線図にピンを刺す
        
        # 路線図画像を生成
        image_buffer = generate_map_image(player_data)
        
        # ----------------------------------------------------
        # image_bufferがNoneの場合、ファイルが見つからなかったため、エラーメッセージを返します
        if image_buffer is None:
            final_summary = "⚠️ 【エラー】対決は終了しましたが、路線図ファイルが見つからなかったため画像を生成できませんでした。ファイル名「Rosenzu.png」を確認してください。"
        else:
            # ④ LINEに画像を返信
            
            # Render環境では画像を公開URLとしてアップロードする必要があるため、一旦テキストで代替
            final_summary = "🎉🎉 【対決終了！】 🎉🎉\n"
            final_summary += "4人分のデータが集まりました。画像生成は成功しましたが、LINEの仕様上、外部URLとしてアップロードしないと送信できません。\n\n"
            
            for p in player_data:
                final_summary += f"・{p['name']} ({p['team']}チーム): {p['station']}\n"
            
            final_summary += "\n**[次のステップ]**\n"
            final_summary += "1. **座標設定**: `station_data.py` の座標を、**`Rosenzu.png` の元の画像サイズ** の正確な位置に合わせて修正してください。\n"
            final_summary += "2. **画像送信**: 外部ストレージサービス（S3など）へのアップロード機能の実装が必要です。"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=final_summary)
        )
        # ----------------------------------------------------

        # データのクリア
        player_data = []
        app.logger.info("4人分のデータ処理が完了し、データをリセットしました。")
        

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
