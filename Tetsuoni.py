def send_map_with_pins(chat_id, participants):
    """Cloudinary 側の実際サイズに合わせて画像をリサイズ → ピンを描画 → 再アップロード → LINE送信"""
    try:
        # 1) ローカル元画像（1000x1000想定）を読み込む
        orig_img = Image.open("Rosenzu.png").convert("RGB")
        orig_w, orig_h = orig_img.size  # 例: 1000,1000

        # 2) 元画像を一旦 Cloudinary にアップして、Cloudinary 側の実際サイズを取得する
        buf_base = io.BytesIO()
        orig_img.save(buf_base, format='PNG')
        buf_base.seek(0)

        base_upload = cloudinary.uploader.upload(
            buf_base,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=False,
            overwrite=True
        )
        if not base_upload:
            line_bot_api.push_message(chat_id, TextSendMessage(text="Cloudinary にベース画像をアップできませんでした。"))
            return

        uploaded_w = int(base_upload.get("width", orig_w))
        uploaded_h = int(base_upload.get("height", orig_h))

        # 3) Cloudinary に保存されたサイズに合わせてローカル画像をリサイズ
        if (uploaded_w, uploaded_h) != (orig_w, orig_h):
            img = orig_img.resize((uploaded_w, uploaded_h), Image.LANCZOS)
        else:
            img = orig_img.copy()

        draw = ImageDraw.Draw(img)

        # 4) 元座標(=STATION_COORDINATES の基準) に対するスケールを計算
        scale_x = uploaded_w / orig_w
        scale_y = uploaded_h / orig_h
        # ピン半径も縮尺に合わせる（平均スケールを使用）
        avg_scale = (scale_x + scale_y) / 2.0
        scaled_radius = max(1, int(PIN_RADIUS * avg_scale))

        # 5) 各参加者の駅にピンを描画
        for username, data in participants.items():
            station_name = data["station"]
            pin_color = get_pin_color(username)
            if station_name in STATION_COORDINATES:
                x0, y0 = STATION_COORDINATES[station_name]  # 元 (1000基準など)
                x = int(x0 * scale_x)
                y = int(y0 * scale_y)
                draw.ellipse((x - scaled_radius, y - scaled_radius, x + scaled_radius, y + scaled_radius),
                             fill=pin_color, outline=pin_color)

        # 6) 描画済み画像をメモリに保存して Cloudinary に再アップロード
        out_buf = io.BytesIO()
        img.save(out_buf, format='PNG')
        out_buf.seek(0)

        final_upload = cloudinary.uploader.upload(
            out_buf,
            resource_type="image",
            folder="tetsuoni_maps",
            use_filename=True,
            unique_filename=True
        )

        image_url = final_upload.get("secure_url") if final_upload else None

        # 7) LINE に結果を送信
        if image_url:
            report_text = f"🚨 参加者 **{REQUIRED_USERS} 人**分のデータが集まりました！ 🚨\n\n"
            for username, data in participants.items():
                group_color = "赤" if username in USER_GROUPS["RED_GROUP"] else "青" if username in USER_GROUPS["BLUE_GROUP"] else "不明(赤)"
                report_text += f"- **{data['username']}** ({group_color}G): **{data['station']}**\n"

            # デバッグ情報（Cloudinary に保存された実サイズ）
            debug_text = f"(Cloudinary 保存サイズ: {uploaded_w}x{uploaded_h})"
            line_bot_api.push_message(chat_id, TextSendMessage(text=report_text + "\n" + debug_text))

            line_bot_api.push_message(
                chat_id,
                ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            )
        else:
            line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: 描画済み画像のアップロードに失敗しました。"))

    except FileNotFoundError:
        line_bot_api.push_message(chat_id, TextSendMessage(text="エラー: Rosenzu.png が見つかりません。"))
    except Exception as e:
        line_bot_api.push_message(chat_id, TextSendMessage(text=f"エラー: 画像処理で問題が発生しました: {e}"))
