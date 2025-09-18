import os
import sys
import cv2
import time
import logging
import threading
import subprocess
import numpy as np
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from werkzeug.utils import secure_filename

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("stream_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

stream_url = os.getenv("STREAM_URL", "")

CONFIG = {
    "IMAGE_DIR":  "./images",       # 图片文件夹路径
    "PORT": 8083,                   # Web服务端口
    "STREAM_URL": stream_url,       # 推流地址
    "WIDTH": 1920,                  # 推流宽度
    "HEIGHT": 1080,                 # 推流高度
    "FPS": 25,                      # 帧率
    "GOP_SIZE": 25,                 # 关键帧间隔
    "BITRATE": "2M",                # 码率
    "DEBUG": True,                  # 调试模式
    "PRESET": "ultrafast",        # 编码预设
    # 有 ultrafast （转码速度最快，视频往往也最模糊）、superfast、veryfast、faster、fast、medium、slow、slower、veryslow、placebo这10个选项，从快到慢
    # （1）veryfast ：转码速度非常快，但是输出视频质量较差。
    # （2）faster ：转码速度比较快，输出的视频质量比veryfast模式稍微好一些。
    # （3）fast ：转码速度快，输出的视频质量较好。
    # （4）medium ：转码速度适中，输出视频质量也适中，如果不明确指定preset转码模式的话，默认值就是该值。
    # （5）slow ：转码速度慢，但是输出视频质量比medium要好。
    # （6）slower ：转码速度比较慢，但是输出的视频质量比较好。
    # （7）veryslow ：转码码速度非常慢，但是输出的视频质量非常好。
    "TUNE": "fastdecode",    # 编码调优
    # tune的值有： 
    #   film： 电影、真人类型；
    #   animation： 动画；
    #   grain： 需要保留大量的grain时用；
    #   stillimage： 静态图像编码时使用；
    #   psnr： 为提高psnr做了优化的参数；
    #   ssim： 为提高ssim做了优化的参数；
    #   fastdecode ： 可以快速解码的参数；
    #   zerolatency：零延迟，用在需要非常低的延迟的情况下，比如电视电话会议的编码。
    "RECOVERY_INTERVAL": 60,     # 自动恢复检查间隔（秒）

    "SECRET_KEY": 'supersecretkey', # # Flask会话密钥（生产环境请修改）
    "REFRESH_INTERVAL": 1000,        # Web界面状态刷新间隔（毫秒）
    "ALLOWED_EXTENSIONS": {'jpg', 'jpeg', 'png', 'bmp'},  # 允许的文件扩展名
    "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,  # 最大上传文件大小（16MB）
    "MAX_RETRY":3, # 最大重试次数
}

# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = CONFIG["SECRET_KEY"]
app.config['UPLOAD_FOLDER'] = CONFIG["IMAGE_DIR"]
app.config['ALLOWED_EXTENSIONS'] = CONFIG["ALLOWED_EXTENSIONS"]
app.config['MAX_CONTENT_LENGTH'] = CONFIG["MAX_CONTENT_LENGTH"]

# 全局状态
stream_state = {
    "running": False,
    "current_image_index": 0,
    "image_list": [],
    "process": None,
    "thread": None,
    "stop_event": threading.Event()
}

# 检查文件扩展名是否允许
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# 初始化图片目录
def init_image_directory():
    if not os.path.exists(CONFIG["IMAGE_DIR"]):
        os.makedirs(CONFIG["IMAGE_DIR"])
        logger.info(f"创建图片目录: {CONFIG['IMAGE_DIR']}")

# 加载图片列表
def load_image_list():
    try:
        image_files = []
        for file in os.listdir(CONFIG["IMAGE_DIR"]):
            if allowed_file(file):
                image_files.append(file)
        stream_state["image_list"] = sorted(image_files)
        logger.info(f"加载了 {len(stream_state['image_list'])} 张图片")
        return stream_state["image_list"]
    except Exception as e:
        logger.error(f"加载图片列表失败: {str(e)}")
        return []

# 准备图片进行推流
def prepare_image(image_path):
    try:
        # 读取图片
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"无法读取图片: {image_path}")
            return None

        # 调整图片尺寸
        image = cv2.resize(image, (CONFIG["WIDTH"], CONFIG["HEIGHT"]))
        return image
    except Exception as e:
        logger.error(f"准备图片失败: {str(e)}")
        return None

