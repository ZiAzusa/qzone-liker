import os
import re
import yaml
import signal
import qrcode
import logging
import asyncio
from PIL import Image
from pyzbar.pyzbar import decode
from playwright.async_api import async_playwright

CONFIG_PATH = "config.yaml"
SESSION_PATH = "session.json"
QRCODE_PATH = "qrcode.png"

DEFAULT_CONFIG = """\
# 自己的QQ号，后续需要使用该QQ号扫码登录
QID: 10086
# 黑名单QQ号列表（在这个列表内的QQ发布的说说将不会被点赞）
BLACKLIST: [10000, 10010]
# 刷新间隔（单位：秒）
REFRESH_INTERVAL: 60
# 日志等级
LEVEL: INFO
"""

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if not os.path.exists(CONFIG_PATH):
    logger.error("配置文件不存在！")
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG)
    logger.info(f"已生成示例配置文件: {CONFIG_PATH}，请修改后重新运行")
    exit()

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
QID = config['QID']
BLACKLIST = config['BLACKLIST']
REFRESH_INTERVAL = config['REFRESH_INTERVAL']
LEVEL = getattr(logging, config['LEVEL'].upper(), None)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
logger.info(f"配置已加载: {config}")

TARGET_URL = f"https://user.qzone.qq.com/{QID}/infocenter"
LIKER = """\
(async () => {
  const blacklist = %s;
  document.querySelector("#tab_menu_friend > div.qz-main").click();
  await new Promise(r => setTimeout(r, 1500));
  const selector = "a.item.qz_like_btn_v3:not(.item-on) > i";
  let emptyCount = 0;
  let likedCount = 0;
  while (true) {
    const buttons = Array.from(document.querySelectorAll(selector));
    if (buttons.length === 0) {
      emptyCount++;
    } else {
      emptyCount = 0;
      for (const btn of buttons) {
        const userid = parseInt(btn.parentElement?.parentElement?.parentElement?.parentElement?.previousElementSibling?.previousElementSibling.querySelector(".f-nick > a").href.split('/').pop(), 10);
        if (blacklist.includes(userid)) continue;
        btn.click();
        likedCount++;
        await new Promise(r => setTimeout(r, 500));
      }
    }
    if (emptyCount >= 3) break;
    window.scrollBy({ top: 1000, behavior: 'smooth' });
    await new Promise(r => setTimeout(r, 1500));
  }
  return likedCount;
})();
""" % str(BLACKLIST)

stop_flag = False

def signal_handler(signum, frame):
    global stop_flag
    logger.warning(f"检测到 Ctrl+C，准备退出...")
    stop_flag = True
    exit()

async def load_qr(path):
    image = Image.open(path)
    result = decode(image)
    if not result:
        logger.error("二维码解析失败")
        exit()
    data = result[0].data.decode('utf-8')
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

async def launch_browser(playwright, session=None, handle_response=None):
    browser = await playwright.chromium.launch(
        headless=False,
        args=[
            "--headless=new",
            "--no-proxy-server",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--enable-gpu",
            "--use-gl=desktop",
        ]
    )
    context = await browser.new_context(storage_state=session)
    page = await context.new_page()
    if handle_response:
        page.on("response", handle_response)
    await page.goto(TARGET_URL)
    return browser, context, page

async def login():
    async with async_playwright() as p:
        logger.info("加载登录二维码...")
        if os.path.exists(QRCODE_PATH):
            os.remove(QRCODE_PATH)

        async def handle_response(response):
            url = response.url.lower()
            if "https://xui.ptlogin2.qq.com/ssl/ptqrshow" in url:
                data = await response.body()
                with open(QRCODE_PATH, "wb") as f:
                    f.write(data)

        browser, context, page = await launch_browser(p, handle_response=handle_response)
        await asyncio.sleep(5)
        if not os.path.exists(QRCODE_PATH):
            logger.error("未能获取二维码，请检查网络连接或页面加载情况")
            await browser.close()
            exit()
        await load_qr(QRCODE_PATH)
        logger.info("请扫码登录...")
        await page.wait_for_url(re.compile(r".*/infocenter([?#].*)?$"), timeout=0)
        logger.info("登录成功，保存状态")
        await context.storage_state(path=SESSION_PATH)
        await context.close()
        await browser.close()

async def main():
    global stop_flag
    async with async_playwright() as p:
        session = SESSION_PATH if os.path.exists(SESSION_PATH) else None
        browser, context, page = await launch_browser(p, session)
        logger.info("加载已有登录状态..." if session else "无登录状态，需登录")
        if not re.match(r".*/infocenter([?#].*)?$", page.url):
            logger.warning("检测到未登录，准备使用二维码登录...")
            await browser.close()
            await login()
            browser, context, page = await launch_browser(p, SESSION_PATH)

        browser_disconnected = asyncio.Event()
        browser.on("disconnected", lambda: browser_disconnected.set())
        logger.info("开始循环刷新并点赞...（按 Ctrl+C 退出）")

        try:
            while not stop_flag:
                if browser_disconnected.is_set():
                    logger.warning("浏览器被关闭，退出程序...")
                    exit()
                    break

                await page.reload()
                logger.info("页面已刷新，保存登录状态")
                await page.evaluate("window.scrollTo(0, 0);")
                await context.storage_state(path=SESSION_PATH)
                if not re.match(r".*/infocenter([?#].*)?$", page.url):
                    logger.critical("检测到页面跳转，可能已退出登录，程序退出")
                    break

                logger.info("执行点赞操作...")
                await asyncio.sleep(5)
                liked_count = await page.evaluate(LIKER)
                logger.info(f"本轮点赞数量：{liked_count}")
                await asyncio.sleep(REFRESH_INTERVAL)
        except KeyboardInterrupt:
            logger.warning("检测到 Ctrl+C，准备退出...")

        await browser.close()
        exit()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())
