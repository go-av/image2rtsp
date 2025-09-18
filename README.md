# 多视频流模拟推送

这是一个支持多个视频流模拟推送的系统，能够将图片序列(收到切换)推送到RTSP服务器。

## 功能特点

- 📋 **多任务管理**：支持创建多个独立的推流任务
- 📷 **自适应分辨率**：每个任务的视频流分辨率根据第一张上传的图片自动调整
- 💾 **任务持久化**：任务配置自动保存，重启后可恢复
- 🖥️ **友好界面**：简洁直观的Web操作界面
- 🎬 **RTSP推流**：将图片序列推送到指定的RTSP服务器
- 🔄 **自动恢复**：监控推流状态，异常时自动尝试恢复

## 系统要求

- Python 3.6+ 
- FFmpeg（必须安装，用于视频编码和推流）
- 推荐使用虚拟环境运行

## 安装指南

### 1. 安装系统依赖

#### Ubuntu/Debian
```bash
apt-get update && apt-get install -y python3 python3-pip ffmpeg
```

#### macOS
```bash
brew install python3 ffmpeg
```

#### Windows
- 下载并安装 [Python](https://www.python.org/downloads/)
- 下载并安装 [FFmpeg](https://ffmpeg.org/download.html)

### 2. 克隆项目

```bash
git clone git@github.com:go-av/image2rtsp.git
cd image2rtsp
```



#### 安装Python依赖
```bash
pip install -r requirements.txt
```

#### 手动启动应用
```bash
python main.py
```

## 使用说明

### 访问Web界面

启动应用后，打开浏览器访问：`http://localhost:8083`

### 创建推流任务
1. 在首页点击 "创建新任务" 按钮
2. 输入任务名称和RTSP推流地址
3. 上传至少一张图片（第一张图片的分辨率将决定视频流的分辨率）
4. 点击 "创建" 按钮

### 管理任务

- **查看任务列表**：在首页可以查看所有已创建的任务及其状态
- **任务详情**：点击任务卡片查看详细信息和操作选项
- **启动/停止/重启推流**：在任务详情页可以控制推流状态
- **图片管理**：在任务详情页可以上传、删除和切换图片

### 注意事项

- 所有上传的图片必须与第一张图片的分辨率相同
- 确保目标RTSP服务器地址正确且可访问
- 推流质量和性能受FFmpeg配置和服务器性能影响


## 常见问题

### FFmpeg未找到

如果系统提示找不到FFmpeg，请确保已正确安装并添加到系统PATH中。

### 推流失败

1. 检查RTSP地址是否正确
2. 确认目标服务器是否可以连接
3. 查看日志文件 `stream_server.log` 获取详细错误信息

### 图片上传失败

1. 确保图片格式受支持（jpg、jpeg、png、bmp）
2. 检查图片尺寸是否与任务要求一致
3. 确认文件大小不超过16MB

## 免责声明

本软件部分代码源于 AI 生成
