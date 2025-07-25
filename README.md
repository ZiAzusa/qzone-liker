# qzone-liker
扣扣空间自动点赞工具

## Usage
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

## Principle
使用Playwright无头Chromium结合JS模拟点击。

## Feature
提供了断线重连、日志分块、邮件通知等功能。

## License
MIT License
