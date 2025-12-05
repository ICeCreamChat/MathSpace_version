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

# ================= ⚡ 配置区 =================
API_KEY = "sk-80fd74758c144a61b2dae7a23195614c" 
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

# ================= 📂 路径配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TEMP_DIR = os.path.join(BASE_DIR, "temp_gen") 
SCENE_FILE = os.path.join(TEMP_DIR, "current_scene.py") 
HISTORY_FILE = os.path.join(TEMP_DIR, "context_history.txt")
CONVERSATION_FILE = os.path.join(TEMP_DIR, "conversation.json")

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

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120.0)

# ================= 📝 智能上下文管理器 =================
class SmartContextManager:
    """智能上下文管理器，深度理解代码结构"""
    
    def __init__(self):
        self.conversation_path = CONVERSATION_FILE
        self.history_path = HISTORY_FILE
        self.scene_path = SCENE_FILE
        self.max_history_entries = 15
        
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

# ================= 🧠 角色 1: 增强版上下文感知生成器 =================
PROMPT_GENERATOR = """
你是一个拥有深度上下文感知能力的 Manim 动画师。

【当前系统状态】
- 你在一个"生成-分析-改进"的链式工作流中
- 你的输出将传递给分析器进行严格质检
- 最终由改进器生成可执行的代码

【上下文感知任务】
你必须深度分析以下信息：
1. 用户的新指令是什么？
2. 当前代码中已经有什么对象？
3. 用户是在引用已有对象，还是创建新对象？
4. 这是连续创作还是全新开始？

【意图识别指南】
根据用户指令识别意图类型：
- 新建 (CREATE)：用户要求完全重新开始，不涉及现有对象
- 修改 (MODIFY)：用户要改变已有对象的属性（颜色、大小、位置）
- 添加 (ADD)：用户在现有场景中添加新元素
- 增强 (ENHANCE)：用户要求添加动画效果或美化现有场景

【坐标轴策略】
- 函数绘制、数据可视化 → 使用 Axes
- 纯几何图形、抽象概念 → 通常不用 Axes
- 三角函数、周期函数 → 考虑使用 PI 刻度
- 如果是修改场景 → 保持原有的坐标轴设置

【场景管理与布局策略】
重要：在Manim中，所有内容都在同一个视频帧中呈现，需要合理规划布局和动画序列。

1. **空间规划**：
   - 评估现有场景中的对象数量和大小
   - 如果对象过多或过大，考虑使用以下策略：
     * 按时间顺序分步显示（先显示A，后显示B）
     * 使用分组（`VGroup`, `HGroup`）并整齐排列
     * 使用缩放（`scale`）或调整位置（`shift`, `to_edge`）

2. **转场动画设计**：
   - 当需要清理空间展示新内容时，使用优雅的转场动画：
     * 逐渐淡出旧内容：`FadeOut`, `Uncreate`
     * 同时进行淡出/淡入：`ReplacementTransform`, `Transform`
   
   - 常见转场模式：
     * "清屏并重新开始" → 使用 `self.play(FadeOut(*all_objects))`
     * "逐步替换" → 使用 `ReplacementTransform(old_obj, new_obj)`
     * "分组展示" → 将相关内容分组，按组显示/隐藏

3. **边界检查与布局优化**：
   - **所有对象的边缘必须在屏幕内**
   - 如果对象超出边界，使用以下方法：
     * 缩放：`obj.scale_to_fit_width(8)`  # 屏幕宽度约14，安全宽度8
     * 移动：`obj.to_edge(UP/BOTTOM/LEFT/RIGHT)`
     * 重排：使用 `VGroup(*objects).arrange(DOWN, buff=0.5)`

4. **多步骤动画序列**：
   - 将复杂的展示分解为多个步骤
   - 每个步骤之间有清晰的转场
   - 示例结构：
     ```
     # 步骤1: 展示A组内容
     self.play(FadeIn(group_a))
     self.wait(1)
     
     # 转场: 淡出A，展示B
     self.play(FadeOut(group_a), FadeIn(group_b))
     self.wait(1)
     ```

【输出要求】
请生成 Manim 代码初稿，注意：
1. 如果是修改/添加，请基于提供的代码进行修改
2. 如果是新建，可以完全重写
3. 确保代码结构清晰，包含必要的导入
4. 使用 Manim CE v0.18.0 的 API
5. **特别注意布局规划**：确保所有内容都在屏幕内，并有合理的动画序列
6. **文字布局规范**：文字标签必须与图形对象分层显示，避免任何重叠
   - 使用 `text.next_to(graphic, direction, buff=0.3)` 将文字放在图形旁边
   - 使用 `text.to_edge(UP/DOWN/LEFT/RIGHT)` 将文字放在屏幕边缘
   - 确保所有文字都在纯色背景上清晰可见，不被图形遮挡

只输出 Python 代码块。
"""

