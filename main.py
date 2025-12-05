# main.py
import os
import sys
import shutil
import asyncio
import uuid
import re
import subprocess
import time
import json
import ast
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from openai import AsyncOpenAI 

# ================= 📦 导入配置和提示词 =================
from config import (
    API_KEY, BASE_URL, MODEL_NAME,
    STATIC_DIR, TEMPLATES_DIR, TEMP_DIR, 
    SCENE_FILE, HISTORY_FILE, CONVERSATION_FILE,
    MAX_RETRIES, MAX_HISTORY_ENTRIES,
    REQUEST_TIMEOUT, MANIM_TIMEOUT,
    DEFAULT_SCENE_NAME, DEFAULT_QUALITY
)

from prompts import (
    PROMPT_GENERATOR,
    PROMPT_ANALYZER,
    PROMPT_IMPROVER,
    PROMPT_INTENT_ANALYZER,
    PROMPT_EMERGENCY_FIXER,
    SYSTEM_PROMPTS,
    RESPONSE_TEMPLATES,
    MONITOR_HTML
)

# ================= 📝 缓存系统 (MD5指纹) =================
CACHE_FILE = os.path.join(TEMP_DIR, "cache.json")

def load_cache():
    """加载缓存文件"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache_entry(prompt, video_url):
    """保存缓存条目，使用MD5作为键"""
    cache = load_cache()
    # 使用 Prompt 的 MD5 作为键，避免特殊字符问题，确保唯一性
    key = hashlib.md5(prompt.strip().encode('utf-8')).hexdigest()
    cache[key] = video_url
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 缓存保存失败: {e}")

def get_cached_video(prompt):
    """尝试获取缓存的视频链接"""
    cache = load_cache()
    key = hashlib.md5(prompt.strip().encode('utf-8')).hexdigest()
    return cache.get(key)

# ================= 🔍 代码分析器 (静态AST) =================
def analyze_code_structure(code: str):
    """分析代码结构，提取重要信息（类名、方法、变量等）"""
    try:
        tree = ast.parse(code)
        analysis = {
            "scene_class": None,
            "methods": [],
            "variables": [],
            "animations": [],
            "has_axes": False,
            "objects": []
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 智能识别继承自 Scene 的类
                base_ids = [base.id for base in node.bases if hasattr(base, 'id')]
                # 只要继承链里有 Scene 相关的都算
                if any(b in ['Scene', 'ThreeDScene', 'MovingCameraScene', 'ZoomedScene', 'LinearTransformationScene'] for b in base_ids):
                    analysis["scene_class"] = node.name
            elif isinstance(node, ast.FunctionDef):
                analysis["methods"].append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        analysis["variables"].append(target.id)
            elif isinstance(node, ast.Call):
                if hasattr(node.func, 'attr'):
                    if node.func.attr in ['Create', 'Play', 'Transform', 'FadeIn', 'FadeOut', 'Rotate', 'Write']:
                        analysis["animations"].append(node.func.attr)
                if hasattr(node.func, 'id'):
                    if node.func.id in ['Axes', 'ThreeDAxes', 'NumberPlane']:
                        analysis["has_axes"] = True
        return analysis
    except:
        return {"error": "代码解析失败"}

def extract_objects_from_code(code: str):
    """静态提取已定义的图形对象（作为动态侦探的备份方案）"""
    objects = []
    # 匹配常见的Manim对象创建模式
    patterns = [
        r'(\w+)\s*=\s*(Circle|Square|Triangle|Rectangle|Line|Dot|Text|MathTex|VGroup|Axes|NumberPlane|Sphere|Cube)',
        r'self\.add\((\w+)\)',
        r'self\.play\([^)]*(\w+)[^)]*\)',
        r'def construct\(self\):[\s\S]*?(\w+)\s*='
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, code)
        for match in matches:
            if isinstance(match, tuple):
                obj_name = match[0] if match[0] else match[1]
            else:
                obj_name = match
            if obj_name and obj_name not in ['self', 'Scene', 'run_time', 'PI'] and obj_name not in objects:
                objects.append(obj_name)
    
    return objects

# ================= 🧹 自清洁启动逻辑 (持久化版) =================
def cleanup_workspace_startup():
    """系统启动时的清理：只清理临时文件，保留生成的视频"""
    print("-" * 50)
    print("🧹 [系统] 正在初始化环境 (保留历史视频)...")
    
    # 1. 清理临时文件夹 (temp_gen)，这是做饭的边角料，可以扔
    if os.path.exists(TEMP_DIR):
        try: 
            shutil.rmtree(TEMP_DIR)
        except: 
            pass
            
    # 2. 【关键】绝对不碰 STATIC_DIR 里的 .mp4 文件！
    # 这样您重启程序后，之前的视频依然存在
    
    # 3. 重建目录结构
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    
    print("✨ [系统] 状态：就绪。")
    print("-" * 50)

def hard_reset_system():
    """彻底重置：清理所有文件，包括视频和历史记录（核按钮）"""
    print("⚠️ [系统] 执行彻底重置...")
    
    # 1. 清理临时目录
    if os.path.exists(TEMP_DIR):
        try: shutil.rmtree(TEMP_DIR)
        except: pass
        
    # 2. 清理所有视频文件
    if os.path.exists(STATIC_DIR):
        for filename in os.listdir(STATIC_DIR):
            if filename.endswith(".mp4"):
                try: 
                    os.remove(os.path.join(STATIC_DIR, filename))
                except: 
                    pass
    
    # 3. 清理记忆文件
    for f in [HISTORY_FILE, CONVERSATION_FILE, SCENE_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass
            
    # 4. 重建目录
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时只执行轻量清理，保护视频
    cleanup_workspace_startup()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

client = AsyncOpenAI(
    api_key=API_KEY, 
    base_url=BASE_URL, 
    timeout=REQUEST_TIMEOUT
)

# ================= 📝 智能上下文管理器 =================
class SmartContextManager:
    """智能上下文管理器，深度理解代码结构"""
    
    def __init__(self):
        self.conversation_path = CONVERSATION_FILE
        self.history_path = HISTORY_FILE
        self.scene_path = SCENE_FILE
        self.max_history_entries = MAX_HISTORY_ENTRIES
        
    def save_conversation(self, user_prompt: str, response_data: dict, code_analysis: dict = None):
        """保存对话记录，包含代码分析"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_prompt,
            "generator_draft": response_data.get("generator_draft", ""),
            "analyzer_critique": response_data.get("analyzer_critique", ""),
            "final_code": response_data.get("final_code", ""),
            "success": response_data.get("success", False),
            "video_url": response_data.get("video_url", ""),
            "code_analysis": code_analysis or {},
            "intent_analysis": response_data.get("intent_analysis", "")
        }
        
        conversation = self.load_conversation()
        conversation.append(entry)
        
        if len(conversation) > self.max_history_entries:
            conversation = conversation[-self.max_history_entries:]
            
        with open(self.conversation_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, ensure_ascii=False, indent=2)
    
    def load_conversation(self):
        if not os.path.exists(self.conversation_path):
            return []
        try:
            with open(self.conversation_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    
    def get_context_summary(self):
        """生成智能上下文摘要"""
        conversation = self.load_conversation()
        if not conversation:
            return {"text": "无历史对话", "objects": [], "current_style": "无"}
        
        recent = conversation[-3:] if len(conversation) >= 3 else conversation
        
        objects = []
        styles = []
        intents = []
        
        for entry in recent:
            if entry.get("code_analysis"):
                objs = entry.get("code_analysis", {}).get("objects", [])
                objects.extend(objs)
            
            if entry.get("user"):
                user_text = entry["user"].lower()
                if "添加" in user_text or "再加" in user_text:
                    intents.append("添加")
                elif "修改" in user_text or "改变" in user_text:
                    intents.append("修改")
                elif "新建" in user_text or "创建" in user_text:
                    intents.append("新建")
            
            if entry.get("code_analysis", {}).get("has_axes"):
                styles.append("使用坐标轴")
        
        # 去重
        objects = list(set(objects))
        styles = list(set(styles))
        intents = list(set(intents))
        
        summary = f"最近{len(recent)}次交互中："
        if objects:
            summary += f"\n- 已创建对象：{', '.join(objects[:5])}"
        if styles:
            summary += f"\n- 当前风格：{', '.join(styles)}"
        
        return {
            "text": summary,
            "objects": objects,
            "current_style": styles[0] if styles else "无特定风格"
        }
    
    def analyze_current_code(self):
        """分析当前代码状态"""
        if not os.path.exists(self.scene_path):
            return {"status": "no_code", "objects": [], "has_axes": False}
        
        try:
            with open(self.scene_path, "r", encoding="utf-8") as f:
                code = f.read()
            
            analysis = analyze_code_structure(code)
            objects = extract_objects_from_code(code)
            
            return {
                "status": "has_code",
                "code_preview": code[:500] + "..." if len(code) > 500 else code,
                "analysis": analysis,
                "objects": objects,
                "object_count": len(objects),
                "has_axes": analysis.get("has_axes", False)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

context_manager = SmartContextManager()

def extract_code_from_markdown(text):
    """从文本中提取代码块"""
    patterns = [
        r"```python(.*?)```",
        r"```(.*?)```",
        r"<code>(.*?)</code>"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            code = re.sub(r'^python\s*', '', code, flags=re.IGNORECASE)
            return code
    
    return text.strip().replace("```", "")

def extract_json_from_response(text):
    """从响应中提取JSON"""
    try:
        json_pattern = r'\{[\s\S]*\}'
        match = re.search(json_pattern, text)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None

def run_manim_safe(cmd):
    """安全运行Manim命令"""
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            encoding='utf-8',
            errors='ignore',
            timeout=MANIM_TIMEOUT
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "渲染超时"
    except Exception as e:
        return -1, "", str(e)

async def find_video_file(search_dir, filename_prefix):
    """查找视频文件"""
    for root, dirs, files in os.walk(search_dir):
        for file in files:
            if file.endswith(".mp4") and filename_prefix in file:
                return os.path.join(root, file)
    return None

# ================= 🚀 核心工作流逻辑 (完整4步 + WebSocket + 侦探) =================
async def process_chat_workflow(prompt: str, websocket: WebSocket):
    """处理核心业务逻辑，通过 WebSocket 发送实时进度"""
    request_id = str(uuid.uuid4())[:8]
    output_filename = f"video_{request_id}"
    
    # 辅助函数：发送进度
    async def send_status(step, message):
        print(f"[{request_id}] {message}")
        if websocket:
            await websocket.send_json({
                "type": "progress",
                "step": step,
                "message": message
            })

    await send_status("init", f"收到指令: {prompt}")
    
    try:
        # =======================================================
        # 🔍 第0步：分析当前状态和用户意图
        # =======================================================
        current_state = context_manager.analyze_current_code()
        context_summary = context_manager.get_context_summary()
        
        await send_status("intent", "正在分析您的意图...")
        intent_analysis = None
        try:
            intent_response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": PROMPT_INTENT_ANALYZER},
                    {"role": "user", "content": f"""
用户指令: {prompt}
当前状态: {json.dumps(current_state, ensure_ascii=False)}
上下文摘要: {context_summary['text']}

请分析用户的真实意图。
"""}
                ],
                stream=False,
                temperature=0.1
            )
            intent_analysis = extract_json_from_response(intent_response.choices[0].message.content)
            print(f"[{request_id}] 🎯 意图分析: {intent_analysis}")
        except Exception as e:
            print(f"[{request_id}] ⚠️ 意图分析失败: {e}")
        
        # =======================================================
        # 🎨 第一步：生成器 - 上下文感知初稿
        # =======================================================
        await send_status("generator", "正在构思动画代码...")
        start_time = time.time()
        
        generator_input = f"""
【用户指令】:
{prompt}

【意图分析】:
{json.dumps(intent_analysis, ensure_ascii=False) if intent_analysis else "未分析"}

【当前代码状态】:
{current_state.get('code_preview', '无现有代码')}

【已存在的对象】:
{', '.join(current_state.get('objects', [])) if current_state.get('objects') else '无'}

【上下文摘要】:
{context_summary['text']}

【具体要求】:
1. 保持代码清晰，**必须在文件开头包含 import math 和 import numpy as np**
2. **严禁在 MathTex 中使用中文**，中文必须用 Text() 类
3. 如果是修改或添加，请基于当前代码进行；如果是新建，可以完全重写
4. 确保所有内容都在屏幕内
"""
        
        gen_response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": PROMPT_GENERATOR},
                {"role": "user", "content": generator_input}
            ],
            stream=False,
            temperature=0.7
        )
        
        draft_code = extract_code_from_markdown(gen_response.choices[0].message.content)
        gen_time = time.time() - start_time
        
        # =======================================================
        # ⚖️ 第二步：分析器 - 上下文感知质检
        # =======================================================
        await send_status("analyzer", "正在检查代码质量...")
        ana_start = time.time()
        
        analyzer_input = f"""
【用户指令】: {prompt}
【生成器初稿】: {draft_code}
请检查布局、遮挡和 MathTex 中文问题。
"""
        
        ana_response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": PROMPT_ANALYZER},
                {"role": "user", "content": analyzer_input}
            ],
            stream=False,
            temperature=0.1
        )
        
        critique = ana_response.choices[0].message.content
        ana_time = time.time() - ana_start
        
        # =======================================================
        # 🔧 第三步：改进器 - 智能优化
        # =======================================================
        await send_status("improver", "正在优化代码细节...")
        imp_start = time.time()
        
        improver_input = f"""
【用户指令】: {prompt}
【初稿】: {draft_code}
【质检报告】: {critique}
请修复所有问题，特别是 MathTex 中文和 import math。
"""
        
        imp_response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": PROMPT_IMPROVER},
                {"role": "user", "content": improver_input}
            ],
            stream=False,
            temperature=0.3
        )
        
        final_code = extract_code_from_markdown(imp_response.choices[0].message.content)
        imp_time = time.time() - imp_start
        
        # =======================================================
        # 🎬 第四步：渲染执行 (并发隔离 + 动态侦探)
        # =======================================================
        await send_status("render", "正在渲染视频 (可能需要几分钟)...")
        
        # 3.1 动态代码分析 (Scene Name Detection)
        code_analysis = analyze_code_structure(final_code)
        scene_name = code_analysis.get("scene_class") or DEFAULT_SCENE_NAME
        
        video_url = None
        error_details = None
        final_objects = []
        
        # 1. 创建本次请求的专属临时目录 (并发隔离)
        request_dir = os.path.join(TEMP_DIR, f"req_{request_id}")
        os.makedirs(request_dir, exist_ok=True)
        
        # 2. 专属场景文件路径
        local_scene_file = os.path.join(request_dir, "current_scene.py")
        dump_file = os.path.join(request_dir, "objects_dump.json").replace("\\", "/")
        
        # 🔥【关键】注入 Inspector 代码 (侦探) 🔥
        # 这是一个继承自用户 Scene 的子类，专门用于在 tear_down 时窃取对象列表
        inspector_class_name = f"Inspector_{request_id}"
        inspector_code = f"""
import json
class {inspector_class_name}({scene_name}):
    def tear_down(self):
        try:
            detected_objects = []
            # 1. 扫描属性 (self.xxx)
            for name, value in self.__dict__.items():
                if isinstance(value, Mobject):
                    detected_objects.append(name)
            # 2. 扫描屏幕上的对象 (self.mobjects)
            for mobj in self.mobjects:
                name = mobj.__class__.__name__
                if name not in detected_objects:
                    detected_objects.append(name)
            
            # 将检测到的对象写入临时文件
            with open(r"{dump_file}", "w", encoding="utf-8") as f:
                json.dump(list(set(detected_objects)), f, ensure_ascii=False)
        except Exception as e:
            print(f"Inspector Error: {{e}}")
        finally:
            super().tear_down()
"""

        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                await send_status("render", f"渲染出错，正在第 {attempt} 次自动修复...")
            
            # 写入带侦探的代码 (源代码 + 侦探代码)
            with open(local_scene_file, "w", encoding="utf-8") as f:
                f.write(final_code + "\n" + inspector_code)
            
            # 运行 Manim (运行的是 Inspector 类，而不是原类)
            cmd = [
                sys.executable, "-m", "manim",
                DEFAULT_QUALITY,
                "--media_dir", request_dir,
                "-o", output_filename,
                local_scene_file,
                inspector_class_name # <--- 运行侦探
            ]
            
            returncode, stdout, stderr = await asyncio.to_thread(run_manim_safe, cmd)
            
            if returncode == 0:
                # 5. 查找视频
                video_path = await find_video_file(request_dir, output_filename)
                
                if video_path:
                    target_name = f"{output_filename}.mp4"
                    target_path = os.path.join(STATIC_DIR, target_name)
                    
                    shutil.move(video_path, target_path)
                    video_url = f"/static/{target_name}"
                    
                    # 🔥 读取侦探的报告 (100% 准确的运行时数据)
                    try:
                        if os.path.exists(dump_file):
                            with open(dump_file, "r", encoding="utf-8") as f:
                                final_objects = json.load(f)
                            print(f"[{request_id}] 🕵️ 侦探报告: {final_objects}")
                        else:
                            # 如果侦探失败，降级为静态正则分析
                            print(f"[{request_id}] ⚠️ 侦探未生成报告，降级为静态分析")
                            final_objects = extract_objects_from_code(final_code)
                    except:
                        final_objects = extract_objects_from_code(final_code)

                    print(f"[{request_id}] 🎉 渲染成功!")
                    
                    # 成功后更新全局状态
                    try:
                        with open(SCENE_FILE, "w", encoding="utf-8") as f:
                            f.write(final_code)
                    except Exception as e:
                        print(f"[{request_id}] ⚠️ 全局状态更新警告: {e}")
                        
                    break
            else:
                error_details = stderr[-500:] if stderr else "未知错误"
                print(f"[{request_id}] ❌ 渲染失败: {error_details[:100]}...")
                
                if attempt < MAX_RETRIES:
                    fixer_prompt = PROMPT_EMERGENCY_FIXER.format(
                        error_details=error_details,
                        final_code=final_code
                    )
                    
                    fix_response = await client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPTS["code_fixer"]},
                            {"role": "user", "content": fixer_prompt}
                        ],
                        stream=False
                    )
                    
                    final_code = extract_code_from_markdown(fix_response.choices[0].message.content)

        # 任务结束，清理临时目录
        try:
            shutil.rmtree(request_dir, ignore_errors=True)
            print(f"[{request_id}] 🧹 临时工作区已清理")
        except:
            pass
        
        # =======================================================
        # 💾 第五步：保存结果与缓存
        # =======================================================
        total_time = time.time() - start_time
        
        response_data = {
            "generator_draft": draft_code[:500] + "..." if len(draft_code) > 500 else draft_code,
            "analyzer_critique": critique,
            "final_code": final_code,
            "success": bool(video_url),
            "video_url": video_url,
            "intent_analysis": intent_analysis,
            "timing": {
                "generator": gen_time,
                "analyzer": ana_time,
                "improver": imp_time,
                "total": total_time
            }
        }
        
        # 这里保存的是侦探抓取到的真实对象列表
        context_manager.save_conversation(prompt, response_data, {
            **code_analysis,
            "objects": final_objects # <--- 真实数据
        })
        
        if video_url:
            # 存入缓存
            save_cache_entry(prompt, video_url)
            
            if websocket:
                await websocket.send_json({
                    "type": "result",
                    "status": "success",
                    "video": video_url,
                    "code": final_code,
                    "timing": response_data["timing"]
                })
        else:
            if websocket:
                await websocket.send_json({
                    "type": "error",
                    "message": "渲染失败",
                    "details": error_details
                })
            
    except Exception as e:
        print(f"[{request_id}] 💥 系统异常: {str(e)}")
        if websocket:
            await websocket.send_json({
                "type": "error",
                "message": f"系统异常: {str(e)}"
            })

