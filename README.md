# 图片模拟推流

图片模拟推流，支持通过RTSP协议推送图片，并提供Web界面和HTTP API进行控制。

## 功能特点

### 推流功能
- 从指定文件夹读取图片（支持JPG/PNG/BMP格式）
- 25fps帧率
- 关键帧间隔25帧
- H.264编码，包含SPS/PPS信息
- RTSP over TCP

### 控制功能
- 启动时自动推送第一张图片
- 支持通过 HTTP API动态切换推流图片
- 可切换到下一张/上一张图片
- 可跳转到指定图片（按文件名或索引）
- 支持开始/停止/重启推流

## 技术架构
- Flask Web服务：提供HTTP API和Web控制界面
- OpenCV：处理图片读取和尺寸调整
- FFmpeg：处理视频编码和RTSP推流
- Threading：实现异步推流和自动恢复

## 安装要求

### 系统要求
- Python 3.6+ 环境
- FFmpeg 安装（用于视频编码和推流）
- 足够的内存和CPU资源处理图片编码

### 依赖包
- Flask：Web服务框架
- OpenCV-python：图像处理
- NumPy：数组计算
- ffmpeg-python：FFmpeg封装
- waitress：WSGI服务器

## 快速开始

### 1. 准备图片

将需要推流的图片放入系统自动创建的`./images`文件夹中。


### 2. 安装依赖

```bash
pip install -r ./requirements.txt
```
### 3. 启动服务

```bash
python3.11 main.py
```

服务将在 `http://localhost:8083` 上运行。

### 4. 访问Web界面

打开浏览器，访问 `http://localhost:8083` 进入Web控制界面。

## API 接口说明

系统提供以下HTTP API端点：

### 获取系统状态
```
GET /api/status
```
**返回示例：**
```json
{
  "running": true,
  "current_image": "example.jpg",
  "current_image_index": 0,
  "image_count": 5,
  "stream_url": "rtsp://xxx.xxx.xxx.xxx/live/test-image-004"
}
```

### 开始推流
```
POST /api/start
```
**返回示例：**
```json
{"success": true, "message": "推流已开始"}
```

### 停止推流
```
POST /api/stop
```
**返回示例：**
```json
{"success": true, "message": "推流已停止"}
```

### 重启推流
```
POST /api/restart
```
**返回示例：**
```json
{"success": true, "message": "推流已重启"}
```

### 下一张图片
```
POST /api/next
```
**返回示例：**
```json
{
  "success": true,
  "message": "已切换到下一张图片",
  "current_image": "next_image.jpg",
  "index": 1
}
```

### 上一张图片
```
POST /api/prev
```
**返回示例：**
```json
{
  "success": true,
  "message": "已切换到上一张图片",
  "current_image": "prev_image.jpg",
  "index": 0
}
```

### 跳转到指定图片
```
POST /api/goto
Content-Type: application/json

// 按索引跳转
{"index": 2}

// 按文件名跳转
{"filename": "specific_image.jpg"}
```
**返回示例：**
```json
{
  "success": true,
  "message": "已跳转到指定图片",
  "current_image": "specific_image.jpg",
  "index": 2
}
```

### 上传新图片
```
POST /api/upload
Content-Type: multipart/form-data

// Form字段
file: <图片文件>
```
**返回示例：**
```json
{
  "success": true,
  "message": "图片上传成功",
  "filename": "uploaded_image.jpg"
}
```

### 获取图片列表
```
GET /api/list
```
**返回示例：**
```json
{
  "success": true,
  "images": ["image1.jpg", "image2.jpg", "image3.jpg"],
  "current_index": 0,
  "count": 3
}
```



## 故障排除

### 常见问题

1. **推流失败**
   - 确保FFmpeg已正确安装
   - 检查RTSP服务器地址是否正确
   - 检查网络连接是否正常

2. **图片切换不流畅**
   - 确保图片尺寸适中（推荐1920×1080）
   - 检查系统资源使用情况

# 注意
本项目为测试验证项目，部分代码为 AI 生成