# ================= ⚖️ 角色 2: 增强版分析器 =================
PROMPT_ANALYZER = """
你是一个严格的上下文感知质检员，负责检查代码的质量和一致性。

【质检维度】
1. **意图匹配度** (40%)
   - 代码是否准确实现了用户要求？
   - 如果是修改请求，是否修改了正确的对象？
   - 如果是添加请求，新元素是否与现有场景协调？

2. **布局与边界检查** (30%)
   - 所有对象是否都在屏幕边界内？
   - 布局是否合理？元素是否重叠？
   - 如果对象过多，是否使用了合适的转场动画？
   - **文字与图形是否分层显示**：文字是否清晰可读且不遮挡图形？

3. **动画与转场质量** (20%)
   - 转场动画是否流畅自然？
   - 动画序列是否有逻辑？
   - 是否有不必要的复杂动画？

4. **代码规范** (10%)
   - 是否使用正确的 Manim API？
   - 代码结构是否清晰？
   - 是否有明显的语法或逻辑错误？

【输出格式】
[总体评级] PASS / WARN / FAIL
[详细说明]
1. 意图匹配: (说明)
2. 布局问题: (特别检查文字与图形的重叠问题)
3. 动画质量: (说明)
4. 具体建议: (列出具体改进建议，特别是文字布局问题)

如果评级为 PASS，请说明为什么通过。
"""

# ================= 🔧 角色 3: 智能改进器 =================
PROMPT_IMPROVER = """
你是一个智能的 Manim 代码改进工程师。

【输入信息】
1. 用户原始指令
2. 生成器的初稿代码
3. 分析器的质检报告
4. 当前上下文状态

【改进策略】
根据分析器的报告，采用以下策略：

1. **PASS 评级** → 优化润色
   - 改进变量命名
   - 添加注释说明
   - 微调动画参数
   - 优化代码结构

2. **WARN 评级** → 针对性修复
   - 修复布局和边界问题
   - **特别注意修复文字与图形的重叠问题**
   - 优化转场动画
   - 保持代码的核心逻辑
   - 确保上下文一致性

3. **FAIL 评级** → 重新设计
   - 基于用户意图重新实现
   - 保留初稿中的合理部分
   - 确保与现有上下文协调
   - 特别注意布局规划，包括文字分层显示

【关键要求】
- 确保导入语句完整：from manim import *
- 类定义正确：class MathScene(Scene):
- 如果是修改场景，正确处理现有对象
- 添加适当的动画效果
- **确保所有对象都在屏幕边界内**
- **确保文字与图形分层显示，不相互遮挡**
- 使用合适的转场动画管理复杂场景

只输出最终的 Python 代码块。
"""

# ================= 🔄 新增：意图分析器 =================
PROMPT_INTENT_ANALYZER = """
你是一个专业的意图分析专家。
请分析用户指令，识别其真实意图和上下文关系。

【分析维度】
1. **意图分类**
   - 新建 (CREATE)：开始全新的场景
   - 修改 (MODIFY)：改变已有对象的属性
   - 添加 (ADD)：在现有场景中添加新元素
   - 增强 (ENHANCE)：添加动画效果或美化
   - 组合 (COMPOSE)：多个对象的交互

2. **对象引用**
   - 用户是否在引用之前创建的对象？
   - 有哪些关键词表明对象引用？（如"那个"、"刚才的"、"之前的"）

3. **布局需求**
   - 用户是否暗示了布局要求？（如"在左边"、"分成两排"）
   - 是否需要特殊的转场效果？

4. **具体要求**
   - 用户明确要求了什么？
   - 有哪些隐含的需求？

【输出格式】
请以 JSON 格式输出分析结果：
{
  "intent": "CREATE|MODIFY|ADD|ENHANCE|COMPOSE",
  "target_objects": ["对象1", "对象2"],
  "context_relation": "独立|连续",
  "layout_hints": ["布局提示1", "布局提示2"],
  "explicit_requirements": ["明确要求1", "明确要求2"],
  "implicit_needs": ["隐含需求1", "隐含需求2"],
  "confidence": 0.9
}
"""

