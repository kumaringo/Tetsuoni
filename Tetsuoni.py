# Tetsuoni.py
import os
import io
import math
import requests
import numpy as np
from PIL import Image, ImageDraw
import cloudinary
import cloudinary.uploader

# LINE imports
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage

# station_data.py から座標データをインポート（元画像基準）
from station_data import STATION_COORDINATES

# ==============================
# Flask app
# ==============================
app = Flask(__name__)

# ==============================
# 設定（必要ならここを編集）
# ==============================
REQUIRED_USERS = 3
PIN_COLOR_RED = (255, 0, 0)
PIN_COLOR_BLUE = (0, 0, 255)
PIN_RADIUS = 10

# 参照点として使う駅（上->中->下 に対応）
REFERENCE_STATIONS = ["上野", "渋谷", "西馬込"]

USER_GROUPS = {
    "RED_GROUP": [
        "茂野大雅",
        "茂野大雅あ"
    ],
    "BLUE_GROUP": [
        "茂野大雅い",
        "茂野大雅う"
    ]
}

# ==============================
# 環境変数読み込み / Cloudinary 設定
# ==============================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# ==============================
# LINE API 初期化
# ==============================
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

# ==============================
# 参加者データ保持
# ==============================
participant_data = {}
users_participated = {}

# ==============================
# ヘルパー
# ==============================
def get_pin_color(username):
    """ユーザー名に基づいてピンの色を決定（RGBタプルを返す）"""
    if username in USER_GROUPS.get("BLUE_GROUP", []):
        return PIN_COLOR_BLUE
    return PIN_COLOR_RED

# ==============================
# Webhook エンドポイント
# ==============================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    return 'OK'

# ==============================
# メッセージ処理
# ==============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip() if event.message and event.message.text else ""
    # グループ or ルーム ID を取得
    if event.source.type == 'group':
        chat_id = event.source.group_id
    elif event.source.type == 'room':
        chat_id = event.source.room_id
    else:
        # 個別トークの場合は user_id を使う（必要なら）
        chat_id = event.source.user_id

    # ユーザー名を取得
    try:
        user_id = event.source.user_id
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(chat_id, user_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(chat_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        username = profile.display_name
    except Exception:
        username = "Unknown User"

    # 初期化
    if chat_id not in participant_data:
        participant_data[chat_id] = {}
        users_participated[chat_id] = set()

    # 駅名がSTATION_COORDINATESにあれば登録
    if text in STATION_COORDINATES:
        if username in users_participated[chat_id]:
            if line_bot_api:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f'{username}さん、駅はすでに報告済みです。')
                )
            return

        participant_data[chat_id][username] = {"username": username, "station": text}
        users_participated[chat_id].add(username)

        current_count = len(users_participated[chat_id])
        if line_bot_api:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'{username}さんが「{text}」を報告しました。\n現在 {current_count} 人 / {REQUIRED_USERS} 人')
            )

        if current_count >= REQUIRED_USERS:
            # 参加者が揃ったら自動検出→アフィン補正→描画→送信
            send_map_with_pins_affine_auto(chat_id, participant_data[chat_id])
            participant_data[chat_id] = {}
            users_participated[chat_id] = set()
    else:
        # 未知の駅名
        if line_bot_api:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'「{text}」 はデータに存在しない駅名です。正しい駅名を報告してください。')
            )

