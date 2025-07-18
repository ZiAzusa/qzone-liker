# qzone-liker
扣扣空间自动点赞工具

## Usage
对于部分Linux系统，可能需要安装zbar库：
```shell
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install libzbar0

# CentOS/Fedora
sudo dnf install zbar

# CentOS 8以前
sudo yum install zbar
```
然后安装需要的依赖，并初始化配置文件
```shell
pip install -r requirements.txt
playwright install # 安装Chrome
python3 qzone_liker.py
```
然后根据提示修改配置文件再执行即可扫码登录。

## Principle
使用Playwright无头Chrome结合JS模拟点击。

## License
MIT License
