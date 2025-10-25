import os
import random
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage
)

# 独自に定義した駅データをインポート
from station_data import STATION_DATA, VALID_STATIONS

app = Flask(__name__)

# 環境変数から設定値を取得
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

# 環境変数が設定されていない場合はエラーを出す
if not channel_secret or not channel_access_token:
    app.logger.error("LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN is not set.")
    exit()

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# --- グローバルな状態管理変数 ---
# 参加者データを格納するリスト。4人分集まったら処理を実行
# 例: [{"name": "ユーザーA", "station": "新宿", "team": "赤"}, ...]
player_data = []

# --- Webhookのルーティング ---
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

# --- メッセージ処理ロジック ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    global player_data

    user_id = event.source.user_id
    text = event.message.text.strip()
    
    # ユーザー名を取得
    try:
        # グループラインでBotが友達追加されていない場合、get_profileは失敗する可能性がある
        profile = line_bot_api.get_profile(user_id)
        display_name = profile.display_name
    except Exception as e:
        app.logger.error(f"ユーザー名の取得に失敗: {e}")
        # グループやトークルームではユーザーID末尾で代用
        display_name = f"不明なユーザー({user_id[-4:]})"

    app.logger.info(f"名前: {display_name}, メッセージ: {text}")

    # ① 東京メトロの駅名かチェック
    if text not in VALID_STATIONS:
        # 有効な駅名リストを返信して再入力を促す
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
        # 同じユーザーが複数回参加できないように名前でチェック
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
        # 直前のチームと逆のチームを割り当てる
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
        # ③ 4人分のデータが集まったらコメントを返信
        
        # 最終結果のサマリーテキストを作成
        final_summary = "🎉🎉 【対決終了！】 🎉🎉\n"
        final_summary += "4人分のデータが集まりました。以下が今回の結果です。\n\n"
        
        for p in player_data:
            final_summary += f"・{p['name']} ({p['team']}チーム): {p['station']}\n"
        
        final_summary += "\n\n**[次のステップ]**\n"
        final_summary += "このデータを使って、次は路線図にピンを刺す画像処理に進みます！"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=final_summary)
        )

        # データのクリア
        player_data = []
        app.logger.info("4人分のデータ処理が完了し、データをリセットしました。")
        

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)