# ==============================
# 赤い参照ピン検出（PIL画像を入力）
# ==============================
def detect_red_centroids_from_pil(img_pil, min_area=8, debug=False):
    """
    PIL.Image -> list of centroids (x, y) of red blobs sorted by y (top->bottom)
    Uses R thresholding: R high and clearly above G/B.
    Falls back to simple connected-component if scipy.ndimage unavailable.
    """
    arr = np.array(img_pil.convert("RGB"))
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)

    # Threshold heuristic (調整可能)
    mask = (r > 150) & (r > g + 50) & (r > b + 50)

    # Try scipy labeling for robustness/performance
    centroids = []
    try:
        from scipy import ndimage as ndi
        lab, n = ndi.label(mask)
        for lbl in range(1, n+1):
            pts = np.argwhere(lab == lbl)
            area = pts.shape[0]
            if area < min_area:
                continue
            ys = pts[:, 0]; xs = pts[:, 1]
            cx = xs.mean(); cy = ys.mean()
            centroids.append((float(cx), float(cy), int(area)))
    except Exception:
        # Simple flood-fill labeling fallback
        h, w = mask.shape
        visited = np.zeros_like(mask, dtype=bool)
        for y in range(h):
            for x in range(w):
                if not mask[y, x] or visited[y, x]:
                    continue
                stack = [(y, x)]
                visited[y, x] = True
                pts = []
                while stack:
                    yy, xx = stack.pop()
                    pts.append((yy, xx))
                    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny, nx = yy+dy, xx+dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                area = len(pts)
                if area < min_area:
                    continue
                ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
                cx = sum(xs)/len(xs); cy = sum(ys)/len(ys)
                centroids.append((float(cx), float(cy), int(area)))

    # Sort top->bottom by y
    centroids_sorted = sorted(centroids, key=lambda c: c[1])
    if debug:
        print("[DEBUG] detected centroids:", centroids_sorted)
    return [(c[0], c[1]) for c in centroids_sorted]

# ==============================
# アフィン推定 / 適用
# ==============================
def estimate_affine(src_pts, dst_pts):
    """
    src_pts, dst_pts: list of (x,y) len>=3
    returns 2x3 affine matrix A so that [u,v] = A @ [x,y,1]
    Works with 3 or more points (least squares).
    """
    assert len(src_pts) == len(dst_pts) and len(src_pts) >= 3
    M = []
    b = []
    for (x, y), (u, v) in zip(src_pts, dst_pts):
        M.append([x, y, 1, 0, 0, 0])
        M.append([0, 0, 0, x, y, 1])
        b.append(u)
        b.append(v)
    M = np.array(M)
    b = np.array(b)
    params, *_ = np.linalg.lstsq(M, b, rcond=None)
    A = params.reshape(2, 3)
    return A

def apply_affine(A, pt):
    x, y = pt
    vec = np.array([x, y, 1.0])
    res = A.dot(vec)
    return float(res[0]), float(res[1])

# ==============================
# Cloudinary / HTTP ヘルパー
# ==============================
def upload_bytes_to_cloudinary(buf_bytes, folder="tetsuoni_maps", use_filename=True, unique=True):
    try:
        res = cloudinary.uploader.upload(
            io.BytesIO(buf_bytes),
            resource_type="image",
            folder=folder,
            use_filename=use_filename,
            unique_filename=unique
        )
        return res
    except Exception as e:
        print("Cloudinary upload error:", e)
        return None

def download_image_from_url(url):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")

