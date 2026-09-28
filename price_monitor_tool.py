import asyncio
import traceback
import datetime
import logging
import csv
import os
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================
# ポートフォリオ：ECサイト価格監視＆変動アラートツール
# ==========================================

# ログの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app_price_monitor.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

DATA_FILE = "book_prices.csv"

# 監視対象のURL（意図的にエラーを起こすダミーURLも含めています）
TARGET_URLS = [
    "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
    "https://books.toscrape.com/catalogue/non-existent-book_9999/index.html", # 404エラーテスト用
    "https://books.toscrape.com/catalogue/soumission_998/index.html"
]

def load_previous_prices():
    """前回保存した価格データを読み込む"""
    previous_prices = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    previous_prices[row['url']] = float(row['price'])
            logging.info("前回の価格データを読み込みました。")
        except Exception as e:
            logging.warning(f"前回データの読み込みに失敗しました（初回起動の可能性があります）: {e}")
    return previous_prices

def save_current_prices(current_prices):
    """最新の価格データをCSVに保存する"""
    try:
        with open(DATA_FILE, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'title', 'price', 'last_checked'])
            writer.writeheader()
            for url, data in current_prices.items():
                writer.writerow({
                    'url': url,
                    'title': data['title'],
                    'price': data['price'],
                    'last_checked': data['last_checked']
                })
        logging.info("最新の価格データを保存しました。")
    except Exception as e:
        logging.error(f"データの保存に失敗しました: {e}")

async def handle_error(page, error, url):
    """エラーハンドリングと証拠保全（スクリーンショット）"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # URLからファイル名に使えそうな部分を抽出
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', url.split('/')[-2] if '/' in url else 'unknown')
    screenshot_path = f"error_{safe_name}_{timestamp}.png"
    
    if page:
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            logging.info(f"【証拠保全】エラー画面のスクリーンショットを保存しました: {screenshot_path}")
        except Exception as ss_error:
            logging.error(f"スクリーンショットの保存に失敗しました: {ss_error}")
    
    logging.error(f"対象URL: {url}")
    # スタックトレースは長くなるので、エラーメッセージのみ出力（必要に応じて traceback を利用）
    logging.error(f"エラー内容: {error}")

async def check_prices(playwright):
    browser = None
    try:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        previous_prices = load_previous_prices()
        current_prices = {}

        for url in TARGET_URLS:
            logging.info(f"価格確認中: {url}")
            try:
                # ページへ遷移
                response = await page.goto(url)
                await asyncio.sleep(2) # サーバー負荷軽減

                # 404エラーなどのステータスコードをチェック
                if response and not response.ok:
                    raise Exception(f"HTTP Error: {response.status} {response.status_text}")

                # 商品タイトルと価格の取得
                # ※書籍サイトの構造が変わった場合はセレクタの修正が必要です
                title_element = await page.wait_for_selector("div.product_main h1", timeout=5000)
                price_element = await page.wait_for_selector("p.price_color", timeout=5000)

                title = await title_element.inner_text()
                price_text = await price_element.inner_text()

                # 価格文字列（例: '£51.77'）から数値だけを抽出
                # 英ポンド記号やユーロ記号などを取り除く
                price_match = re.search(r'[\d\.]+', price_text)
                if not price_match:
                    raise ValueError(f"価格の形式が不正です: {price_text}")
                
                current_price = float(price_match.group())
                
                # 取得結果を保存用辞書に追加
                current_prices[url] = {
                    'title': title,
                    'price': current_price,
                    'last_checked': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                # 差分検知
                if url in previous_prices:
                    prev_price = previous_prices[url]
                    if current_price < prev_price:
                        # ★値下がり検知！★
                        logging.warning(f"\n{'='*40}\n★値下がり検知！★\n商品: {title}\n価格: £{prev_price:.2f} -> £{current_price:.2f}\nURL: {url}\n{'='*40}\n")
                    elif current_price > prev_price:
                        logging.info(f"値上がりしました: £{prev_price:.2f} -> £{current_price:.2f}")
                    else:
                        logging.info(f"価格変動なし: £{current_price:.2f}")
                else:
                    logging.info(f"新規登録商品: {title} (£{current_price:.2f})")

            except PlaywrightTimeoutError as e:
                logging.error(f"タイムアウトエラー: 要素が見つかりませんでした。")
                await handle_error(page, e, url)
                # スキップして次の商品へ
                continue
            except Exception as e:
                logging.error(f"取得エラー発生")
                await handle_error(page, e, url)
                # スキップして次の商品へ
                continue
            
        # 全件処理が終わったら保存
        save_current_prices(current_prices)

    finally:
        if browser:
            await browser.close()
            logging.info("ブラウザを終了しました。")

async def main():
    async with async_playwright() as playwright:
        await check_prices(playwright)

if __name__ == '__main__':
    asyncio.run(main())