# RTSP推流函数
def start_rtsp_stream():
    load_image_list()
    
    if not stream_state["image_list"]:
        logger.error("没有找到可推流的图片")
        stream_state["running"] = False
        return

    # 准备第一张图片
    current_image_path = os.path.join(CONFIG["IMAGE_DIR"], stream_state["image_list"][0])
    current_image = prepare_image(current_image_path)
    
    if current_image is None:
        logger.error("无法准备初始图片")
        stream_state["running"] = False
        return

    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # 覆盖输出文件
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',
        '-s', f'{CONFIG["WIDTH"]}x{CONFIG["HEIGHT"]}',
        '-r', '25',
        '-i', '-',  # 从stdin读取
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-b:v', '2M',
        '-maxrate', '2M',
        '-bufsize', '4M',
        '-g', '25',
        '-keyint_min', '10',
        '-preset', CONFIG["PRESET"],
        '-tune', CONFIG["TUNE"],
        '-profile:v', 'high',
        '-level:v', '4.1',
        '-x264-params','repeat_headers=1',
        '-flags', '+global_header',
        '-bsf:v', 'h264_mp4toannexb',  # 确保正确处理H.264比特流格式
        '-f', 'rtsp',
        '-rtsp_transport', 'tcp',
        CONFIG["STREAM_URL"]
    ]

    try:
        # 启动FFmpeg进程
        stream_state["process"] = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        logger.info(f"开始推流到: {CONFIG['STREAM_URL']}")
        stream_state["running"] = True
        stream_state["stop_event"].clear()

        # 推流循环
        frame_interval = 1.0 / CONFIG["FPS"]
        last_frame_time = time.time()

        while not stream_state["stop_event"].is_set():
            # 检查是否需要切换图片
            current_time = time.time()
            if current_time - last_frame_time >= frame_interval:
                last_frame_time = current_time
                
                # 获取当前图片
                if stream_state["image_list"]:
                    index = stream_state["current_image_index"] % len(stream_state["image_list"])
                    image_path = os.path.join(CONFIG["IMAGE_DIR"], stream_state["image_list"][index])
                    current_image = prepare_image(image_path)
                    
                    if current_image is not None:
                        # 写入到FFmpeg进程
                        try:
                            stream_state["process"].stdin.write(current_image.tobytes())
                            stream_state["process"].stdin.flush()
                        except Exception as e:
                            logger.error(f"写入FFmpeg失败: {str(e)}")
                            break

            # 小延迟避免CPU占用过高
            time.sleep(0.001)

    except Exception as e:
        logger.error(f"推流过程中出错: {str(e)}")
        stream_state["running"] = False
    finally:
        # 清理资源
        if stream_state["process"]:
            try:
                stream_state["process"].stdin.close()
                stream_state["process"].stdout.close()
                stream_state["process"].stderr.close()
                stream_state["process"].terminate()
                stream_state["process"].wait(timeout=5)
            except:
                try:
                    stream_state["process"].kill()
                except:
                    pass
            stream_state["process"] = None
        
        stream_state["running"] = False
        logger.info("推流已停止")

# 启动推流线程
def start_stream_thread():
    if stream_state["thread"] and stream_state["thread"].is_alive():
        logger.warning("推流线程已经在运行")
        return False
    
    stream_state["stop_event"].clear()
    stream_state["thread"] = threading.Thread(target=start_rtsp_stream)
    stream_state["thread"].daemon = True
    stream_state["thread"].start()
    return True

# 停止推流
def stop_stream():
    if stream_state["running"]:
        stream_state["stop_event"].set()
        if stream_state["thread"]:
            stream_state["thread"].join(timeout=5)
        return True
    return False

