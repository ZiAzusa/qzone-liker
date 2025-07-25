# qzone-liker
扣扣空间自动点赞工具

## Released Usage
Win端（x86）直接下载Release中的xxx-win-amd64，解压运行后根据提示修改配置文件再执行即可扫码登录。

生成的yaml配置文件可使用记事本打开编辑，如果你不知道其他的项目的作用是什么，请只填写QID（用于点赞的账号的QQ号）和BLACKLIST（不点赞谁的说说）。

## Code Usage
安装需要的依赖，并初始化配置文件
```shell
pip install -r requirements.txt
python3 -m playwright install chromium # 安装Chromium
python3 qzone_liker.py
```
然后根据提示修改配置文件再执行即可扫码登录。

也可以后台运行：
```shell
nohup python3 qzone_liker.py > /dev/null 2>&1 &
```
config.yaml配置文件模板如下：
```yaml
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
```

## Principle
使用Playwright无头Chromium结合JS模拟点击。

## Feature
提供了断线重连、日志分块、邮件通知等功能。

## License
MIT License
