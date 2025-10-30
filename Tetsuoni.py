import os
import sys
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 環境変数から設定を読み込み ---
# ★ チャンネルアクセストークンとシークレットのみ使用します
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    print("エラー: 環境変数 (LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET) を設定してください。")
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- Webhook処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名が不正な場合は400エラーを返す
        app.logger.error("InvalidSignatureError: 署名が不正です。チャンネルシークレットを確認してください。")
        abort(400)
    return 'OK'

# --- メッセージ受信時の処理 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 受信したメッセージの内容を取得
    received_text = event.message.text
    
    # オウム返しのメッセージを作成し、返信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"オウム返し: {received_text}")
    )
    # ※ グループ/個人チャットに関わらず、このreply_messageは機能します。


# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)