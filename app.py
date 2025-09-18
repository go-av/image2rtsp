import os
import sys
import cv2
import time
import json
import uuid
import threading
import subprocess
import numpy as np
import logging
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify, send_from_directory, render_template
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

# 基础配置
class Config:
    # 项目根目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Web服务配置
    PORT = 8083
    DEBUG = True
    SECRET_KEY = 'supersecretkey'  # 生产环境请修改
    REFRESH_INTERVAL = 1000        # Web界面状态刷新间隔（毫秒）
    
    # 文件上传配置
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'images')
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 最大上传文件大小（16MB）
    
    # 任务和数据配置
    TASKS_DIR = os.path.join(BASE_DIR, 'data', 'tasks')
    TASK_DATA_FILE = os.path.join(BASE_DIR, 'data', 'tasks.json')
    
    # FFmpeg编码配置
    FPS = 25
    GOP_SIZE = 25
    BITRATE = "2M"
    PRESET = "ultrafast"  # 编码预设
    TUNE = "fastdecode"   # 编码调优
    
    # 系统配置
    MAX_RETRY = 3         # 最大重试次数
    RECOVERY_INTERVAL = 60  # 自动恢复检查间隔（秒）

# 任务管理类
class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.load_tasks()
        
    def load_tasks(self):
        """从文件加载任务配置"""
        try:
            if not os.path.exists(Config.TASK_DATA_FILE):
                # 确保数据目录存在
                os.makedirs(os.path.dirname(Config.TASK_DATA_FILE), exist_ok=True)
                # 创建空的任务文件
                with open(Config.TASK_DATA_FILE, 'w') as f:
                    json.dump({}, f)
                logger.info("创建了空的任务配置文件")
                return
            
            with open(Config.TASK_DATA_FILE, 'r') as f:
                self.tasks = json.load(f)
                
            # 程序重启时，所有任务都应该是stopped状态
            for task_id in self.tasks:
                self.tasks[task_id]['status'] = 'stopped'
                
            # 保存更新后的任务状态
            self.save_tasks()
            logger.info(f"成功加载了 {len(self.tasks)} 个任务配置，并重置所有任务状态为stopped")
        except Exception as e:
            logger.error(f"加载任务配置失败: {str(e)}")
            self.tasks = {}
    
    def save_tasks(self):
        """保存任务配置到文件"""
        try:
            with open(Config.TASK_DATA_FILE, 'w') as f:
                json.dump(self.tasks, f, indent=2, ensure_ascii=False)
            logger.info(f"成功保存了 {len(self.tasks)} 个任务配置")
        except Exception as e:
            logger.error(f"保存任务配置失败: {str(e)}")
    
    def create_task(self, task_name: str, stream_url: str, width: int, height: int) -> str:
        """创建新任务"""
        try:
            # 检查任务名称是否已存在
            for task_id, task in self.tasks.items():
                if task.get('name') == task_name:
                    logger.error(f"任务名称 '{task_name}' 已存在")
                    return None
            
            # 生成唯一ID
            task_id = str(uuid.uuid4())
            
            # 确保该任务的图片目录存在
            task_images_dir = os.path.join(Config.TASKS_DIR, task_id, 'images')
            os.makedirs(task_images_dir, exist_ok=True)
            
            # 创建任务配置
            self.tasks[task_id] = {
                'name': task_name,
                'stream_url': stream_url,
                'width': width,
                'height': height,
                'created_at': json.dumps({'$date': int(time.time() * 1000)}),  # 模拟MongoDB时间格式
                'updated_at': json.dumps({'$date': int(time.time() * 1000)}),
                'images_dir': task_images_dir,
                'image_list': [],
                'status': 'stopped'  # stopped, running, error
            }
            
            self.save_tasks()
            logger.info(f"创建任务成功: {task_id}, 名称: {task_name}, 推流地址: {stream_url}, 分辨率: {width}x{height}")
            return task_id
        except Exception as e:
            logger.error(f"创建任务失败: {str(e)}")
            return None
    
    def update_task(self, task_id: str, **kwargs) -> bool:
        """更新任务配置"""
        try:
            if task_id not in self.tasks:
                logger.error(f"任务ID '{task_id}' 不存在")
                return False
            
            self.tasks[task_id].update(kwargs)
            self.tasks[task_id]['updated_at'] = json.dumps({'$date': int(time.time() * 1000)})
            self.save_tasks()
            logger.info(f"更新任务成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"更新任务失败: {str(e)}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        try:
            if task_id not in self.tasks:
                logger.error(f"任务ID '{task_id}' 不存在")
                return False
            
            del self.tasks[task_id]
            self.save_tasks()
            logger.info(f"删除任务成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务失败: {str(e)}")
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有任务"""
        return list(self.tasks.values())
    
    def add_image_to_task(self, task_id: str, filename: str) -> bool:
        """向任务添加图片"""
        try:
            if task_id not in self.tasks:
                logger.error(f"任务ID '{task_id}' 不存在")
                return False
            
            if filename not in self.tasks[task_id]['image_list']:
                self.tasks[task_id]['image_list'].append(filename)
                self.tasks[task_id]['updated_at'] = json.dumps({'$date': int(time.time() * 1000)})
                self.save_tasks()
                logger.info(f"向任务 {task_id} 添加图片成功: {filename}")
            return True
        except Exception as e:
            logger.error(f"向任务添加图片失败: {str(e)}")
            return False
    
    def remove_image_from_task(self, task_id: str, filename: str) -> bool:
        """从任务移除图片"""
        try:
            if task_id not in self.tasks:
                logger.error(f"任务ID '{task_id}' 不存在")
                return False
            
            # 确保至少保留一张图片
            if filename in self.tasks[task_id]['image_list'] and len(self.tasks[task_id]['image_list']) > 1:
                self.tasks[task_id]['image_list'].remove(filename)
                self.tasks[task_id]['updated_at'] = json.dumps({'$date': int(time.time() * 1000)})
                self.save_tasks()
                logger.info(f"从任务 {task_id} 移除图片成功: {filename}")
                return True
            else:
                logger.warning(f"任务 {task_id} 只能保留最后一张图片，无法删除")
                return False
        except Exception as e:
            logger.error(f"从任务移除图片失败: {str(e)}")
            return False

# 创建全局任务管理器实例
task_manager = TaskManager()

# 创建Flask应用
app = Flask(__name__, template_folder=os.path.join(Config.BASE_DIR, 'templates'), static_folder=os.path.join(Config.BASE_DIR, 'static'))
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

# 全局任务状态
stream_tasks = {}

# 检查文件扩展名是否允许
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# 初始化目录
def init_directories():
    # 确保基础目录存在
    directories = [
        Config.UPLOAD_FOLDER,
        Config.TASKS_DIR,
        os.path.dirname(Config.TASK_DATA_FILE)
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"创建目录: {directory}")

# 准备图片进行推流
def prepare_image(image_path, width, height):
    try:
        # 读取图片
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"无法读取图片: {image_path}")
            return None
        
        # 注意：由于上传时已经限制了图片尺寸，此处不再需要调整大小
        # 直接返回原始图片
        return image
    except Exception as e:
        logger.error(f"准备图片失败: {str(e)}")
        return None

# 获取任务的图片列表
def get_task_image_list(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return []
        
        images_dir = task['images_dir']
        image_files = []
        
        # 从文件系统加载图片列表
        if os.path.exists(images_dir):
            for file in os.listdir(images_dir):
                if allowed_file(file):
                    image_files.append(file)
        
        # 更新任务的图片列表
        task_manager.update_task(task_id, image_list=sorted(image_files))
        return sorted(image_files)
    except Exception as e:
        logger.error(f"加载任务图片列表失败: {str(e)}")
        return []

# RTSP推流函数
def start_rtsp_stream(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        logger.error(f"任务不存在: {task_id}")
        if task_id in stream_tasks:
            stream_tasks[task_id]['running'] = False
        return
    
    # 获取图片列表
    image_list = get_task_image_list(task_id)
    if not image_list:
        logger.error(f"任务 {task_id} 没有找到可推流的图片")
        task_manager.update_task(task_id, status='error')
        if task_id in stream_tasks:
            stream_tasks[task_id]['running'] = False
        return
    
    # 获取任务配置
    stream_url = task['stream_url']
    width = task['width']
    height = task['height']
    
    # 准备第一张图片
    current_image_path = os.path.join(task['images_dir'], image_list[0])
    current_image = prepare_image(current_image_path, width, height)
    
    if current_image is None:
        logger.error(f"任务 {task_id} 无法准备初始图片")
        task_manager.update_task(task_id, status='error')
        if task_id in stream_tasks:
            stream_tasks[task_id]['running'] = False
        return
    
    # 构建FFmpeg命令
    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # 覆盖输出文件
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',
        '-s', f'{width}x{height}',
        '-r', str(Config.FPS),
        '-i', '-',  # 从stdin读取
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-b:v', Config.BITRATE,
        '-maxrate', Config.BITRATE,
        '-bufsize', f'{int(Config.BITRATE[:-1]) * 2}M',
        '-g', str(Config.GOP_SIZE),
        '-keyint_min', str(max(10, Config.GOP_SIZE // 2)),
        '-preset', Config.PRESET,
        '-tune', Config.TUNE,
        '-profile:v', 'high',
        '-level:v', '4.1',
        '-x264-params','repeat_headers=1',
        '-flags', '+global_header',
        '-bsf:v', 'h264_mp4toannexb',  # 确保正确处理H.264比特流格式
        '-f', 'rtsp',
        '-rtsp_transport', 'tcp',
        stream_url
    ]
    
    try:
        # 启动FFmpeg进程
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        logger.info(f"任务 {task_id} 开始推流到: {stream_url}")
        task_manager.update_task(task_id, status='running')
        
        # 更新任务状态
        stream_tasks[task_id] = {
            'running': True,
            'current_image_index': 0,
            'image_list': image_list,
            'process': process,
            'thread': threading.current_thread(),
            'stop_event': stream_tasks[task_id]['stop_event'] if task_id in stream_tasks else threading.Event()
        }
        
        # 重置停止事件
        stream_tasks[task_id]['stop_event'].clear()
        
        # 推流循环
        frame_interval = 1.0 / Config.FPS
        last_frame_time = time.time()
        
        while not stream_tasks[task_id]['stop_event'].is_set():
            # 检查是否需要切换图片
            current_time = time.time()
            if current_time - last_frame_time >= frame_interval:
                last_frame_time = current_time
                
                # 获取当前图片
                if stream_tasks[task_id]['image_list']:
                    index = stream_tasks[task_id]['current_image_index'] % len(stream_tasks[task_id]['image_list'])
                    image_path = os.path.join(task['images_dir'], stream_tasks[task_id]['image_list'][index])
                    current_image = prepare_image(image_path, width, height)
                    
                    if current_image is not None:
                        # 写入到FFmpeg进程
                        try:
                            process.stdin.write(current_image.tobytes())
                            process.stdin.flush()
                        except Exception as e:
                            logger.error(f"任务 {task_id} 写入FFmpeg失败: {str(e)}")
                            break
            
            # 小延迟避免CPU占用过高
            time.sleep(0.001)
            
            # 定期刷新图片列表
            if int(time.time()) % 5 == 0:  # 每5秒刷新一次
                new_image_list = get_task_image_list(task_id)
                if new_image_list != stream_tasks[task_id]['image_list']:
                    stream_tasks[task_id]['image_list'] = new_image_list
                    logger.info(f"任务 {task_id} 图片列表已更新，当前 {len(new_image_list)} 张图片")
    
    except Exception as e:
        logger.error(f"任务 {task_id} 推流过程中出错: {str(e)}")
        task_manager.update_task(task_id, status='error')
    finally:
        # 清理资源
        if task_id in stream_tasks and stream_tasks[task_id].get('process'):
            try:
                stream_tasks[task_id]['process'].stdin.close()
                stream_tasks[task_id]['process'].stdout.close()
                stream_tasks[task_id]['process'].stderr.close()
                stream_tasks[task_id]['process'].terminate()
                stream_tasks[task_id]['process'].wait(timeout=5)
            except:
                try:
                    stream_tasks[task_id]['process'].kill()
                except:
                    pass
            stream_tasks[task_id]['process'] = None
        
        if task_id in stream_tasks:
            stream_tasks[task_id]['running'] = False
        task_manager.update_task(task_id, status='stopped')
        logger.info(f"任务 {task_id} 推流已停止")

# 启动推流线程
def start_stream_thread(task_id):
    if task_id in stream_tasks and stream_tasks[task_id].get('thread') and stream_tasks[task_id]['thread'].is_alive():
        logger.warning(f"任务 {task_id} 推流线程已经在运行")
        return False
    
    # 初始化任务状态
    if task_id not in stream_tasks:
        stream_tasks[task_id] = {
            'running': False,
            'current_image_index': 0,
            'image_list': [],
            'process': None,
            'thread': None,
            'stop_event': threading.Event()
        }
    else:
        stream_tasks[task_id]['stop_event'].clear()
    
    # 创建并启动新线程
    stream_tasks[task_id]['thread'] = threading.Thread(target=start_rtsp_stream, args=(task_id,))
    stream_tasks[task_id]['thread'].daemon = True
    stream_tasks[task_id]['thread'].start()
    return True

# 停止推流
def stop_stream(task_id):
    if task_id in stream_tasks and stream_tasks[task_id]['running']:
        stream_tasks[task_id]['stop_event'].set()
        if stream_tasks[task_id]['thread']:
            stream_tasks[task_id]['thread'].join(timeout=5)
        return True
    return False

# 自动恢复功能
def auto_recovery():
    def recovery_task():
        retry_counts = {}
        while True:
            try:
                tasks = task_manager.get_all_tasks()
                for task in tasks:
                    task_id = [tid for tid, t in task_manager.tasks.items() if t == task][0]
                    
                    # 检查任务是否应该运行但实际没有运行
                    if task.get('status') == 'running' and \
                       task_id in stream_tasks and \
                       not stream_tasks[task_id]['running'] and \
                       (not stream_tasks[task_id]['thread'] or not stream_tasks[task_id]['thread'].is_alive()):
                        
                        logger.warning(f"检测到任务 {task_id} 推流异常停止，尝试自动恢复...")
                        max_retry = Config.MAX_RETRY
                        retry_counts[task_id] = retry_counts.get(task_id, 0)
                        
                        if retry_counts[task_id] < max_retry:
                            start_stream_thread(task_id)
                            retry_counts[task_id] += 1
                        else:
                            logger.error(f"任务 {task_id} 已达到最大重试次数 ({max_retry})，停止自动恢复")
                            retry_counts[task_id] = 0
                            task_manager.update_task(task_id, status='error')
                            # 等待更长时间后再尝试
                            time.sleep(Config.RECOVERY_INTERVAL * 2)
                            continue
            except Exception as e:
                logger.error(f"自动恢复过程中出错: {str(e)}")
            
            # 按照配置的间隔检查
            time.sleep(Config.RECOVERY_INTERVAL)
    
    recovery_thread = threading.Thread(target=recovery_task)
    recovery_thread.daemon = True
    recovery_thread.start()

# Web路由
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/task/<task_id>')
def task_detail(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return render_template('error.html', message="任务不存在")
    return render_template('task_detail.html', task_id=task_id, task=task)

# API路由
@app.route('/api/tasks')
def api_get_tasks():
    try:
        tasks = task_manager.get_all_tasks()
        tasks_with_ids = []
        for task_id, task in task_manager.tasks.items():
            task_with_id = task.copy()
            task_with_id['task_id'] = task_id
            # 获取任务运行状态
            if task_id in stream_tasks:
                task_with_id['is_running'] = stream_tasks[task_id]['running']
                task_with_id['current_image_index'] = stream_tasks[task_id]['current_image_index']
            else:
                task_with_id['is_running'] = False
                task_with_id['current_image_index'] = 0
            tasks_with_ids.append(task_with_id)
        return jsonify({"success": True, "tasks": tasks_with_ids})
    except Exception as e:
        logger.error(f"获取任务列表API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/create', methods=['POST'])
def api_create_task():
    try:
        # 获取表单数据
        task_name = request.form.get('task_name')
        stream_url = request.form.get('stream_url')
        
        if not task_name or not stream_url:
            return jsonify({"success": False, "message": "缺少必要参数: task_name 或 stream_url"})
        
        # 检查是否上传了图片
        if 'file' not in request.files:
            return jsonify({"success": False, "message": "请至少上传一张图片"})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "message": "没有选择文件"})
        
        if file and allowed_file(file.filename):
            # 先保存图片以获取宽高
            temp_filename = secure_filename(file.filename)
            temp_path = os.path.join(Config.UPLOAD_FOLDER, temp_filename)
            file.save(temp_path)
            
            # 读取图片宽高
            try:
                image = cv2.imread(temp_path)
                if image is None:
                    os.remove(temp_path)
                    return jsonify({"success": False, "message": "无法读取上传的图片"})
                height, width = image.shape[:2]
                
                # 创建任务
                task_id = task_manager.create_task(task_name, stream_url, width, height)
                if task_id:
                    task = task_manager.get_task(task_id)
                    if not task:
                        os.remove(temp_path)
                        return jsonify({"success": False, "message": "任务创建失败，无法获取任务信息"})
                    
                    # 将图片移动到任务目录
                    task_image_path = os.path.join(task['images_dir'], temp_filename)
                    
                    # 如果文件名已存在，生成新文件名
                    if os.path.exists(task_image_path):
                        base, ext = os.path.splitext(temp_filename)
                        temp_filename = f"{base}_{int(time.time())}{ext}"
                        task_image_path = os.path.join(task['images_dir'], temp_filename)
                    
                    try:
                        os.rename(temp_path, task_image_path)
                        logger.info(f"图片移动成功: {temp_path} -> {task_image_path}")
                    except Exception as e:
                        logger.error(f"图片移动失败: {str(e)}")
                        os.remove(temp_path)
                        return jsonify({"success": False, "message": f"图片移动失败: {str(e)}"})
                    
                    # 更新任务的图片列表
                    if not task_manager.add_image_to_task(task_id, temp_filename):
                        logger.error(f"添加图片到任务失败: {temp_filename}")
                        if os.path.exists(task_image_path):
                            os.remove(task_image_path)
                        return jsonify({"success": False, "message": "添加图片到任务失败"})
                    
                    logger.info(f"任务 {task_id} 创建成功并上传了第一张图片: {temp_filename}")
                    return jsonify({"success": True, "message": "任务创建成功", "task_id": task_id})
                else:
                    os.remove(temp_path)
                    return jsonify({"success": False, "message": "任务创建失败，任务名称可能已存在"})
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                logger.error(f"处理图片时出错: {str(e)}")
                return jsonify({"success": False, "message": str(e)})
        else:
            return jsonify({"success": False, "message": "不支持的文件格式"})
    except Exception as e:
        logger.error(f"创建任务API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/status')
def api_get_task_status(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        # 获取任务运行状态
        status = {
            "running": False,
            "current_image_index": 0,
            "image_count": len(task.get('image_list', [])),
            "stream_url": task['stream_url'],
            "width": task['width'],
            "height": task['height'],
            "status": task.get('status', 'stopped')
        }
        
        if task_id in stream_tasks:
            status["running"] = stream_tasks[task_id]['running']
            status["current_image_index"] = stream_tasks[task_id]['current_image_index']
            
            # 获取当前图片
            if stream_tasks[task_id]['image_list'] and stream_tasks[task_id]['current_image_index'] < len(stream_tasks[task_id]['image_list']):
                status["current_image"] = stream_tasks[task_id]['image_list'][stream_tasks[task_id]['current_image_index']]
        
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error(f"获取任务状态API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/start', methods=['POST'])
def api_start_task(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        if task_id in stream_tasks and stream_tasks[task_id]['running']:
            return jsonify({"success": False, "message": "推流已经在运行中"})
        
        if start_stream_thread(task_id):
            return jsonify({"success": True, "message": "推流已开始"})
        else:
            return jsonify({"success": False, "message": "启动推流失败"})
    except Exception as e:
        logger.error(f"启动任务推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/stop', methods=['POST'])
def api_stop_task(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        if not stream_tasks.get(task_id, {}).get('running'):
            return jsonify({"success": False, "message": "推流已经停止"})
        
        if stop_stream(task_id):
            return jsonify({"success": True, "message": "推流已停止"})
        else:
            return jsonify({"success": False, "message": "停止推流失败"})
    except Exception as e:
        logger.error(f"停止任务推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/restart', methods=['POST'])
def api_restart_task(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        stop_stream(task_id)
        time.sleep(1)  # 给系统一点时间停止
        
        if start_stream_thread(task_id):
            return jsonify({"success": True, "message": "推流已重启"})
        else:
            return jsonify({"success": False, "message": "重启推流失败"})
    except Exception as e:
        logger.error(f"重启任务推流API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/next', methods=['POST'])
def api_next_image(task_id):
    try:
        if task_id not in stream_tasks:
            return jsonify({"success": False, "message": "任务未初始化"})
        
        image_list = get_task_image_list(task_id)
        if not image_list:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        stream_tasks[task_id]['current_image_index'] = (stream_tasks[task_id]['current_image_index'] + 1) % len(image_list)
        stream_tasks[task_id]['image_list'] = image_list
        
        logger.info(f"任务 {task_id} 切换到下一张图片: {image_list[stream_tasks[task_id]['current_image_index']]}")
        
        return jsonify({
            "success": True,
            "message": "已切换到下一张图片",
            "current_image": image_list[stream_tasks[task_id]['current_image_index']],
            "index": stream_tasks[task_id]['current_image_index']
        })
    except Exception as e:
        logger.error(f"切换到下一张图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/prev', methods=['POST'])
def api_prev_image(task_id):
    try:
        if task_id not in stream_tasks:
            return jsonify({"success": False, "message": "任务未初始化"})
        
        image_list = get_task_image_list(task_id)
        if not image_list:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        stream_tasks[task_id]['current_image_index'] = (stream_tasks[task_id]['current_image_index'] - 1) % len(image_list)
        stream_tasks[task_id]['image_list'] = image_list
        
        logger.info(f"任务 {task_id} 切换到上一张图片: {image_list[stream_tasks[task_id]['current_image_index']]}")
        
        return jsonify({
            "success": True,
            "message": "已切换到上一张图片",
            "current_image": image_list[stream_tasks[task_id]['current_image_index']],
            "index": stream_tasks[task_id]['current_image_index']
        })
    except Exception as e:
        logger.error(f"切换到上一张图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/goto', methods=['POST'])
def api_goto_image(task_id):
    try:
        if task_id not in stream_tasks:
            return jsonify({"success": False, "message": "任务未初始化"})
        
        image_list = get_task_image_list(task_id)
        if not image_list:
            return jsonify({"success": False, "message": "没有可用的图片"})
        
        data = request.get_json()
        if 'index' in data:
            index = int(data['index'])
            if 0 <= index < len(image_list):
                stream_tasks[task_id]['current_image_index'] = index
                stream_tasks[task_id]['image_list'] = image_list
                
                logger.info(f"任务 {task_id} 跳转到图片: {image_list[index]}")
                return jsonify({
                    "success": True,
                    "message": "已跳转到指定图片",
                    "current_image": image_list[index],
                    "index": index
                })
            else:
                return jsonify({"success": False, "message": "索引超出范围"})
        elif 'filename' in data:
            filename = data['filename']
            if filename in image_list:
                index = image_list.index(filename)
                stream_tasks[task_id]['current_image_index'] = index
                stream_tasks[task_id]['image_list'] = image_list
                
                logger.info(f"任务 {task_id} 跳转到图片: {filename}")
                return jsonify({
                    "success": True,
                    "message": "已跳转到指定图片",
                    "current_image": filename,
                    "index": index
                })
            else:
                return jsonify({"success": False, "message": "文件不存在"})
        else:
            return jsonify({"success": False, "message": "缺少index或filename参数"})
    except Exception as e:
        logger.error(f"跳转到指定图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/upload', methods=['POST'])
def api_upload_image(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        if 'file' not in request.files:
            return jsonify({"success": False, "message": "没有文件部分"})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "message": "没有选择文件"})
        
        if file and allowed_file(file.filename):
            # 保存图片到临时位置
            temp_filename = secure_filename(file.filename)
            temp_path = os.path.join(Config.UPLOAD_FOLDER, temp_filename)
            file.save(temp_path)
            
            try:
                # 检查图片尺寸是否符合任务要求
                image = cv2.imread(temp_path)
                if image is None:
                    os.remove(temp_path)
                    return jsonify({"success": False, "message": "无法读取上传的图片"})
                
                height, width = image.shape[:2]
                if width != task['width'] or height != task['height']:
                    os.remove(temp_path)
                    return jsonify({
                        "success": False, 
                        "message": f"图片尺寸必须为 {task['width']}x{task['height']}"
                    })
                
                # 将图片移动到任务目录
                task_image_path = os.path.join(task['images_dir'], temp_filename)
                # 如果文件名已存在，生成新文件名
                if os.path.exists(task_image_path):
                    base, ext = os.path.splitext(temp_filename)
                    temp_filename = f"{base}_{int(time.time())}{ext}"
                    task_image_path = os.path.join(task['images_dir'], temp_filename)
                
                os.rename(temp_path, task_image_path)
                
                # 更新任务的图片列表
                task_manager.add_image_to_task(task_id, temp_filename)
                
                # 更新内存中的图片列表
                if task_id in stream_tasks:
                    stream_tasks[task_id]['image_list'] = get_task_image_list(task_id)
                
                logger.info(f"向任务 {task_id} 上传图片成功: {temp_filename}")
                return jsonify({
                    "success": True,
                    "message": "图片上传成功",
                    "filename": temp_filename
                })
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                logger.error(f"处理上传图片时出错: {str(e)}")
                return jsonify({"success": False, "message": str(e)})
        else:
            return jsonify({"success": False, "message": "不支持的文件格式"})
    except Exception as e:
        logger.error(f"上传图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/list')
def api_get_task_images(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        image_list = get_task_image_list(task_id)
        current_index = stream_tasks[task_id]['current_image_index'] if task_id in stream_tasks else 0
        
        return jsonify({
            "success": True,
            "images": image_list,
            "current_index": current_index,
            "count": len(image_list)
        })
    except Exception as e:
        logger.error(f"获取任务图片列表API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/delete', methods=['POST'])
def api_delete_task(task_id):
    try:
        # 先停止推流
        stop_stream(task_id)
        
        # 删除任务
        if task_manager.delete_task(task_id):
            # 从内存中移除任务状态
            if task_id in stream_tasks:
                del stream_tasks[task_id]
            
            logger.info(f"任务 {task_id} 删除成功")
            return jsonify({"success": True, "message": "任务删除成功"})
        else:
            return jsonify({"success": False, "message": "任务删除失败"})
    except Exception as e:
        logger.error(f"删除任务API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task/<task_id>/delete_image', methods=['POST'])
def api_delete_task_image(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "message": "任务不存在"})
        
        data = request.get_json()
        filename = data.get('filename')
        if not filename:
            return jsonify({"success": False, "message": "缺少filename参数"})
        
        # 删除文件
        image_path = os.path.join(task['images_dir'], filename)
        if os.path.exists(image_path):
            # 检查图片列表长度
            image_list = get_task_image_list(task_id)
            if len(image_list) <= 1:
                return jsonify({"success": False, "message": "每个任务至少需要保留一张图片"})
            
            os.remove(image_path)
        
        # 从任务中移除图片
        if task_manager.remove_image_from_task(task_id, filename):
            # 更新内存中的图片列表
            if task_id in stream_tasks:
                stream_tasks[task_id]['image_list'] = get_task_image_list(task_id)
                # 如果删除的是当前显示的图片，切换到下一张
                if stream_tasks[task_id]['image_list'] and stream_tasks[task_id]['current_image_index'] >= len(stream_tasks[task_id]['image_list']):
                    stream_tasks[task_id]['current_image_index'] = 0
            
            logger.info(f"任务 {task_id} 删除图片成功: {filename}")
            return jsonify({"success": True, "message": "图片删除成功"})
        else:
            return jsonify({"success": False, "message": "图片删除失败，可能是最后一张图片"})
    except Exception as e:
        logger.error(f"删除图片API错误: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

# 提供任务图片的路由
@app.route('/api/task/<task_id>/image/<filename>')
def serve_task_image(task_id, filename):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return "任务不存在", 404
        
        # 安全检查文件名
        safe_filename = secure_filename(filename)
        if safe_filename != filename:
            return "文件名不合法", 400
        
        # 构建图片路径
        image_path = os.path.join(task['images_dir'], safe_filename)
        if not os.path.exists(image_path):
            return "图片不存在", 404
        
        # 返回图片文件
        return send_from_directory(os.path.dirname(image_path), safe_filename)
    except Exception as e:
        logger.error(f"提供任务图片失败: {str(e)}")
        return "提供图片失败", 500

# 应用主函数
if __name__ == '__main__':
    # 初始化目录
    init_directories()
    
    # 启动自动恢复功能
    auto_recovery()
    
    # 启动Flask应用
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=Config.PORT)