# ================= 🔌 WebSocket 接口 =================
@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔌 新的 WebSocket 连接建立")
    
    try:
        while True:
            data = await websocket.receive_json()
            prompt = data.get("prompt")
            
            if not prompt:
                continue

            print(f"\n{'='*60}")
            print(f"⚡ WS 收到指令: {prompt}")
            print(f"{'='*60}")

            # 1. 检查缓存
            cached_video = get_cached_video(prompt)
            if cached_video:
                print(f"✨ 命中缓存: {prompt}")
                await websocket.send_json({
                    "type": "progress",
                    "step": "cache",
                    "message": "发现相同灵感，正在调取记忆..."
                })
                # 稍微停顿展示一下缓存命中效果
                await asyncio.sleep(0.5)
                
                await websocket.send_json({
                    "type": "result",
                    "status": "success",
                    "video": cached_video,
                    "code": "（缓存内容）",
                    "cached": True
                })
                continue

            # 2. 无缓存，开始完整工作流
            await process_chat_workflow(prompt, websocket)
            
    except WebSocketDisconnect:
        print("🔌 客户端断开连接")
    except Exception as e:
        print(f"❌ WS异常: {e}")

# ================= 🌐 静态页面路由 =================
@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/context")
async def get_context():
    """获取完整上下文信息"""
    conversation = context_manager.load_conversation()
    current_state = context_manager.analyze_current_code()
    context_summary = context_manager.get_context_summary()
    
    return {
        "conversation_summary": context_summary,
        "current_state": current_state,
        "recent_conversations": conversation[-5:] if len(conversation) > 5 else conversation
    }