class UserRequest(BaseModel):
    prompt: str

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
            timeout=300
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
    scene_name = "MathScene"
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
        
        max_retries = 2
        video_url = None
        error_details = None
        
        for attempt in range(max_retries + 1):
            attempt_num = attempt + 1
            print(f"[{request_id}] 🎬 渲染尝试 {attempt_num}/{max_retries+1}...")
            
            with open(SCENE_FILE, "w", encoding="utf-8") as f:
                f.write(final_code)
            
            cmd = [
                sys.executable, "-m", "manim",
                "-ql",  # 低质量，快速渲染
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
                
                if attempt < max_retries:
                    print(f"[{request_id}] 🚑 启动紧急修复...")
                    
                    fixer_prompt = f"""
你是一个Manim代码修复专家。请修复以下代码中的错误。

【错误信息】:
{error_details}

【问题代码】:
{final_code}

【修复要求】:
1. 分析错误类型
2. 提供最小化修改
3. 保持原有意图
4. **特别注意文字布局问题，确保文字不遮挡图形**
5. 确保代码可以运行

只输出修复后的完整Python代码。
"""
                    
                    fix_response = await client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[
                            {"role": "system", "content": "你是一个代码修复专家"},
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
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>MathSpace 智能监控</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.15);
        }
        .card h2 {
            color: #333;
            margin-bottom: 16px;
            font-size: 18px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .card h2::before {
            content: '';
            width: 4px;
            height: 20px;
            background: #667eea;
            border-radius: 2px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #eee;
        }
        .status-item:last-child {
            border-bottom: none;
        }
        .status-label {
            color: #666;
            font-size: 14px;
        }
        .status-value {
            font-weight: 500;
            color: #333;
        }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .badge-success { background: #10b981; color: white; }
        .badge-warning { background: #f59e0b; color: white; }
        .badge-error { background: #ef4444; color: white; }
        .badge-info { background: #3b82f6; color: white; }
        .object-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }
        .object-tag {
            background: #e0e7ff;
            color: #4f46e5;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
        }
        .code-preview {
            background: #1e293b;
            color: #cbd5e1;
            padding: 16px;
            border-radius: 8px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            margin-top: 12px;
        }
        .refresh-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .refresh-btn:hover {
            transform: rotate(180deg);
            background: #f8fafc;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        .loading {
            animation: pulse 1.5s infinite;
        }
    </style>
</head>
<body>
    <div class="container" id="container">
        <div class="card">
            <h2>📊 系统状态</h2>
            <div id="system-status"></div>
        </div>
        
        <div class="card">
            <h2>🧠 上下文感知</h2>
            <div id="context-info"></div>
        </div>
        
        <div class="card">
            <h2>🎯 当前意图</h2>
            <div id="intent-analysis"></div>
        </div>
        
        <div class="card">
            <h2>📝 代码结构</h2>
            <div id="code-structure"></div>
        </div>
        
        <div class="card">
            <h2>🔄 最近交互</h2>
            <div id="recent-conversations"></div>
        </div>
        
        <div class="card">
            <h2>⚙️ 系统调试</h2>
            <div id="debug-info"></div>
        </div>
    </div>
    
    <div class="refresh-btn" onclick="loadAllData()">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
        </svg>
    </div>
    
    <script>
        async function loadAllData() {
            const cards = document.querySelectorAll('.card');
            cards.forEach(card => card.classList.add('loading'));
            
            try {
                const statusRes = await fetch('/api/context');
                const statusData = await statusRes.json();
                
                document.getElementById('system-status').innerHTML = `
                    <div class="status-item">
                        <span class="status-label">当前对象数</span>
                        <span class="status-value">${statusData.current_state?.object_count || 0}</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">坐标轴状态</span>
                        <span class="status-value">
                            <span class="badge ${statusData.current_state?.has_axes ? 'badge-success' : 'badge-info'}">
                                ${statusData.current_state?.has_axes ? '已启用' : '未启用'}
                            </span>
                        </span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">代码状态</span>
                        <span class="status-value">
                            <span class="badge ${statusData.current_state?.status === 'has_code' ? 'badge-success' : 'badge-warning'}">
                                ${statusData.current_state?.status === 'has_code' ? '有代码' : '无代码'}
                            </span>
                        </span>
                    </div>
                `;
                
                document.getElementById('context-info').innerHTML = `
                    <div style="color: #666; font-size: 14px; line-height: 1.5;">
                        ${statusData.conversation_summary.text.replace(/\\n/g, '<br>')}
                    </div>
                    ${statusData.conversation_summary.objects.length > 0 ? `
                        <div style="margin-top: 12px;">
                            <div style="color: #666; font-size: 12px; margin-bottom: 4px;">已识别对象:</div>
                            <div class="object-list">
                                ${statusData.conversation_summary.objects.slice(0, 6).map(obj => 
                                    `<span class="object-tag">${obj}</span>`
                                ).join('')}
                                ${statusData.conversation_summary.objects.length > 6 ? 
                                    `<span class="object-tag">+${statusData.conversation_summary.objects.length - 6}更多</span>` : ''
                                }
                            </div>
                        </div>
                    ` : ''}
                `;
                
                const recentHTML = statusData.recent_conversations.length > 0 ? 
                    statusData.recent_conversations.reverse().map(conv => `
                        <div style="margin-bottom: 12px; padding: 12px; background: #f8fafc; border-radius: 8px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <span style="font-size: 11px; color: #94a3b8;">${conv.timestamp}</span>
                                <span class="badge ${conv.success ? 'badge-success' : 'badge-error'}" style="font-size: 10px;">
                                    ${conv.success ? '成功' : '失败'}
                                </span>
                            </div>
                            <div style="font-size: 13px; color: #334155; margin-bottom: 4px;">
                                ${conv.user}
                            </div>
                            ${conv.intent_analysis ? `
                                <div style="font-size: 11px; color: #64748b;">
                                    意图: ${conv.intent_analysis.intent || '未知'}
                                </div>
                            ` : ''}
                        </div>
                    `).join('') : '<div style="color: #94a3b8; text-align: center;">暂无交互记录</div>';
                
                document.getElementById('recent-conversations').innerHTML = recentHTML;
                
            } catch (error) {
                console.error('加载数据失败:', error);
            } finally {
                cards.forEach(card => card.classList.remove('loading'));
            }
        }
        
        loadAllData();
        setInterval(loadAllData, 5000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)

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