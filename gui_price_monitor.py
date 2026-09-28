import streamlit as st
import pandas as pd
import asyncio
import datetime
import csv
import os
import re
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================
# ポートフォリオ1：ECサイト価格監視＆元データ可視化ダッシュボード
# ==========================================

DATA_FILE = "book_prices.csv"
BASE_URL = "https://books.toscrape.com/"

TARGET_ITEMS = [
    {
        "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "custom_name": "ビジネス用 高性能ノートPC (Core i7)"
    },
    {
        "url": "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
        "custom_name": "ワイヤレス ノイズキャンセリングヘッドホン"
    },
    {
        "url": "https://books.toscrape.com/catalogue/non-existent-book_9999/index.html",
        "custom_name": "【エラー検知用】販売終了テスト商品"  # 404エラーテスト
    },
    {
        "url": "https://books.toscrape.com/catalogue/soumission_998/index.html",
        "custom_name": "Python業務自動化・スクレイピング実践バイブル"
    }
]

def load_previous_prices():
    previous_prices = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    previous_prices[row['url']] = int(row['price_jpy'])
        except Exception:
            pass
    return previous_prices

def save_current_prices(records):
    with open(DATA_FILE, mode='w', encoding='utf-8', newline='') as f:
        fieldnames = ['url', 'custom_name', 'raw_title', 'price_raw', 'price_jpy', 'stock', 'image_url', 'last_checked']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r)

