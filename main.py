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
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
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

# ================= 📝 Pydantic 模型 =================
class UserRequest(BaseModel):
    prompt: str

# ================= 🔍 代码分析器 =================
def analyze_code_structure(code: str):
    """分析代码结构，提取重要信息"""
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
                if "Scene" in [base.id for base in node.bases if hasattr(base, 'id')]:
                    analysis["scene_class"] = node.name
            elif isinstance(node, ast.FunctionDef):
                analysis["methods"].append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        analysis["variables"].append(target.id)
            elif isinstance(node, ast.Call):
                if hasattr(node.func, 'attr'):
                    if node.func.attr in ['Create', 'Play', 'Transform', 'FadeIn', 'FadeOut', 'Rotate']:
                        analysis["animations"].append(node.func.attr)
                if hasattr(node.func, 'id'):
                    if node.func.id == 'Axes':
                        analysis["has_axes"] = True
        
        return analysis
    except:
        return {"error": "代码解析失败"}

def extract_objects_from_code(code: str):
    """从代码中提取已定义的图形对象"""
    objects = []
    
    # 匹配常见的Manim对象创建模式
    patterns = [
        r'(\w+)\s*=\s*(Circle|Square|Triangle|Rectangle|Line|Dot|Text|MathTex)',
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
            if obj_name and obj_name not in ['self', 'Scene'] and obj_name not in objects:
                objects.append(obj_name)
    
    return objects

# ================= 🧹 自清洁启动 =================
def cleanup_workspace():
    print("-" * 50)
    print("🧹 [系统] 正在初始化链式工作流环境...")
    if os.path.exists(TEMP_DIR):
        try: 
            shutil.rmtree(TEMP_DIR)
        except: 
            pass
    if os.path.exists(STATIC_DIR):
        for filename in os.listdir(STATIC_DIR):
            if filename.endswith(".mp4"):
                try: 
                    os.remove(os.path.join(STATIC_DIR, filename))
                except: 
                    pass
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    print("✨ [系统] 状态：就绪。")
    print("-" * 50)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_workspace()
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
        
        objects = list(set(objects))
        styles = list(set(styles))
        intents = list(set(intents))
        
        summary = f"最近{len(recent)}次交互中："
        if objects:
            summary += f"\n- 已创建对象：{', '.join(objects[:5])}{'等' if len(objects) > 5 else ''}"
        if styles:
            summary += f"\n- 当前风格：{', '.join(styles)}"
        if intents:
            summary += f"\n- 用户意图倾向：{', '.join(intents)}"
        
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

@app.post("/api/chat")
async def chat_endpoint(request: UserRequest):
    """链式工作流主处理函数"""
    request_id = str(uuid.uuid4())[:8]
    scene_name = DEFAULT_SCENE_NAME
    output_filename = f"video_{request_id}"
    
    print(f"\n{'='*60}")
    print(f"[{request_id}] 🧠 用户指令: {request.prompt}")
    print(f"{'='*60}")
    
    try:
        # =======================================================
        # 🔍 第0步：分析当前状态和用户意图
        # =======================================================
        print(f"[{request_id}] 🔍 分析当前状态和用户意图...")
        
        current_state = context_manager.analyze_current_code()
        context_summary = context_manager.get_context_summary()
        
        intent_analysis = None
        try:
            intent_response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": PROMPT_INTENT_ANALYZER},
                    {"role": "user", "content": f"""
用户指令: {request.prompt}
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
        print(f"[{request_id}] 🎨 生成器正在创作初稿...")
        start_time = time.time()
        
        current_code = ""
        if os.path.exists(SCENE_FILE):
            with open(SCENE_FILE, "r", encoding="utf-8") as f:
                current_code = f.read()
        
        generator_input = f"""
【用户指令】:
{request.prompt}

【意图分析】:
{json.dumps(intent_analysis, ensure_ascii=False) if intent_analysis else "未分析"}

【当前代码状态】:
{current_state.get('code_preview', '无现有代码')}

【已存在的对象】:
{', '.join(current_state.get('objects', [])) if current_state.get('objects') else '无'}

【上下文摘要】:
{context_summary['text']}

【具体要求】:
1. 如果是修改或添加，请基于当前代码进行
2. 如果是新建，可以完全重写
3. 保持代码清晰和可读性
4. **特别注意布局规划**：确保所有内容都在屏幕内
5. 使用合适的转场动画管理复杂场景
6. **文字与图形分层**：文字标签必须与图形对象分开显示，避免重叠遮挡
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
        print(f"[{request_id}] 📝 初稿生成完成 ({gen_time:.2f}s)")
        
        # =======================================================
        # ⚖️ 第二步：分析器 - 上下文感知质检
        # =======================================================
        print(f"[{request_id}] ⚖️ 分析器正在进行质检...")
        ana_start = time.time()
        
        analyzer_input = f"""
【用户指令】:
{request.prompt}

【意图分析】:
{json.dumps(intent_analysis, ensure_ascii=False) if intent_analysis else "未分析"}

【当前代码状态】:
{current_state.get('code_preview', '无现有代码')}

【已存在的对象】:
{', '.join(current_state.get('objects', [])) if current_state.get('objects') else '无'}

【生成器初稿】:
{draft_code}

请特别注意检查：
1. 布局是否合理？所有对象是否在屏幕内？
2. **文字与图形是否分层显示？文字是否遮挡图形？**
3. 转场动画是否合适？
4. 代码是否实现了用户意图？

请进行严格的上下文感知质检。
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
        
        rating = "UNKNOWN"
        rating_match = re.search(r'\[总体评级\]\s*(PASS|WARN|FAIL)', critique, re.IGNORECASE)
        if rating_match:
            rating = rating_match.group(1).upper()
        
        print(f"[{request_id}] 📋 质检评级: {rating} ({ana_time:.2f}s)")
        
        # =======================================================
        # 🔧 第三步：改进器 - 智能优化
        # =======================================================
        print(f"[{request_id}] 🔧 改进器正在优化代码...")
        imp_start = time.time()
        
        improver_input = f"""
【用户指令】:
{request.prompt}

【意图分析】:
{json.dumps(intent_analysis, ensure_ascii=False) if intent_analysis else "未分析"}

【当前代码状态】:
{current_state.get('code_preview', '无现有代码')}

【生成器初稿】:
{draft_code}

【分析器报告】:
{critique}

【评级】:
{rating}

请特别注意：
1. 修复布局和边界问题
2. **修复文字与图形的重叠问题，确保文字分层显示**
3. 优化转场动画
4. 确保所有对象在屏幕内

请生成最终的优化代码。
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
        print(f"[{request_id}] ✨ 最终代码生成完成 ({imp_time:.2f}s)")
        
        # =======================================================
        # 🎬 第四步：渲染执行
        # =======================================================
        print(f"[{request_id}] 🎬 开始渲染...")
        
        code_analysis = analyze_code_structure(final_code)
        final_objects = extract_objects_from_code(final_code)
        
        video_url = None
        error_details = None
        
        for attempt in range(MAX_RETRIES + 1):
            attempt_num = attempt + 1
            print(f"[{request_id}] 🎬 渲染尝试 {attempt_num}/{MAX_RETRIES+1}...")
            
            with open(SCENE_FILE, "w", encoding="utf-8") as f:
                f.write(final_code)
            
            cmd = [
                sys.executable, "-m", "manim",
                DEFAULT_QUALITY,
                "--media_dir", TEMP_DIR,
                "-o", output_filename,
                SCENE_FILE, scene_name
            ]
            
            returncode, stdout, stderr = await asyncio.to_thread(run_manim_safe, cmd)
            
            if returncode == 0:
                video_path = await find_video_file(TEMP_DIR, output_filename)
                if video_path:
                    target_name = f"{output_filename}.mp4"
                    target_path = os.path.join(STATIC_DIR, target_name)
                    
                    shutil.move(video_path, target_path)
                    video_url = f"/static/{target_name}"
                    
                    print(f"[{request_id}] 🎉 渲染成功!")
                    break
            else:
                error_details = stderr[-500:] if stderr else "未知错误"
                print(f"[{request_id}] ❌ 渲染失败: {error_details[:100]}...")
                
                if attempt < MAX_RETRIES:
                    print(f"[{request_id}] 🚑 启动紧急修复...")
                    
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
                    print(f"[{request_id}] 🔨 修复完成，准备重试...")
        
        # =======================================================
        # 💾 第五步：保存上下文和结果
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
        
        context_manager.save_conversation(request.prompt, response_data, {
            **code_analysis,
            "objects": final_objects
        })
        
        if video_url:
            print(f"[{request_id}] ✅ 任务完成！总耗时: {total_time:.2f}s")
            
            return {
                "status": "success",
                "video": video_url,
                "code": final_code,
                "analysis": critique,
                "intent": intent_analysis,
                "objects": final_objects,
                "timing": response_data["timing"]
            }
        else:
            print(f"[{request_id}] ❌ 最终失败")
            
            return JSONResponse(
                status_code=500,
                content={
                    "error": "渲染失败",
                    "details": error_details,
                    "analysis": critique,
                    "intent": intent_analysis
                }
            )
            
    except Exception as e:
        print(f"[{request_id}] 💥 系统异常: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"系统异常: {str(e)}"}
        )

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
    """重置系统"""
    cleanup_workspace()
    return {"message": "系统已重置"}

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
    print("✨ MathSpace 智能上下文感知系统已启动")
    print("🌐 前端地址: http://localhost:8000")
    print("📊 智能监控: http://localhost:8000/monitor")
    print("="*60)
    print("🤖 系统特色:")
    print("  1. 智能意图分析 (CREATE/MODIFY/ADD/ENHANCE)")
    print("  2. 深度代码结构解析")
    print("  3. 上下文感知生成器")
    print("  4. 实时对象追踪")
    print("  5. 专业场景管理与布局策略")
    print("  6. 文字分层显示规范（文字不遮挡图形）")
    print("="*60)
    
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)