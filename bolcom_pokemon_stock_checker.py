import requests
import time
import traceback

PRODUCT_URLS = [
    "https://www.bol.com/nl/nl/p/-/9300000235555648/?cid=1759061647325-2529148209426&bltgh=da15bd10-1e8e-4a64-978a-5bd91dce5b2d.wishlist_details_page_products.WishlistDetailProductCardItem_5.ProductImage",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-etb-mega-gardevoir/9300000235555646/",
    "https://www.bol.com/nl/nl/p/pokemon-tcg-mega-evolution-6-booster-bundel/9300000235555645/",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-bo-18ct-display/9300000235555637/",
]
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1421979172284403783/yGf1_cVii9IsIN6c6mwcCobPWbSU320BHwEyLxCVn6ueAaMaX5QYj24orpTOV1YeGQ9p'
CHECK_INTERVAL = 60  # seconds

def check_stock(product_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; StockChecker/1.0)'
    }
    response = requests.get(product_url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch product page ({product_url}), status code: {response.status_code}")
        return False
    if "op voorraad" in response.text.lower():
        return True
    else:
        return False

def send_discord_notification(product_url):
    data = {
        "content": f"🎉 Pokémon product in stock! Check it here: {product_url}"
    }
    response = requests.post(DISCORD_WEBHOOK_URL, json=data)
    if response.status_code == 204:
        print(f"Notification sent to Discord for {product_url}.")
    else:
        print(f"Failed to send Discord notification: {response.text}")

def main():
    print("Starting Bol.com Pokémon stock checker for multiple products...")
    notified = set()
    while True:
        try:
            for url in PRODUCT_URLS:
                in_stock = check_stock(url)
                if in_stock and url not in notified:
                    send_discord_notification(url)
                    notified.add(url)
                elif not in_stock:
                    print(f"Not in stock yet: {url}")
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print("Error occurred:", e)
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    main()