# Web控制界面HTML
def get_web_interface_html():
    return '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>图片推流控制系统</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #333; }
        .status { padding: 10px; border-radius: 5px; margin-bottom: 20px; }
        .status.running { background-color: #d4edda; color: #155724; }
        .status.stopped { background-color: #f8d7da; color: #721c24; }
        .controls { margin-bottom: 20px; }
        .btn { padding: 10px 15px; margin: 5px; cursor: pointer; border: none; border-radius: 4px; font-size: 14px; }
        .btn-primary { background-color: #007bff; color: white; }
        .btn-secondary { background-color: #6c757d; color: white; }
        .btn-success { background-color: #28a745; color: white; }
        .btn-danger { background-color: #dc3545; color: white; }
        .image-list { border: 1px solid #ddd; border-radius: 5px; padding: 10px; max-height: 300px; overflow-y: auto; }
        .image-item { padding: 8px; margin: 5px 0; border-radius: 4px; cursor: pointer; }
        .image-item.active { background-color: #007bff; color: white; }
        .image-item:hover { background-color: #f0f0f0; }
        .upload-form { margin: 20px 0; }
        .upload-input { margin: 10px 0; }
        .logs { font-family: monospace; background-color: #f8f9fa; padding: 15px; border-radius: 5px; max-height: 200px; overflow-y: auto; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>图片推流控制系统</h1>
        
        <div id="status" class="status stopped">
            <p>状态: <span id="status-text">已停止</span></p>
            <p>当前图片: <span id="current-image">无</span></p>
            <p>推流地址: <a href="{{ stream_url }}" target="_blank">{{ stream_url }}</a></p>
        </div>
        
        <div class="controls">
            <button id="start-btn" class="btn btn-success">开始推流</button>
            <button id="stop-btn" class="btn btn-danger">停止推流</button>
            <button id="restart-btn" class="btn btn-primary">重启推流</button>
            <button id="prev-btn" class="btn btn-secondary">上一张</button>
            <button id="next-btn" class="btn btn-secondary">下一张</button>
        </div>
        
        <div class="upload-form">
            <h3>上传新图片</h3>
            <form id="upload-form" enctype="multipart/form-data">
                <input type="file" name="file" class="upload-input" accept=".jpg,.jpeg,.png,.bmp">
                <button type="submit" class="btn btn-primary">上传</button>
            </form>
        </div>
        
        <h3>图片列表</h3>
        <div id="image-list" class="image-list">
            <!-- 图片列表将通过JavaScript动态生成 -->
        </div>
        
        <h3>系统信息</h3>
        <div class="logs" id="logs">
            <!-- 日志将通过JavaScript动态更新 -->
        </div>
    </div>
    
    <script>
        // 刷新状态
        function refreshStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    const statusEl = document.getElementById('status');
                    const statusTextEl = document.getElementById('status-text');
                    const currentImageEl = document.getElementById('current-image');
                    
                    if (data.running) {
                        statusEl.className = 'status running';
                        statusTextEl.textContent = '运行中';
                    } else {
                        statusEl.className = 'status stopped';
                        statusTextEl.textContent = '已停止';
                    }
                    
                    if (data.current_image) {
                        currentImageEl.textContent = data.current_image;
                    }
                    
                    // 更新日志
                    const logsEl = document.getElementById('logs');
                    logsEl.innerHTML = `系统状态: ${data.running ? '运行中' : '已停止'}<br>`;
                    logsEl.innerHTML += `当前图片索引: ${data.current_image_index}<br>`;
                    logsEl.innerHTML += `图片总数: ${data.image_count}<br>`;
                    logsEl.innerHTML += `上次更新时间: ${new Date().toLocaleString()}<br>`;
                });
        }
        
        // 刷新图片列表
        function refreshImageList() {
            fetch('/api/list')
                .then(response => response.json())
                .then(data => {
                    const listEl = document.getElementById('image-list');
                    listEl.innerHTML = '';
                    
                    data.images.forEach((image, index) => {
                        const item = document.createElement('div');
                        item.className = `image-item ${index === data.current_index ? 'active' : ''}`;
                        item.textContent = image;
                        item.onclick = () => goToImage(index);
                        listEl.appendChild(item);
                    });
                });
        }
        
        // 发送命令
        function sendCommand(endpoint) {
            fetch(`/api/${endpoint}`, {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                console.log(data);
                refreshStatus();
                refreshImageList();
            })
            .catch(error => {
                console.error('Error:', error);
            });
        }
        
        // 跳转到指定图片
        function goToImage(index) {
            fetch('/api/goto', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ index: index })
            })
            .then(response => response.json())
            .then(data => {
                console.log(data);
                refreshStatus();
                refreshImageList();
            })
            .catch(error => {
                console.error('Error:', error);
            });
        }
        
        // 上传图片
        document.getElementById('upload-form').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            fetch('/api/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                console.log(data);
                refreshStatus();
                refreshImageList();
                this.reset();
            })
            .catch(error => {
                console.error('Error:', error);
            });
        });
        
        // 添加按钮事件监听
        document.getElementById('start-btn').addEventListener('click', () => sendCommand('start'));
        document.getElementById('stop-btn').addEventListener('click', () => sendCommand('stop'));
        document.getElementById('restart-btn').addEventListener('click', () => sendCommand('restart'));
        document.getElementById('prev-btn').addEventListener('click', () => sendCommand('prev'));
        document.getElementById('next-btn').addEventListener('click', () => sendCommand('next'));
        
        // 定期刷新状态和列表
        setInterval(refreshStatus, 1000);
        setInterval(refreshImageList, 2000);
        
        // 初始加载
        refreshStatus();
        refreshImageList();
    </script>
</body>
</html>
'''

# API路由
@app.route('/')
def index():
    return render_template_string(get_web_interface_html(), stream_url=CONFIG["STREAM_URL"])

@app.route('/api/status')
def get_status():
    current_image = ""
    if stream_state["image_list"] and stream_state["current_image_index"] < len(stream_state["image_list"]):
        current_image = stream_state["image_list"][stream_state["current_image_index"]]
    
    return jsonify({
        "running": stream_state["running"],
        "current_image": current_image,
        "current_image_index": stream_state["current_image_index"],
        "image_count": len(stream_state["image_list"]),
        "stream_url": CONFIG["STREAM_URL"]
    })

@app.route('/api/start', methods=['POST'])
def api_start():
    try:
        if stream_state["running"]:
            return jsonify({"success": False, "message": "推流已经在运行中"})
        
        if start_stream_thread():
            return jsonify({"success": True, "message": "推流已开始"})
        else:
            return jsonify({"success": False, "message": "启动推流失败"})
    except Exception as e:
        logger.error(f"启动推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    try:
        if not stream_state["running"]:
            return jsonify({"success": False, "message": "推流已经停止"})
        
        if stop_stream():
            return jsonify({"success": True, "message": "推流已停止"})
        else:
            return jsonify({"success": False, "message": "停止推流失败"})
    except Exception as e:
        logger.error(f"停止推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/restart', methods=['POST'])
def api_restart():
    try:
        stop_stream()
        time.sleep(1)  # 给系统一点时间停止
        
        if start_stream_thread():
            return jsonify({"success": True, "message": "推流已重启"})
        else:
            return jsonify({"success": False, "message": "重启推流失败"})
    except Exception as e:
        logger.error(f"重启推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/next', methods=['POST'])
def api_next():
    try:
        load_image_list()
        if not stream_state["image_list"]:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        stream_state["current_image_index"] = (stream_state["current_image_index"] + 1) % len(stream_state["image_list"])
        logger.info(f"切换到下一张图片: {stream_state['image_list'][stream_state['current_image_index']]}")
        
        return jsonify({
            "success": True,
            "message": "已切换到下一张图片",
            "current_image": stream_state["image_list"][stream_state["current_image_index"]],
            "index": stream_state["current_image_index"]
        })
    except Exception as e:
        logger.error(f"切换到下一张图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/prev', methods=['POST'])
def api_prev():
    try:
        load_image_list()
        if not stream_state["image_list"]:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        stream_state["current_image_index"] = (stream_state["current_image_index"] - 1) % len(stream_state["image_list"])
        logger.info(f"切换到上一张图片: {stream_state['image_list'][stream_state['current_image_index']]}")
        
        return jsonify({
            "success": True,
            "message": "已切换到上一张图片",
            "current_image": stream_state["image_list"][stream_state["current_image_index"]],
            "index": stream_state["current_image_index"]
        })
    except Exception as e:
        logger.error(f"切换到上一张图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/goto', methods=['POST'])
def api_goto():
    try:
        load_image_list()
        if not stream_state["image_list"]:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        data = request.get_json()
        if 'index' in data:
            index = int(data['index'])
            if 0 <= index < len(stream_state["image_list"]):
                stream_state["current_image_index"] = index
                logger.info(f"跳转到图片: {stream_state['image_list'][stream_state['current_image_index']]}")
                return jsonify({
                    "success": True,
                    "message": "已跳转到指定图片",
                    "current_image": stream_state["image_list"][stream_state["current_image_index"]],
                    "index": stream_state["current_image_index"]
                })
            else:
                return jsonify({"success": False, "message": "索引超出范围"})
        elif 'filename' in data:
            filename = data['filename']
            if filename in stream_state["image_list"]:
                stream_state["current_image_index"] = stream_state["image_list"].index(filename)
                logger.info(f"跳转到图片: {filename}")
                return jsonify({
                    "success": True,
                    "message": "已跳转到指定图片",
                    "current_image": filename,
                    "index": stream_state["current_image_index"]
                })
            else:
                return jsonify({"success": False, "message": "文件不存在"})
        else:
            return jsonify({"success": False, "message": "缺少index或filename参数"})
    except Exception as e:
        logger.error(f"跳转到指定图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/upload', methods=['POST'])
def api_upload():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "message": "没有文件部分"})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "message": "没有选择文件"})
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # 重新加载图片列表
            load_image_list()
            logger.info(f"上传了新图片: {filename}")
            
            return jsonify({
                "success": True,
                "message": "图片上传成功",
                "filename": filename
            })
        else:
            return jsonify({"success": False, "message": "不支持的文件格式"})
    except Exception as e:
        logger.error(f"上传图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/list')
def api_list():
    try:
        load_image_list()
        return jsonify({
            "success": True,
            "images": stream_state["image_list"],
            "current_index": stream_state["current_image_index"],
            "count": len(stream_state["image_list"])
        })
    except Exception as e:
        logger.error(f"获取图片列表API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

# 自动恢复功能
def auto_recovery():
    def recovery_task():
        retry_count = 0
        while True:
            try:
                # 检查推流是否应该运行但实际没有运行
                if not stream_state["running"] and stream_state["thread"] and not stream_state["thread"].is_alive():
                    logger.warning(f"检测到推流异常停止，尝试自动恢复... (第{retry_count+1}次重试)")
                    max_retry = CONFIG["MAX_RETRY"]
                    if retry_count < max_retry:
                        start_stream_thread()
                        retry_count += 1
                    else:
                        logger.error(f"已达到最大重试次数 ({max_retry})，停止自动恢复")
                        retry_count = 0
                        # 等待更长时间后再尝试
                        time.sleep(CONFIG["RECOVERY_INTERVAL"] * 3)
                        continue
            except Exception as e:
                logger.error(f"自动恢复过程中出错: {str(e)}")
            
            # 按照配置的间隔检查
            time.sleep(CONFIG["RECOVERY_INTERVAL"])
    
    recovery_thread = threading.Thread(target=recovery_task)
    recovery_thread.daemon = True
    recovery_thread.start()

# 主函数
if __name__ == '__main__':
    try:
        # 初始化图片目录
        init_image_directory()
        
        # 加载图片列表
        load_image_list()
        
        # 启动自动恢复功能
        auto_recovery()
        
        # 启动时自动开始推流（如果有图片）
        if stream_state["image_list"]:
            start_stream_thread()
        else:
            logger.warning("没有找到图片，系统已启动但未开始推流")
        
        # 启动Flask服务
        logger.info(f"Web服务启动在端口 {CONFIG['PORT']}")
        app.run(host='0.0.0.0', port=CONFIG['PORT'], debug=CONFIG['DEBUG'], use_reloader=False)
    except Exception as e:
        logger.error(f"系统启动失败: {str(e)}")
        sys.exit(1)