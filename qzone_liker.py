import os
import re
import sys
import cv2
import glob
import yaml
import signal
import qrcode
import logging
import asyncio
from logging.handlers import RotatingFileHandler
from playwright.async_api import async_playwright, Error
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
from controller import BrowserException

CONFIG_PATH = "config.yaml"
SESSION_PATH = "session.json"
QRCODE_PATH = "qrcode.png"
DEFAULT_CONFIG = """\
# 自己的QQ号（后续需要使用该QQ号扫码登录）
QID: 10086
# 黑名单QQ号列表（在这个列表内的QQ发布的说说将不会被点赞）
BLACKLIST: [10000, 10010]
# 刷新获取新说说的间隔（单位：秒）
REFRESH_INTERVAL: 60
# 两次点赞之间间隔（单位：秒）
LIKE_INTERVAL: 3
# 网络操作重试次数
RETRY_TIMES: 3
# 网络操作超时时间（单位：秒）
TIMEOUT: 30
# 日志配置
LEVEL: INFO                 # 日志等级
LOG_PATH: 'logs/run.log'    # 日志文件路径
LOG_SIZE: 10                # 单个日志文件大小限制(MB)
LOG_COUNT: 5                # 保留的日志文件数量

# 是否使用SMTP邮件服务实现断线通知
USE_SMTP: false
# SMTP配置（如果USE_SMTP为true，则需填写以下配置）
SMTP:
    SENDER: ''       # 发件人邮箱地址
    PASSWORD: ''     # 发件人邮箱密码
    RECEIVER: ''     # 收件人邮箱地址
    SERVER: ''       # SMTP服务器地址
    PORT: 587        # SMTP服务器端口
"""
TARGET_URL = "https://user.qzone.qq.com/%d/infocenter"
LIKER = """\
(async () => {
  const blacklist = %s;
  document.querySelector("#tab_menu_friend > div.qz-main").click();
  await new Promise(r => setTimeout(r, 1500));
  const selector = "a.item.qz_like_btn_v3:not(.item-on) > i";
  let emptyCount = 0;
  let likedCount = 0;
  while (emptyCount <= 3) {
    const buttons = Array.from(document.querySelectorAll(selector));
    const fb = buttons.filter(btn => {
      const userid = parseInt(btn.parentElement?.parentElement?.parentElement?.parentElement?.previousElementSibling?.previousElementSibling.querySelector(".f-nick > a").href.split('/').pop(), 10);
      return !blacklist.includes(userid); 
    });
    if (fb.length === 0) { emptyCount++; } else {
      emptyCount = 0;
      for (const btn of fb) {
        btn.click();
        likedCount++;
        await new Promise(r => setTimeout(r, %d));
      }
    }
    window.scrollBy({ top: 1000, behavior: 'smooth' });
    await new Promise(r => setTimeout(r, 1500));
  }
  return likedCount;
})();
"""

def initialize(config_path):
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)
    if not os.path.exists(config_path):
        logger.error("配置文件不存在！")
        with open(config_path, 'w', encoding='utf-8') as f: f.write(DEFAULT_CONFIG)
        logger.info(f"已生成示例配置文件: {config_path}，请修改后重新运行")
        sys.exit()

    with open(config_path, 'r', encoding='utf-8') as f: config = yaml.safe_load(f)
    LEVEL = getattr(logging, config.get('LEVEL', 'INFO').upper(), logging.INFO)
    logger.setLevel(LEVEL)
    if log_path := config.get('LOG_PATH', None):
        log_dir = os.path.dirname(log_path)
        if log_dir and not os.path.exists(log_dir): os.makedirs(log_dir)
        log_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=config.get('LOG_SIZE', 10) * 1024 * 1024,
            backupCount=config.get('LOG_COUNT', 5),
            encoding='utf-8'
        )
        log_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(log_handler)
    
    if config.get('USE_SMTP', False):
        from controller import EmailController
        controller = EmailController(logger, config).controller
    else:
        def controller():
            def decorator(func):
                async def wrapper(*args, **kwargs):
                    try:
                        kwargs.update({'first_run': False})
                        return await func(*args, **kwargs)
                    except Exception as e:
                        logger.error(f"执行函数时出错: {str(e)}")
                        sys.exit()
                return wrapper
            return decorator

    logger.info(f"配置已加载: {config}")
    return logger, config, controller

def with_retry():
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for attempt in range(RETRY_TIMES):
                try:
                    kwargs.update({'wait_until': 'networkidle', 'timeout': TIMEOUT*1000})
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt < RETRY_TIMES - 1:
                        wait_time = min(attempt + 2, 10)
                        logger.warning(f"操作失败：{str(e)}，{wait_time}秒后进行第{attempt + 2}次重试...")
                        await asyncio.sleep(wait_time)
                    else: logger.error(f"操作失败：{str(e)}，已重试{RETRY_TIMES}次，放弃重试")
        return wrapper
    return decorator