# ==============================
# メイン: 自動検出→アフィン補正→描画→送信
# ==============================
def send_map_with_pins_affine_auto(chat_id, participants, debug=False):
    """
    participants: dict username -> {"username":..., "station": station_name}
    フロー:
      1) Rosenzu.png を Cloudinary にアップして保存版の URL を取得
      2) その URL の画像をダウンロードして赤い参照ピンを検出（3点）
      3) 3点を REFERENCE_STATIONS に対応させアフィン推定
      4) ダウンロードした画像上に participants の駅だけピンを描画
      5) 描画済み画像を Cloudinary 再アップロードして LINE に送信
    """
    try:
        base_path = "Rosenzu.png"
        if not os.path.exists(base_path):
            if line_bot_api:
                line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
            return

        # 1) ベース画像をアップロード（保存版）して cloud URL を取得
        with open(base_path, "rb") as f:
            base_bytes = f.read()
        base_upload = upload_bytes_to_cloudinary(base_bytes, folder="tetsuoni_maps", use_filename=True, unique=False)
        if not base_upload:
            if line_bot_api:
                line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Cloudinary へのベース画像アップに失敗しました。"))
            return
        cloud_url = base_upload.get("secure_url")
        if debug:
            print("[DEBUG] cloud_url:", cloud_url)

        # 2) Cloudinary に保存された画像をダウンロード
        cloud_img = download_image_from_url(cloud_url)
        if debug:
            print("[DEBUG] downloaded cloud image size:", cloud_img.size)

        # 3) 赤い参照ピンを自動検出
        centroids = detect_red_centroids_from_pil(cloud_img, min_area=8, debug=debug)
        observed_points = {}
        if len(centroids) < 3:
            # フォールバック: 手動で指定した観測点（最初の値）
            observed_points = {
                "上野": (754.0, 362.0),
                "渋谷": (309.0, 637.0),
                "西馬込": (101.0, 850.0),
            }
            if debug:
                print("[DEBUG] fallback observed_points used:", observed_points)
        else:
            # centroids は top->bottom にソート済み
            # centroids が3つより多い場合は中央値に近い3つを選ぶなど簡易選択
            if len(centroids) > 3:
                ys = [c[1] for c in centroids]
                med = np.median(ys)
                ranked = sorted(centroids, key=lambda c: abs(c[1]-med))
                picked = ranked[:3]
                picked_sorted = sorted(picked, key=lambda c: c[1])  # top->bottom
            else:
                picked_sorted = centroids[:3]
            observed_points = {
                "上野": (float(picked_sorted[0][0]), float(picked_sorted[0][1])),
                "渋谷": (float(picked_sorted[1][0]), float(picked_sorted[1][1])),
                "西馬込": (float(picked_sorted[2][0]), float(picked_sorted[2][1])),
            }
            if debug:
                print("[DEBUG] auto observed_points:", observed_points)

        # 4) アフィン推定 (src: STATION_COORDINATES, dst: observed_points)
        src_pts = []
        dst_pts = []
        for s in REFERENCE_STATIONS:
            if s not in STATION_COORDINATES:
                raise KeyError(f"参照駅 {s} が STATION_COORDINATES に見つかりません")
            src_pts.append(STATION_COORDINATES[s])
            dst_pts.append(observed_points[s])
        A = estimate_affine(src_pts, dst_pts)
        if debug:
            print("[DEBUG] affine A:", A)

        # 5) participants の駅だけ描画（cloud_img 上に）
        out_img = cloud_img.copy()
        draw = ImageDraw.Draw(out_img)
        for username, data in participants.items():
            st = data.get("station")
            if not st or st not in STATION_COORDINATES:
                continue
            x_src = STATION_COORDINATES[st]
            x_draw, y_draw = apply_affine(A, x_src)
            xi, yi = int(round(x_draw)), int(round(y_draw))
            color = get_pin_color(username)
            r = PIN_RADIUS
            draw.ellipse((xi-r, yi-r, xi+r, yi+r), fill=color, outline=color)

        # 6) 再アップロードして LINE に送信
        buf = io.BytesIO()
        out_img.save(buf, format="PNG")
        buf.seek(0)
        final_res = upload_bytes_to_cloudinary(buf.getvalue(), folder="tetsuoni_maps", use_filename=True, unique=True)
        if final_res and line_bot_api:
            image_url = final_res.get("secure_url")
            # メッセージ送信
            summary = f"参加者 {len(participants)} 人分のピンを描画しました。"
            line_bot_api.push_message(chat_id, TextSendMessage(text=summary))
            line_bot_api.push_message(chat_id, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        else:
            if line_bot_api:
                line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 描画済み画像のアップロード/送信に失敗しました。"))
    except Exception as e:
        msg = f"画像処理エラー: {e}"
        print(msg)
        if line_bot_api:
            try:
                line_bot_api.push_message(chat_id, TextSendMessage(text=msg))
            except Exception:
                pass

# ==============================
# 以降は必要に応じて補助関数（既存 upload_to_cloudinary を残す）
# ==============================
def upload_to_cloudinary(img_data):
    """
    画像をCloudinaryにアップロードし、(secure_url, upload_result) を返す
    """
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        print("Cloudinaryの認証情報が設定されていません。")
        return None, {}

    try:
        upload_result = cloudinary.uploader.upload(
            img_data,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True,
        )
        secure_url = upload_result.get('secure_url')
        return secure_url, upload_result
    except Exception as e:
        print(f"Cloudinaryアップロードエラー: {e}")
        return None, {}

# ==============================
# アプリ起動（ローカル用）
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
