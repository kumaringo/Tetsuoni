import os
import sys
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from PIL import Image, ImageDraw, ImageFont
import requests
import io

# station_data.py から座標データをインポート（※ファイル名はstation_data.pyである前提）
try:
    from station_data import STATION_COORDINATES
except ImportError:
    print("エラー: station_data.py が見つかりません。ファイル名を確認してください。")
    sys.exit(1)

app = Flask(__name__)

# --- 環境変数から設定を読み込み (Renderで設定) ---
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET or not IMGBB_API_KEY:
    print("エラー: 環境変数 (LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, IMGBB_API_KEY) を設定してください。")
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- 定数設定 ---
ROSENZU_PATH = "Rosenzu.png"
FONT_PATH = None # フォントファイルのパス (IPAexGothicなど)
PIN_RADIUS = 15
PIN_COLOR = "red"
TEXT_COLOR = "black"

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★ 参加人数 (x人) をここで設定します
REQUIRED_PARTICIPANTS = 5  # <-- この数値を変更してください
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# 実行中のユーザーの駅名をグループごとに保存する辞書
# { 'groupId1': {'userId1': '東京', 'userId2': '新宿'}, 'groupId2': ... }
collected_stations = {}

# --- Webhook処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("InvalidSignatureError: 署名が不正です。チャンネルシークレットを確認してください。")
        abort(400)
    return 'OK'

# --- メッセージ受信時の処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # グループチャットでのみ動作
    if event.source.type != 'group':
        return

    text = event.message.text
    group_id = event.source.group_id
    user_id = event.source.user_id

    # グループIDの初期化
    if group_id not in collected_stations:
        collected_stations[group_id] = {}

    # --- 処理分岐 ---

    # 1. 「リセット」コマンド
    if text == 'リセット':
        collected_stations[group_id] = {}
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="登録済みの駅をリセットしました。")
        )
        return

    # 2. 駅名が送信された場合
    elif text in STATION_COORDINATES:
        
        # --- ユーザー名重複チェック ---
        current_user_name = None
        try:
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
            current_user_name = profile.display_name
        except Exception:
            pass # ユーザー名が取得できない場合はスキップ

        # 既に登録済みのユーザー名リストを取得
        registered_names = []
        for uid in collected_stations[group_id].keys():
            if uid == user_id: # 自分のIDはスキップ
                continue
            try:
                other_profile = line_bot_api.get_group_member_profile(group_id, uid)
                registered_names.append(other_profile.display_name)
            except Exception:
                pass

        # ユーザー名が重複しているかチェック
        if current_user_name and current_user_name in registered_names:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ {current_user_name} 様、他の参加者と同じユーザー名です。名前を変更してください。")
            )
            return # 処理を中断
        # -----------------------------
        
        # 登録/上書き処理に進む
        collected_stations[group_id][user_id] = text
        
        current_count = len(collected_stations[group_id])
        
        # 登録確認メッセージ
        line_bot_api.reply_message( 
            event.reply_token,
            TextSendMessage(text=f"✅ {text} を登録しました。 (現在 {current_count}/{REQUIRED_PARTICIPANTS}人)")
        )

        # 3. 規定人数に達した場合
        if current_count == REQUIRED_PARTICIPANTS:
            stations_to_draw = collected_stations[group_id]
            
            # 登録者リストの作成
            user_list_text = "【登録者一覧】\n"
            for uid, station in stations_to_draw.items():
                try:
                    profile = line_bot_api.get_group_member_profile(group_id, uid)
                    user_name = profile.display_name
                except Exception:
                    user_name = "（不明なユーザー）"
                
                user_list_text += f"・{user_name}：{station}\n"
            
            # 処理中であることを通知 (登録者リストを合わせて送信)
            line_bot_api.post_to_group(
                group_id,
                TextSendMessage(text=f"🎉 {REQUIRED_PARTICIPANTS}人の駅登録が完了しました。画像を作成します！\n\n{user_list_text}")
            )

            # 画像処理とアップロードを実行
            try:
                image_url = process_and_upload_image(stations_to_draw)
                
                # LINEに画像URLを送信
                line_bot_api.post_to_group( 
                    group_id,
                    ImageSendMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                    )
                )
                
                # 集計が完了したら、このグループのデータをリセット
                collected_stations[group_id] = {}

            except Exception as e:
                app.logger.error(f"画像処理または送信エラー: {e}")
                line_bot_api.post_to_group(
                    group_id,
                    TextSendMessage(text=f"⚠️ エラーが発生しました: {e}")
                )
    
    # 4. 存在しない駅名が送信された場合
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"⚠️ 『{text}』は登録された駅リストに存在しません。駅名リストにある駅名を入力してください。")
        )


# --- 画像処理関数 ---
def process_and_upload_image(stations):
    """
    駅名の辞書を受け取り、路線図にピンを刺し、IMGBBにアップロードしてURLを返す
    """
    
    # 1. 路線図の読み込み
    try:
        base_image = Image.open(ROSENZU_PATH).convert("RGBA")
    except FileNotFoundError:
        raise Exception(f"{ROSENZU_PATH} が見つかりません。ファイルを確認してください。")
        
    draw = ImageDraw.Draw(base_image)
    
    # フォントの準備
    try:
        if FONT_PATH:
            font = ImageFont.truetype(FONT_PATH, size=PIN_RADIUS)
        else:
            font = ImageFont.load_default()
    except IOError:
        font = ImageFont.load_default() 

    # 2. ピンと駅名を描画
    for user_id, station_name in stations.items():
        if station_name in STATION_COORDINATES:
            x, y = STATION_COORDINATES[station_name]
            
            # ピン（円）を描画
            draw.ellipse(
                (x - PIN_RADIUS, y - PIN_RADIUS, x + PIN_RADIUS, y + PIN_RADIUS),
                fill=PIN_COLOR,
                outline="black",
                width=2
            )
            
            # 駅名を描画 (ピンのすぐ横)
            draw.text(
                (x + PIN_RADIUS + 5, y - (PIN_RADIUS // 2)), 
                station_name,
                fill=TEXT_COLOR,
                font=font
            )

    # 3. 画像をメモリ（バイトストリーム）に保存
    img_byte_arr = io.BytesIO()
    base_image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0) 

    # 4. IMGBBにアップロード
    response = requests.post(
        "https://api.imgbb.com/1/upload",
        params={'key': IMGBB_API_KEY},
        files={'image': img_byte_arr}
    )
    
    response.raise_for_status() 
    result = response.json()
    
    if result.get("data") and result["data"].get("url"):
        return result["data"]["url"]
    else:
        raise Exception(f"IMGBBへのアップロードに失敗しました: {result}")


# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)