@app.get("/api/debug")
async def debug_info():
    """调试信息接口"""
    return {
        "system": {
            "python_version": sys.version,
            "platform": sys.platform,
            "temp_dir_exists": os.path.exists(TEMP_DIR),
            "scene_file_exists": os.path.exists(SCENE_FILE)
        },
        "context": context_manager.get_context_summary()
    }

@app.post("/api/reset")
async def reset_system():
    """重置系统：这是'核按钮'，彻底删除所有数据"""
    hard_reset_system()
    return {"message": "系统已彻底重置"}

@app.get("/api/code/current")
async def get_current_code():
    """获取当前代码"""
    if os.path.exists(SCENE_FILE):
        with open(SCENE_FILE, "r", encoding="utf-8") as f:
            return {"code": f.read()}
    return {"code": "无当前代码"}

# ================= 📊 智能监控面板 =================
@app.get("/monitor", response_class=HTMLResponse)
async def smart_monitor():
    """智能监控面板"""
    return HTMLResponse(content=MONITOR_HTML)

if __name__ == "__main__":
    import uvicorn
    print("="*60)
    print("✨ MathSpace 智能上下文感知系统已启动 (增强版)")
    print("🌐 前端地址: http://localhost:8000")
    print("🔌 WebSocket: ws://localhost:8000/ws/chat")
    print("📊 智能监控: http://localhost:8000/monitor")
    print("="*60)
    print("🤖 系统特色:")
    print("  1. 全流程流式反馈 (WebSocket)")
    print("  2. 智能指令缓存 (MD5 Cache)")
    print("  3. 渲染环境隔离 (Concurrency)")
    print("  4. 运行时对象侦探 (Runtime Inspector)")
    print("="*60)
    
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)