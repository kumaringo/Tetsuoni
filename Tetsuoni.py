# -*- coding: utf-8 -*-
import os
import io
import json
import base64
import requests 

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageSendMessage, TextMessage

from PIL import Image, ImageDraw

# 外部ファイルから駅データをインポート (station_data.py)
from station_data import STATION_COORDINATES

# --- 環境変数設定 (ImgBB用) ---
# LINEの認証情報
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
# 画像ホスティングサービス ImgBB の APIキー (Imgurの環境変数名を流用)
IMGBB_API_KEY = os.getenv('IMGUR_CLIENT_ID')

app = Flask(__name__)

# LINE Bot API の初期化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 共通処理: 画像のアップロード (ImgBB版) ---
def upload_image_to_imgbb(image_io):
    """
    PIL Image IOをImgBBにアップロードし、公開URLを返す
    :param image_io: BytesIOオブジェクト (PNG形式)
    :return: 公開画像URL (str) または None
    """
    if not IMGBB_API_KEY:
        print("Error: IMGBB_API_KEY is not set.")
        return None

    # BytesIOからBase64文字列にエンコード
    image_io.seek(0) # ポインタを先頭に戻す
    base64_image = base64.b64encode(image_io.read()).decode('utf-8')

    # ImgBBアップロードエンドポイント
    url = "https://api.imgbb.com/1/upload"
    
    # リクエストパラメータ
    data = {
        'key': IMGBB_API_KEY,
        'image': base64_image,
        'name': 'tetsuoni_rosenzu.png' # ファイル名
    }

    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる
        
        result = response.json()
        
        if result.get('success'):
            image_url = result['data']['url']
            # LINEの仕様により、画像URLとプレビューURLは同じでOK
            return image_url
        else:
            print(f"ImgBB upload failed. Error: {result.get('error', 'Unknown error')}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Error during ImgBB API request: {e}")
        return None
    except json.JSONDecodeError:
        print(f"Error decoding ImgBB response: {response.text}")
        return None


# --- 共通処理: 画像の描画 ---
def draw_station_pin(station_name, target_station):
    """
    路線図画像にピンを描画する
    :param station_name: 描画する駅名
    :param target_station: ターゲット駅かどうか (bool)
    :return: BytesIOオブジェクト
    """
    try:
        # 画像のロード（Botの実行ファイルと同じディレクトリにあることを想定）
        # 'Rosenzu.png' はアップロード済みのファイル名と一致していることを前提とします
        image = Image.open("Rosenzu.png").convert("RGB")
    except FileNotFoundError:
        # 路線図が見つからない場合はエラーメッセージを返す
        print("Error: Rosenzu.png not found. Please ensure 'Rosenzu.png' is in the same directory.")
        return None

    draw = ImageDraw.Draw(image)

    # 座標の取得
    if station_name not in STATION_COORDINATES:
        print(f"Error: Coordinates for {station_name} not found in STATION_COORDINATES.")
        return None
        
    x, y = STATION_COORDINATES[station_name]

    # ピンの色とサイズを設定
    pin_radius = 20
    
    if target_station:
        # ターゲット駅 (黄色で目立つように)
        color = "yellow" 
        radius = pin_radius * 1.5
    else:
        # 現在のプレイヤー位置 (赤色)
        color = "red"
        radius = pin_radius 
    
    # 円の描画 (ピン)
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=color,
        outline="black" if target_station else "white",
        width=4
    )
    
    # 結果をBytesIOに保存 (LINE送信のため)
    img_io = io.BytesIO()
    image.save(img_io, format='PNG')
    img_io.seek(0)
    return img_io

# --- LINE Webhook処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    # 署名ヘッダーを取得
    signature = request.headers.get('X-Line-Signature', '')
    # リクエストボディを取得
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 署名検証
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Check your channel secret/token.")
        abort(400)

    return 'OK'

# --- メッセージ処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    
    # --- デバッグ用: 画像テストコマンド ---
    if msg == '画像テスト':
        # ターゲット駅（例：大手町）と現在地（例：渋谷）を設定
        # 実際にはFirestoreからデータを取得しますが、ここではデモ用
        current_station = "渋谷" 
        target_station = "大手町" 

        # 1. 路線図画像にピンを描画
        # この関数は、現在地とターゲットを両方描画するように機能拡張します。
        
        # 最初にベースの路線図を取得
        try:
            image = Image.open("Rosenzu.png").convert("RGB")
        except FileNotFoundError:
            line_bot_api.reply_message(
                event.reply_token,
                TextMessage(text="エラー: 路線図ファイル(Rosenzu.png)が見つかりません。")
            )
            return

        draw = ImageDraw.Draw(image)

        # 座標の定義
        stations_to_plot = {
            current_station: {"target": False, "color": "red", "radius_scale": 1.0},
            target_station: {"target": True, "color": "yellow", "radius_scale": 1.5}
        }
        
        for station_name, info in stations_to_plot.items():
            if station_name in STATION_COORDINATES:
                x, y = STATION_COORDINATES[station_name]
                pin_radius = 20
                radius = pin_radius * info["radius_scale"]
                color = info["color"]
                
                # ピンの描画
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius),
                    fill=color,
                    outline="black" if info["target"] else "white",
                    width=4
                )
            else:
                print(f"Warning: Station {station_name} coordinates missing.")


        # 2. 最終画像をBytesIOに保存
        final_img_io = io.BytesIO()
        image.save(final_img_io, format='PNG')
        
        # 3. ImgBBにアップロード
        uploaded_url = upload_image_to_imgbb(final_img_io)

        if uploaded_url:
            # 4. LINEに画像メッセージを送信
            line_bot_api.reply_message(
                event.reply_token,
                ImageSendMessage(
                    original_content_url=uploaded_url,
                    preview_image_url=uploaded_url # LINEの仕様上、同じURLでOK
                )
            )
        else:
            # アップロード失敗時の処理
            line_bot_api.reply_message(
                event.reply_token,
                TextMessage(text="画像のアップロードに失敗しました。ImgBBのAPIキーを確認してください。")
            )
    
    # --- 通常の応答 (デバッグ用) ---
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextMessage(text="「画像テスト」と入力すると、現在の路線図が表示されます。")
        )

# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)