def signal_handler(*args): sys.exit(logger.warning(f"检测到 Ctrl+C，准备退出...（如未退出可重试）"))

async def close(browser): sys.exit(await browser.close())

async def load_qr(path):
    img = cv2.imread(path)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    if not data: return 0
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    return 1

async def launch_browser(playwright, session=None, handle_response=None):
    params = {
        'headless': False,
        'args': [
            "--headless=new",
            "--no-proxy-server",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--enable-gpu",
            "--use-gl=desktop",
        ]
    }
    try: browser = await playwright.chromium.launch(**params)
    except Error:
        matcher = "./chrom*/chrome.exe" if sys.platform.startswith('win') else "./chrom*/chrome"
        (chromium_path := glob.glob(matcher)) or logger.error("未找到Chromium，请检查其是否存在") or sys.exit()
        browser = await playwright.chromium.launch(executable_path=chromium_path[0], **params)

    context = await browser.new_context(storage_state=session, permissions=[])
    page = await context.new_page()
    if handle_response: page.on("response", handle_response)
    await (with_retry()(page.goto))(TARGET_URL)
    return browser, context, page

async def login():
    async with async_playwright() as p:
        logger.info("加载登录二维码...")
        if os.path.exists(QRCODE_PATH): os.remove(QRCODE_PATH)
        async def handle_response(response):
            url = response.url.lower()
            if "https://xui.ptlogin2.qq.com/ssl/ptqrshow" in url:
                data = await response.body()
                with open(QRCODE_PATH, "wb") as f: f.write(data)

        browser, context, page = await launch_browser(p, handle_response=handle_response)
        await asyncio.sleep(3)
        os.path.exists(QRCODE_PATH) or logger.error("未能获取二维码，请检查网络连接或页面加载情况") or await close(browser)
        await load_qr(QRCODE_PATH) or logger.error("二维码解析失败") or await close(browser)
        logger.info("请扫码登录...")
        try:
            await page.wait_for_url(url=re.compile('.*/infocenter([?#].*)?$'), timeout=300000)
            logger.info("登录成功，保存状态")
            await context.storage_state(path=SESSION_PATH)
        except PlaywrightTimeoutError: logger.error("登录超时，请重新运行程序") or await close(browser)
        await browser.close()

async def main(first_run=True):
    async with async_playwright() as p:
        session = SESSION_PATH if os.path.exists(SESSION_PATH) else None
        logger.info("加载已有登录状态..." if session else "无登录状态，需登录")
        browser, context, page = await launch_browser(p, session)
        if not re.match(r".*/infocenter([?#].*)?$", page.url):
            if first_run: raise BrowserException(browser)
            logger.warning("检测到未登录，准备使用二维码登录...")
            await browser.close()
            await login()
            browser, context, page = await launch_browser(p, SESSION_PATH)

        browser_disconnected = asyncio.Event()
        browser.on("disconnected", lambda: browser_disconnected.set())
        logger.info("开始循环刷新并点赞...（按 Ctrl+C 退出）")
        while True:
            not browser_disconnected.is_set() or logger.warning("浏览器被关闭，退出程序...") or await close(browser)
            try:
                await (with_retry()(page.reload))()
                logger.info("页面已刷新，保存登录状态")
                await page.evaluate("window.scrollTo(0, 0);")
                await context.storage_state(path=SESSION_PATH)
                if not re.match(r".*/infocenter([?#].*)?$", page.url):
                    logger.critical("页面跳转，登录状态过期")
                    raise BrowserException(browser)
                
            except BrowserException as e: raise e
            except Exception as e:
                logger.error(f"页面刷新失败：{str(e)}")
                continue

            logger.info("执行点赞操作...")
            await asyncio.sleep(3)
            liked_count = await page.evaluate(LIKER)
            logger.info(f"本轮点赞数量：{liked_count}")
            await asyncio.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    logger, config, controller = initialize(CONFIG_PATH)

    QID = config.get('QID', None) or logger.error("配置文件中缺少必须的QQ号！") or sys.exit()
    BLACKLIST = config.get('BLACKLIST', [])
    REFRESH_INTERVAL = config.get('REFRESH_INTERVAL', 60)
    LIKE_INTERVAL = config.get('LIKE_INTERVAL', 3)*1000
    RETRY_TIMES = config.get('RETRY_TIMES', 3)
    TIMEOUT = config.get('TIMEOUT', 30)
    TARGET_URL = TARGET_URL % QID
    LIKER = LIKER % (str(BLACKLIST), LIKE_INTERVAL)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run((controller()(main))())
