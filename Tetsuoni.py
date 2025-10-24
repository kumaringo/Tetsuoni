import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数からチャネルシークレットとアクセストークンを取得
# ※ Renderなどのサーバーでは、これらの情報を直接コードに書かず、「環境変数」として設定するのが安全です
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')       # 変数名を設定
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN') # 変数名を設定

# ... 以下略
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# WebhookからのPOSTリクエストを処理する部分
@app.route("/callback", methods=['POST'])
def callback():
    # リクエストヘッダーから署名検証のための値を取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディを取得
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 署名を検証し、問題なければhandleに定義されている関数を呼び出す
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# テキストメッセージを受け取った時の処理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 受け取ったテキストをそのまま返信する（オウム返し）
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=event.message.text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)