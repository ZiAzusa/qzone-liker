class BrowserException(Exception):
    def __init__(self, browser):
        super().__init__("Browser error")
        self.browser = browser

class EmailController:
    def __init__(self, config):
        modules = {
            'os': None,
            'logging': None,
            'asyncio': None,
            'aiosmtplib': None,
            'email.mime.text': ('MIMEText',),
            'email.mime.image': ('MIMEImage',),
            'email.mime.multipart': ('MIMEMultipart',),
            'email.header': ('Header',)
        } 
        for module_path, attrs in modules.items():
            module = __import__(module_path, fromlist=['*'] if not attrs else attrs)
            globals()[module_path.split('.')[-1]] = module
            if attrs: globals().update({attr: getattr(module, attr) for attr in attrs})

        self.config = config
        self.qrcode_path = "qrcode.png"
        self.logger = logging.getLogger(__name__)
        self.level = getattr(logging, config.get('LEVEL', 'INFO').upper(), logging.INFO)
        self.logger.setLevel(self.level)

    async def send_email(self, subject, body, attach_qrcode=True):
        if not self.config.get('USE_SMTP', False): return

        smtp_config = self.config.get('SMTP', {})
        from_addr = smtp_config.get('SENDER', None)
        password = smtp_config.get('PASSWORD', None)
        to_addr = smtp_config.get('RECEIVER', None)
        server = smtp_config.get('SERVER', None)
        port = smtp_config.get('PORT', 587)
        if not all([from_addr, password, to_addr, server]):
            self.logger.error("SMTP配置不完整，无法发送邮件")
            return

        try:
            message = MIMEMultipart()
            message['From'] = from_addr
            message['To'] = to_addr
            message['Subject'] = Header(subject, 'utf-8')
            message.attach(MIMEText(body, 'plain', 'utf-8'))
            
            if attach_qrcode and os.path.exists(self.qrcode_path):
                with open(self.qrcode_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<qrcode>')
                    img.add_header('Content-Disposition', 'attachment', filename='qrcode.png')
                    message.attach(img)
                    self.logger.info("已将二维码添加到邮件中")

            async with aiosmtplib.SMTP(hostname=server, port=port, use_tls=True) as smtp:
                await smtp.login(from_addr, password)
                await smtp.sendmail(from_addr, [to_addr], message.as_string())
            self.logger.info(f"邮件已发送至 {to_addr}")
        except Exception as e:
            self.logger.error(f"发送邮件时出错: {str(e)}")

    def controller(self):
        def decorator(func):
            async def wrapper(*args, **kwargs): 
                async def watch_qrcode():
                    self.logger.info("开始监控登录信息...")
                    last_mtime = None
                    max_retries = 128

                    while max_retries:
                        max_retries == 128 or await asyncio.sleep(3)
                        max_retries -= 1
                        try:
                            if os.path.exists(self.qrcode_path): current_mtime = os.path.getmtime(self.qrcode_path) or None
                            else: continue
                            if last_mtime is None: last_mtime = current_mtime
                            elif current_mtime != last_mtime:
                                self.logger.info("检测到二维码更新，发起邮件提醒")
                                await self.send_email("QQ登录状态更新提醒", "请查看附件中的二维码进行登录（您必须使用另一台设备扫码）")
                                break
                        except Exception as e: 
                            self.logger.error(f"监控登录信息时出错: {str(e)}")
                    else:
                        self.logger.error("登录信息监控已达到最大轮询次数，停止监控")

                while True:
                    try: return await func(*args, **kwargs)
                    except BrowserException as e:
                        await e.browser.close()
                        self.logger.error(f"登录信息过期，准备重试...")
                        kwargs['first_run'] = False
                        asyncio.create_task(watch_qrcode())
                    except Exception as e:
                        self.logger.error(f"执行函数时出错: {str(e)}")
                        exit()

            return wrapper
        return decorator
