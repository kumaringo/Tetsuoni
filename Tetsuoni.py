# -*- coding: utf-8 -*-
import os
import io
import json
import base64
import requests

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageSendMessage, TextSendMessage

from PIL import Image, ImageDraw

# 外部ファイルから駅データをインポート (station_data.py)
from station_data import STATION_COORDINATES

# --- 環境変数設定 (ImgBB用) ---
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
IMGBB_API_KEY = os.getenv('IMGUR_CLIENT_ID') # ImgBBのAPIキーとして使用

app = Flask(__name__)

# LINE Bot API の初期化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 共通処理: 画像のアップロード (ImgBB版) ---
def upload_image_to_imgbb(image_io):
    """
    PIL Image IOをImgBBにアップロードし、公開URLを返す
    :param image_io: BytesIOオブジェクト (JPEG形式)
    :return: 公開画像URL (str) または None
    """
    if not IMGBB_API_KEY:
        print("Error: IMGBB_API_KEY is not set.")
        return None

    # BytesIOからBase64文字列にエンコード
    image_io.seek(0)
    base64_image = base64.b64encode(image_io.read()).decode('utf-8')

    url = "https://api.imgbb.com/1/upload"
    
    data = {
        'key': IMGBB_API_KEY,
        'image': base64_image,
        'name': 'tetsuoni_rosenzu.jpeg' # ファイル名をJPEGに変更
    }

    try:
        # APIリクエストを指数関数的バックオフで実行 (省略)
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if result.get('success'):
            image_url = result['data']['url']
            # ImgBBは常に小さなサムネイルURLも返すが、ここではフルサイズのURLを使用
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
        image = Image.open("Rosenzu.png").convert("RGB")
    except FileNotFoundError:
        print("Error: Rosenzu.png not found. Please ensure 'Rosenzu.png' is in the same directory.")
        return None

    draw = ImageDraw.Draw(image)

    if station_name not in STATION_COORDINATES:
        print(f"Error: Coordinates for {station_name} not found.")
        return None
        
    x, y = STATION_COORDINATES[station_name]

    pin_radius = 20
    # ターゲット駅は黄色 (ここではデモ用として未使用)
    if target_station:
        color = "yellow" 
        radius = pin_radius * 1.5
    # 現在のプレイヤー位置は赤
    else:
        color = "red"
        radius = pin_radius 
    
    # 円の描画 (ピン)
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=color,
        outline="black" if target_station else "white",
        width=4
    )
    
    # 結果をBytesIOにJPEG形式で保存
    img_io = io.BytesIO()
    image.save(img_io, format='JPEG') # 互換性の高いJPEGを使用
    img_io.seek(0)
    return img_io

# --- LINE Webhook処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

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
    
    # ユーザーが入力した駅名がSTATION_COORDINATESにあるかチェック
    if msg in STATION_COORDINATES:
        station_name = msg
        
        # 1. 駅にピンを描画した画像を生成
        # target_station=False (現在地を示す赤ピン) として描画
        image_io = draw_station_pin(station_name, False)
        
        if image_io:
            # 2. ImgBBに画像をアップロードし、URLを取得
            image_url = upload_image_to_imgbb(image_io)

            if image_url:
                # 3. LINEに画像として返信
                line_bot_api.reply_message(
                    event.reply_token,
                    ImageSendMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                    )
                )
            else:
                # アップロード失敗時のメッセージ
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="画像アップロードに失敗しました。APIキーを確認してください。")
                )
        else:
            # 画像生成失敗時のメッセージ
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"画像生成に失敗しました。路線図ファイル 'Rosenzu.png' が見つからない可能性があります。")
            )

    # デバッグ用: 画像テストコマンド (削除またはコメントアウト推奨)
    elif msg == '画像テスト':
        # このブロックはデバッグ用であり、通常はゲームロジックの一部ではありません。
        current_station = "渋谷" 
        target_station = "大手町" 

        # デモ画像を生成 (赤ピンと黄ピンの両方を描画)
        image_io = draw_station_pin(current_station, False)
        
        if image_io:
            # BytesIOをPIL Imageに変換し、ターゲット駅を描画
            image_io.seek(0)
            img = Image.open(image_io).convert("RGB")
            draw = ImageDraw.Draw(img)
            
            x_target, y_target = STATION_COORDINATES[target_station]
            radius = 20 * 1.5
            color = "yellow"
            
            draw.ellipse(
                (x_target - radius, y_target - radius, x_target + radius, y_target + radius),
                fill=color,
                outline="black",
                width=4
            )

            final_img_io = io.BytesIO()
            img.save(final_img_io, format='JPEG')
            
            image_url = upload_image_to_imgbb(final_img_io)

            if image_url:
                line_bot_api.reply_message(
                    event.reply_token,
                    ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
                )
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="画像テストアップロード失敗。"))
        
    # その他のメッセージ
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="現在、ゲームを開始していません。駅名を入力するか、次のステップでゲーム開始コマンドを設定します。")
        )

# --- Flaskの起動 ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)