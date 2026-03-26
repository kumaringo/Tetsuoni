import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 外部ファイルから必要なものだけを呼ぶ
from add_station import handle_registration_logic
from pin import send_map_with_pins, USER_CONFIG # USER_CONFIGもpin.pyにあるので借りる

app = Flask(__name__)

# --- 基本設定 ---
try:
    REQUIRED_USERS = int(os.environ.get('REQUIRED_USERS', '15'))
except ValueError:
    REQUIRED_USERS = 15

# LINE & Cloudinary 認証設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

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
    if text.startswith('/'):
        return

    # すでに from add_station import handle_registration_logic しているので
    # ファイル名抜きの関数名だけで呼び出せます
    handle_registration_logic(
        event, line_bot_api, participant_data, users_participated, USER_CONFIG, REQUIRED_USERS)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))