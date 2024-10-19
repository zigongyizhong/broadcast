## 自贡一中新闻采集系统
一个可以从各类网站下载**最高画质**视频，添加台标、片头、片尾，并且转换为 MPG/AVI 格式的工具。

### 配置开发环境
安装所需的第三方库
```
pip install requests bs4 psutil PyQt5 yt_dlp
```

若在中国大陆地区连接速度较慢，可使用国内的镜像源
```
pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple requests bs4 psutil PyQt5 yt_dlp
```

此外，需要您手动下载[FFmpeg](https://www.ffmpeg.org/)，并将`ffmpeg.exe`和`ffprobe.exe`置于`ffmpeg`文件夹内

### 版权说明
本程序的目的只是为了审核并向**校内**学生放送由教师筛选过的新闻，仅在自贡市第一中学校放送，并无盗播行为。若本程序侵犯了您的合法权益，请在 Issues 提出。