async def check_prices_async():
    previous_prices = load_previous_prices()
    current_records = []
    alerts = []
    errors = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for item in TARGET_ITEMS:
            url = item["url"]
            custom_name = item["custom_name"]

            try:
                response = await page.goto(url, timeout=10000)
                await asyncio.sleep(1)

                if response and not response.ok:
                    raise Exception(f"HTTPステータスエラー: {response.status} {response.status_text}")

                title_elem = await page.wait_for_selector("div.product_main h1", timeout=5000)
                raw_title = await title_elem.inner_text()

                price_elem = await page.wait_for_selector("p.price_color", timeout=5000)
                raw_price_text = await price_elem.inner_text()
                price_match = re.search(r'[\d\.]+', raw_price_text)
                if not price_match:
                    raise ValueError("価格のパースに失敗しました")
                price_val = float(price_match.group())
                price_jpy = int(price_val * 190)

                stock_elem = await page.query_selector("p.instock.availability")
                stock_text = (await stock_elem.inner_text()).strip() if stock_elem else "不明"
                stock_clean = re.sub(r'\s+', ' ', stock_text)

                img_elem = await page.query_selector("div.item.active img, #product_gallery img")
                img_src = await img_elem.get_attribute("src") if img_elem else ""
                full_img_url = urljoin(url, img_src) if img_src else ""

                record = {
                    'url': url,
                    'custom_name': custom_name,
                    'raw_title': raw_title,
                    'price_raw': raw_price_text,
                    'price_jpy': price_jpy,
                    'stock': stock_clean,
                    'image_url': full_img_url,
                    'last_checked': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                current_records.append(record)

                if url in previous_prices:
                    prev_jpy = previous_prices[url]
                    if price_jpy < prev_jpy:
                        alerts.append({
                            'custom_name': custom_name,
                            'raw_title': raw_title,
                            'current': price_jpy,
                            'prev': prev_jpy,
                            'diff': prev_jpy - price_jpy,
                            'image_url': full_img_url,
                            'url': url
                        })

            except Exception as e:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', url.split('/')[-2] if '/' in url else 'unknown')
                screenshot_file = f"error_{safe_name}_{timestamp}.png"
                try:
                    await page.screenshot(path=screenshot_file, full_page=True)
                except:
                    screenshot_file = None

                errors.append({
                    'custom_name': custom_name,
                    'url': url,
                    'error': str(e),
                    'screenshot': screenshot_file
                })
                continue

        await browser.close()

    save_current_prices(current_records)
    return current_records, alerts, errors

# ==========================================
# 画面レイアウト
# ==========================================
st.set_page_config(page_title="ECサイト価格監視ダッシュボード", layout="wide")

st.title("🛒 ECサイト 価格監視＆自動データ加工ダッシュボード")
st.markdown("""
**Webサイト上の生データ（画像・英語タイトル・現地通貨）をリアルタイムに巡回抽出し、自社管理用のデータ（日本語・日本円換算）に自動変換・監視するデモシステムです。**  
404エラーや要素変更などのWeb障害が発生した場合も、処理を中断せず**証拠画面（スクリーンショット）を自動保存**してフェイルセーフを維持します。
""")

# クライアント向けの安全性・コンプライアンス説明ブロック
st.info("""
🛡️ **【安全性・コンプライアンスについて】**  
本デモで巡回・スクレイピングしている対象サイト（`books.toscrape.com`）は、**スクレイピングの動作検証・教育専用に一般公開されている安全なサンドボックスサイト**です。商用サイトへの無断アクセスや規約違反等のリスクは一切ございません。安心してリンク先をご確認ください。  
※本番案件におきましては、貴社が指定される対象サイトの規約・サーバー負荷方針・API提供状況を遵守した最適な設計で開発・納品いたします。
""")

if st.button("🚀 最新の価格をチェックする", type="primary"):
    with st.spinner("対象サイトを自動巡回し、画像・価格・在庫データをスクレイピング中..."):
        records, alerts, errors = asyncio.run(check_prices_async())

    st.success("巡回とデータ取得が完了しました！")

    if alerts:
        st.subheader("🔥 値下がり検知アラート")
        cols = st.columns(len(alerts))
        for i, alert in enumerate(alerts):
            with cols[i]:
                if alert['image_url']:
                    st.image(alert['image_url'], width=120)
                st.metric(
                    label=alert['custom_name'],
                    value=f"¥{alert['current']:,}",
                    delta=f"-¥{alert['diff']:,} 値下げ!",
                    delta_color="inverse"
                )
                st.caption(f"元データ: {alert['raw_title']}")
                st.link_button("🌐 安全なテスト元サイトを確認", alert['url'])

    st.subheader("📊 スクレイピング元データ ＆ 自社管理データ 一覧")
    if records:
        df = pd.DataFrame(records)
        display_df = df[[
            'image_url', 'custom_name', 'price_jpy', 
            'raw_title', 'price_raw', 'stock', 'url', 'last_checked'
        ]].copy()

        display_df['price_jpy'] = display_df['price_jpy'].apply(lambda x: f"¥{x:,}")

        display_df.columns = [
            '商品画像', '管理用商品名', '現在価格(円)', 
            '元サイト商品名(英語)', '元サイト価格', '在庫状況', '元サイトURL', '最終確認日時'
        ]

        st.dataframe(
            display_df,
            column_config={
                "商品画像": st.column_config.ImageColumn("商品画像", help="元サイトから取得したサムネイル"),
                "元サイトURL": st.column_config.LinkColumn("元サイトURL", display_text="テストサイトを開く")
            },
            use_container_width=True,
            hide_index=True
        )

    if errors:
        st.subheader("🛡️ QA障害検知・証拠保全レポート")
        st.warning("巡回中に異常（存在しないURL等）を検知しましたが、システム全体はクラッシュせず正常に完走しました。")
        
        for err in errors:
            with st.expander(f"⚠️ 検知ログ: {err['custom_name']} (クリックで証拠スクショを表示)"):
                st.write(f"**対象URL:** {err['url']}")
                st.write(f"**エラー詳細:** {err['error']}")
                if err['screenshot'] and os.path.exists(err['screenshot']):
                    st.image(err['screenshot'], caption=f"自動撮影された障害画面 ({err['screenshot']})", use_container_width=True)