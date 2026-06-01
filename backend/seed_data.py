"""
种子数据脚本 — 软工2201班规模
生成一个完整班级使用系统的数据体量：
  - 组织：山东科技大学 → 各学院
  - 用户：1管理员 + 3教师 + 30学生
  - 供应商 + 模型：阿里云 DashScope（LLM + Embedding）
  - 知识库：3门课程 + 1班级公告
  - Bot：每门课1个助手 + 1班级事务助手
  - 模型配置：每门课1个配置
  - 对话 + 消息：每个学生若干条历史记录

用法：
    cd ModelHub-backend
    .venv/bin/python seed_data.py
    .venv/bin/python seed_data.py --clean   # 先清空再重建
"""

import asyncio
import argparse
import sys
import uuid
from datetime import datetime, timedelta
import random
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# 把项目根目录加入 path
sys.path.insert(0, '.')

from app.config import settings
from app.extensions import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.provider_config import ProviderConfig
from app.models.model_info import ModelInfo
from app.models.model_config import ModelConfig
from app.models.vector_db import VectorDb
from app.models.bot import Bot
from app.models.conversation import Conversation
from app.models.message import Message

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─────────────────────────────────────────────
# 数据库连接
# ─────────────────────────────────────────────
DB_URL = (
    f"mysql+aiomysql://{settings.db_username}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_database}"
)

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────
def hash_pw(pw: str) -> str:
    return pwd_context.hash(pw)


def rand_time(days_ago_max=90, days_ago_min=1):
    delta = timedelta(
        days=random.randint(days_ago_min, days_ago_max),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return datetime.now() - delta


# ─────────────────────────────────────────────
# 清理旧数据
# ─────────────────────────────────────────────
async def clean_all(session: AsyncSession):
    print("🗑  清空旧种子数据...")
    tables = [
        'message', 'conversation', 'bot', 'vector_db',
        'model_config', 'model_info', 'provider_config',
        'organization_member', 'user', 'organization',
    ]
    await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    for t in tables:
        await session.execute(text(f"TRUNCATE TABLE `{t}`"))
    await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    await session.commit()
    print("   完成")


# ─────────────────────────────────────────────
# 1. 组织架构（学校 → 学院 → 专业）
# ─────────────────────────────────────────────
COLLEGES_AND_MAJORS = [
    # ── 青岛校区 ──
    ("能源与矿业工程学院",     "EMME",  ["采矿工程", "智能采矿工程", "工业工程", "工程力学"]),
    ("安全与环境工程学院",     "SEE",   ["安全工程", "环境工程", "职业卫生工程"]),
    ("测绘与空间信息学院",     "SGI",   ["测绘工程", "遥感科学与技术", "地理信息科学"]),
    ("地球科学与工程学院",     "GSE",   ["地质工程", "水文与水资源工程", "资源勘查工程", "勘查技术与工程"]),
    ("土木工程与建筑学院",     "CEA",   ["土木工程", "建筑学", "建筑环境与能源应用工程", "城市地下空间工程"]),
    ("机械电子工程学院",       "MEE",   ["机械设计制造及其自动化", "机械电子工程", "智能制造工程"]),
    ("计算机科学与工程学院",   "CSE",   ["计算机科学与技术", "软件工程", "信息安全", "物联网工程", "智能科学与技术"]),
    ("数学与系统科学学院",     "MSS",   ["数学与应用数学", "信息与计算科学", "统计学", "数据科学与大数据技术"]),
    ("经济管理学院",           "EM",    ["金融学", "会计学", "工商管理", "国际经济与贸易", "财政学", "投资学", "物流管理", "大数据管理与应用", "供应链管理"]),
    ("电气与自动化工程学院",   "EAE",   ["电气工程及其自动化", "自动化", "机器人工程"]),
    ("电子信息工程学院",       "EIE",   ["电子信息工程", "通信工程", "应用物理学", "集成电路设计与集成系统"]),
    ("化学与生物工程学院",     "CBE",   ["化学工程与工艺", "应用化学", "矿物加工工程", "生物工程", "生物制药"]),
    ("材料科学与工程学院",     "MSE",   ["金属材料工程", "高分子材料与工程", "新能源材料与器件", "材料化学"]),
    ("交通学院",               "TRA",   ["交通运输", "智慧交通"]),
    ("储能技术学院",           "EST",   ["储能科学与工程", "新能源科学与工程", "能源与动力工程"]),
    ("海洋科学与工程学院",     "OSE",   ["海洋技术", "船舶与海洋工程"]),
    ("文法学院",               "LAW",   ["法学", "汉语言文学", "行政管理"]),
    ("外国语学院",             "FL",    ["英语", "日语", "朝鲜语"]),
    ("艺术学院",               "ART",   ["音乐学", "视觉传达设计", "环境设计", "产品设计"]),
    ("体育学院",               "PE",    ["运动训练"]),
    # ── 泰安校区 ──
    ("资源学院",               "RES",   ["防灾减灾科学与工程", "工程管理"]),
    ("智能装备学院",           "IE",    ["应急装备技术与工程", "网络工程", "信息工程"]),
    ("财经学院",               "FIN",   ["审计学", "国际商务", "金融科技"]),
    # ── 济南校区 ──
    ("斯威本学院",             "SWI",   ["机械电子工程(中外合作)", "软件工程(中外合作)", "自动化(中外合作)", "工业设计(中外合作)", "金融学(中外合作)", "电气工程及其自动化(中外合作)", "通信工程(中外合作)"]),
]


async def seed_organizations(session: AsyncSession) -> dict:
    print("🏫 创建组织架构...")

    school = Organization(
        name="山东科技大学", code="SDUST", type="school",
        level=1, path="", description="山东科技大学", status="active",
    )
    session.add(school)
    await session.flush()
    school.path = str(school.id)
    school.school_id = school.id

    colleges = {}   # code -> Organization
    majors = {}     # "{college_code}/{major_name}" -> Organization
    cs_college = None
    se_major = None  # 软件工程专业
    total_majors = 0

    for college_name, college_code, major_names in COLLEGES_AND_MAJORS:
        c = Organization(
            name=college_name, code=college_code, type="college",
            parent_id=school.id, school_id=school.id,
            level=2, description=college_name, status="active",
        )
        session.add(c)
        await session.flush()
        c.path = f"{school.id}/{c.id}"
        colleges[college_code] = c

        if college_code == "CSE":
            cs_college = c

        for idx, major_name in enumerate(major_names, 1):
            major_code = f"{college_code}-M{idx:02d}"
            m = Organization(
                name=major_name, code=major_code, type="major",
                parent_id=c.id, school_id=school.id,
                level=3, description=f"{college_name} — {major_name}",
                status="active",
            )
            session.add(m)
            await session.flush()
            m.path = f"{school.id}/{c.id}/{m.id}"
            majors[f"{college_code}/{major_name}"] = m
            total_majors += 1

            if college_code == "CSE" and major_name == "软件工程":
                se_major = m

    await session.commit()
    print(f"   山东科技大学 → {len(COLLEGES_AND_MAJORS)} 个学院 → {total_majors} 个专业")
    return {
        "school": school,
        "colleges": colleges,
        "majors": majors,
        "cs_college": cs_college,
        "se_major": se_major,
    }


# ─────────────────────────────────────────────
# 2. 用户
# ─────────────────────────────────────────────
async def seed_users(session: AsyncSession, orgs: dict) -> dict:
    print("👥 创建用户（1管理员 + 1教师 + 1学生）...")
    school = orgs["school"]
    cs_college = orgs["cs_college"]
    se_major = orgs["se_major"]

    # 管理员
    admin = User(
        name="系统管理员", email="admin@sdust.edu.cn",
        password=hash_pw("admin123456"),
        role="admin", school_id=school.id,
        student_id=None, employee_id="A001",
        describe="系统管理员账号", status="active",
    )
    session.add(admin)
    await session.flush()
    session.add(OrganizationMember(user_id=admin.id, organization_id=school.id, role="admin"))

    # 教师 — 绑定到计算机学院
    teacher = User(
        name="张伟", email="zhang.wei@sdust.edu.cn",
        password=hash_pw("teacher123"),
        role="teacher", school_id=school.id,
        employee_id="T001",
        describe="计算机学院教师", status="active",
    )
    session.add(teacher)
    await session.flush()
    session.add(OrganizationMember(user_id=teacher.id, organization_id=school.id, role="teacher"))
    session.add(OrganizationMember(user_id=teacher.id, organization_id=cs_college.id, role="teacher"))
    teachers = [teacher]

    # 学生 — 学号前4位是入学年份，绑定到软件工程专业
    student = User(
        name="陈浩", email="s20220001@sdust.edu.cn",
        password=hash_pw("student123"),
        role="student", school_id=school.id,
        student_id="20220001", enrollment_year=2022,
        describe="软件工程 2022级 陈浩", status="active",
    )
    session.add(student)
    await session.flush()
    session.add(OrganizationMember(user_id=student.id, organization_id=school.id, role="student"))
    session.add(OrganizationMember(user_id=student.id, organization_id=cs_college.id, role="student"))
    if se_major:
        session.add(OrganizationMember(user_id=student.id, organization_id=se_major.id, role="student"))
    students = [student]

    await session.commit()
    print(f"   管理员: {admin.email} / admin123456")
    print(f"   教师:   {teacher.email} / teacher123")
    print(f"   学生:   {student.email} / student123")
    return {"admin": admin, "teachers": teachers, "students": students}


# ─────────────────────────────────────────────
# 3. 供应商 + 模型
# ─────────────────────────────────────────────
async def seed_models(session: AsyncSession) -> dict:
    print("🤖 创建供应商和模型...")

    # 4 个供应商
    p_aliyun = ProviderConfig(
        name="阿里云 DashScope", code="aliyun",
        provider_type="aliyun",
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        description="阿里云通义系列，支持 LLM 与 Embedding",
        is_active=True, is_default=True, priority=10,
        rate_limit=60, max_tokens=8192,
        supported_model_types="chatllm,embedding",
    )
    p_openai = ProviderConfig(
        name="OpenAI", code="openai",
        provider_type="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-placeholder-openai-key",
        description="OpenAI GPT 系列（需配置真实 Key）",
        is_active=False, is_default=False, priority=5,
        rate_limit=30, max_tokens=4096,
        supported_model_types="chatllm",
    )
    p_deepseek = ProviderConfig(
        name="DeepSeek", code="deepseek",
        provider_type="custom",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-placeholder-deepseek-key",
        description="深度求索 DeepSeek 系列，兼容 OpenAI 协议（需配置真实 Key）",
        is_active=False, is_default=False, priority=8,
        rate_limit=60, max_tokens=8192,
        supported_model_types="chatllm",
    )
    p_local = ProviderConfig(
        name="OpenAI兼容本地服务", code="local",
        provider_type="local",
        base_url="http://localhost:8000/v1",
        api_key="local-dev-key",
        description="兼容 OpenAI 协议的本地推理服务，支持 Qwen/Llama 等开源模型",
        is_active=False, is_default=False, priority=1,
        rate_limit=10, max_tokens=4096,
        supported_model_types="chatllm",
    )
    session.add_all([p_aliyun, p_openai, p_deepseek, p_local])
    await session.flush()

    # 13 个模型
    models_to_add = [
        # 阿里云
        ModelInfo(model_name="qwen-turbo",  type="chatllm",  provider_id=p_aliyun.id,
                  describe="通义千问 Turbo，速度快、成本低，适合简单问答",
                  max_tokens=6144, context_window=8192, is_active=True, is_default=False, priority=7),
        ModelInfo(model_name="qwen-plus",   type="chatllm",  provider_id=p_aliyun.id,
                  describe="通义千问 Plus，均衡性价比，推荐日常使用",
                  max_tokens=8192, context_window=32768, is_active=True, is_default=True, priority=10),
        ModelInfo(model_name="qwen-max",    type="chatllm",  provider_id=p_aliyun.id,
                  describe="通义千问 Max，最强推理能力，适合复杂任务",
                  max_tokens=8192, context_window=32768, is_active=True, is_default=False, priority=8),
        ModelInfo(model_name="qwen3.6-max-preview", type="chatllm", provider_id=p_aliyun.id,
                  describe="通义千问 3.6 Max 预览版，最新旗舰推理模型",
                  max_tokens=8192, context_window=131072, is_active=True, is_default=False, priority=9),
        ModelInfo(model_name="qwen3.6-plus", type="chatllm", provider_id=p_aliyun.id,
                  describe="通义千问 3.6 Plus，新一代均衡模型，性能显著提升",
                  max_tokens=8192, context_window=131072, is_active=True, is_default=False, priority=8),
        ModelInfo(model_name="qwen3.6-flash", type="chatllm", provider_id=p_aliyun.id,
                  describe="通义千问 3.6 Flash，极速响应、超低成本",
                  max_tokens=8192, context_window=131072, is_active=True, is_default=False, priority=6),
        ModelInfo(model_name="qwen-image-2.0", type="chatllm", provider_id=p_aliyun.id,
                  describe="通义万相 2.0，多模态图像理解与生成模型",
                  max_tokens=4096, context_window=8192, is_active=True, is_default=False, priority=7),
        ModelInfo(model_name=settings.embedding_model, type="embedding", provider_id=p_aliyun.id,
                  describe="通义文本向量 v4，1536维，支持中英文",
                  is_active=True, is_default=True, priority=10),
        # DeepSeek（未激活，需配置 Key）
        ModelInfo(model_name="deepseek-v4-pro", type="chatllm", provider_id=p_deepseek.id,
                  describe="DeepSeek V4 Pro，国产高性能推理模型，性价比极高",
                  max_tokens=8192, context_window=65536, is_active=False, is_default=False, priority=9),
        ModelInfo(model_name="vanchin/deepseek-v3.2-think", type="chatllm", provider_id=p_deepseek.id,
                  describe="DeepSeek V3.2 Think，深度思考推理模型，支持思维链",
                  max_tokens=8192, context_window=65536, is_active=False, is_default=False, priority=8),
        # OpenAI（未激活，仅配置展示）
        ModelInfo(model_name="gpt-3.5-turbo", type="chatllm", provider_id=p_openai.id,
                  describe="GPT-3.5 Turbo，快速低价",
                  max_tokens=4096, context_window=16384, is_active=False, is_default=False, priority=5),
        ModelInfo(model_name="gpt-4o",        type="chatllm", provider_id=p_openai.id,
                  describe="GPT-4o，多模态旗舰模型",
                  max_tokens=4096, context_window=128000, is_active=False, is_default=False, priority=6),
        # 本地
        ModelInfo(model_name="qwen2.5-7b-instruct",   type="chatllm", provider_id=p_local.id,
                  describe="Qwen2.5 7B 本地部署，需通过 OpenAI 兼容接口提供服务",
                  max_tokens=4096, context_window=32768, is_active=False, is_default=False, priority=3),
    ]
    session.add_all(models_to_add)
    await session.flush()

    # 按名称建立模型索引，方便 config_defs 引用
    model_map = {m.model_name: m for m in models_to_add}
    emb = next(m for m in models_to_add if m.type == "embedding")

    await session.commit()
    print(f"   供应商: 4个  模型: {len(models_to_add)}个")
    return {
        "providers": [p_aliyun, p_openai, p_deepseek, p_local],
        "model_map": model_map, "embedding": emb,
        "all_llms": [m for m in models_to_add if m.type == "chatllm" and m.is_active],
    }


# ─────────────────────────────────────────────
# 4. 知识库
# ─────────────────────────────────────────────
async def seed_vector_dbs(session: AsyncSession, users: dict, orgs: dict, models: dict) -> tuple:
    print("📚 创建知识库...")
    admin = users["admin"]
    teachers = users["teachers"]
    school = orgs["school"]
    cs_college = orgs["cs_college"]
    emb = models["embedding"]

    kb_defs = [
        # ── 学校级知识库（全校公开，organization_id=school）──
        {"name": "学校通知公告库",           "describe": "学校官网通知、教务处公告、校历、政策制度",
         "owner": admin, "org": school},
        {"name": "学生手册与规章制度库",     "describe": "学生守则、奖助学金政策、学籍管理、违纪处分规定",
         "owner": admin, "org": school},
        {"name": "实习就业指南",  "describe": "简历写作、面试经验、大厂笔试题解析、实习信息",
         "owner": admin, "org": school},
        {"name": "毕业设计资料库", "describe": "毕设流程、论文写作规范、查重说明、往届优秀毕设、答辩安排",
         "owner": admin, "org": school},
        # ── 学院级知识库（学院公开，organization_id=college）──
        {"name": "计算机学院通知库",         "describe": "学院公告、专业介绍、培养方案、竞赛通知、教学安排",
         "owner": teachers[0], "org": cs_college},
        {"name": "软件工程专业公告库",       "describe": "专业通知、课程安排、考试信息、学业动态",
         "owner": teachers[0], "org": cs_college},
        # ── 个人级知识库（私有，organization_id=None）──
        {"name": "个人毕设资料库",           "describe": "导师要求、论文草稿、参考文献、答辩准备材料",
         "owner": teachers[0], "org": None},
    ]

    vdbs = []
    for kd in kb_defs:
        vdb = VectorDb(
            name=kd["name"], describe=kd["describe"],
            user_id=kd["owner"].id,
            embedding_id=emb.id,
            organization_id=kd["org"].id if kd["org"] else None,
            document_similarity=0.70,
        )
        session.add(vdb)
        await session.flush()
        vdbs.append(vdb)

    await session.commit()

    # ── 模型配置（3个）──
    # 3 个配置用不同底层模型，覆盖论文三个维度：温度策略 × 不同模型 × 有无知识库
    config_defs = [
        # 精确问答：低温 + 最强模型 + 带知识库 → 论文第6章严谨场景实验 + 溯源展示
        {"vdb_idx": 0, "owner_idx": "admin", "temp": 0.3, "top_p": 0.8,
         "model": "qwen-max",
         "name": "精确问答",
         "prompt": "基于知识库内容精确回答，必须标注信息来源。不确定的内容明确说明，禁止编造。"},
        # 标准对话：中温 + 均衡模型 + 带知识库 → 论文第5章主力演示截图
        {"vdb_idx": 0, "owner_idx": "admin", "temp": 0.5, "top_p": 0.85,
         "model": "qwen3.6-plus",
         "name": "标准对话",
         "prompt": "基于知识库信息回答问题，语言简洁清晰，兼顾准确性和流畅度。"},
        # 自由对话：高温 + 轻量模型 + 无知识库 → 论文第6章 RAG vs 无RAG 对比实验
        {"vdb_idx": None, "owner_idx": "admin", "temp": 0.9, "top_p": 0.95,
         "model": "qwen3.6-flash",
         "name": "自由对话",
         "prompt": "你是一个通用AI助手，可以自由对话、解答问题、辅助编程、写作润色。"},
    ]

    owner_map = {
        "t0": users["teachers"][0], "admin": users["admin"],
    }
    model_map = models["model_map"]
    configs = []
    for cd in config_defs:
        owner = owner_map[cd["owner_idx"]]
        base_model = model_map[cd["model"]]
        mc = ModelConfig(
            user_id=owner.id,
            share_id=str(uuid.uuid4()),
            base_model_id=base_model.id,
            name=cd["name"],
            temperature=cd["temp"], top_p=cd["top_p"],
            prompt=cd["prompt"],
            organization_id=school.id,
        )
        session.add(mc)
        await session.flush()
        configs.append(mc)
    await session.commit()

    print(f"   创建 {len(vdbs)} 个知识库，{len(configs)} 个模型配置")
    return vdbs, configs


# ─────────────────────────────────────────────
# 5. Bot
# ─────────────────────────────────────────────
async def seed_bots(session: AsyncSession, users: dict, orgs: dict, configs: list, vdbs: list) -> list:
    print("🤖 创建数字助手...")
    teachers = users["teachers"]
    admin = users["admin"]
    school = orgs["school"]
    cs_college = orgs["cs_college"]

    # configs 索引：0=精确问答(qwen-max)  1=标准对话(qwen3.6-plus)  2=自由对话(qwen3.6-flash)

    bot_defs = [
        # 山科通：学校级公开
        {"name": "山科通",
         "desc": "山东科技大学综合智能助手，一站式查询校园通知、规章制度、教务信息",
         "owner": admin, "config": configs[1],
         "vdb_ids": [vdbs[0].id, vdbs[1].id],
         "org": school,
         "system_prompt": "你是山东科技大学综合服务助手「山科通」。你能查询学校通知、教务公告、规章制度、校历安排等信息。回答要简洁准确，涉及政策时标注信息来源。如果问题超出知识库范围，坦诚告知并建议咨询相关部门。",
         "greeting": "你好，我是「山科通」！学校通知、教务公告、规章政策都可以问我，有什么需要帮忙的？",
         "forbidden_topics": []},

        # 毕设助手：学校级公开
        {"name": "毕设助手",
         "desc": "毕业设计全流程辅导助手，覆盖选题、开题、写作、查重、答辩",
         "owner": admin, "config": configs[0],
         "vdb_ids": [vdbs[3].id],
         "org": school,
         "system_prompt": "你是山东科技大学毕业设计辅导助手。你熟悉毕业设计的全部流程——选题、任务书、开题报告、中期检查、论文写作、查重检测、AIGC检测、答辩、材料归档。回答时优先引用学校文件中的具体要求和时间节点，帮助学生少走弯路。对于写作技巧类问题可以适当展开。",
         "greeting": "同学好！毕设的事都可以找我——选题方向、开题报告怎么写、查重要求、答辩流程，问就对了！",
         "forbidden_topics": ["代写论文"]},

        # 求职教练：学校级公开
        {"name": "求职教练",
         "desc": "就业指导与求职辅导，简历优化、面试准备、职业规划",
         "owner": admin, "config": configs[1],
         "vdb_ids": [vdbs[2].id],
         "org": school,
         "system_prompt": "你是就业辅导助手「求职教练」。你帮助学生准备求职全过程——简历撰写、面试技巧、笔试准备、实习选择、职业规划。语气友好鼓励，多给具体可操作的建议。遇到不了解的行业可以坦诚说明。",
         "greeting": "嗨！准备找工作了？简历润色、面试模拟、行业分析，咱们一步步来，你肯定行！",
         "forbidden_topics": []},

        # AI 聊天室：学校级公开
        {"name": "AI 聊天室",
         "desc": "不绑定知识库的自由对话，支持闲聊、头脑风暴、代码辅助",
         "owner": admin, "config": configs[2],
         "vdb_ids": [],
         "org": school,
         "system_prompt": "你是一个通用AI助手，可以自由对话、解答问题、辅助编程、写作润色、头脑风暴。不限于校园话题，但保持友好和有帮助。",
         "greeting": "随便聊聊？无论是编程问题、作业难题还是奇思妙想，我都在！",
         "forbidden_topics": []},
    ]

    bots = []
    for bd in bot_defs:
        b = Bot(
            name=bd["name"],
            description=bd.get("desc", f"{bd['name']}——智能问答助手"),
            system_prompt=bd["system_prompt"],
            greeting=bd["greeting"],
            forbidden_topics=bd["forbidden_topics"],
            model_config_id=bd["config"].id,
            vector_db_ids=bd["vdb_ids"],
            user_id=bd["owner"].id,
            organization_id=bd["org"].id if bd.get("org") else None,
        )
        session.add(b)
        await session.flush()
        bots.append(b)

    await session.commit()
    print(f"   创建 {len(bots)} 个 Bot")
    return bots


# ─────────────────────────────────────────────
# 6. 对话 + 消息
# ─────────────────────────────────────────────
SAMPLE_QA = {
    # ── 山科通（综合助手）──
    "山科通": [
        ("本学期校历安排是什么？",
         "根据学校教务处通知，本学期主要时间节点：\n- 开学注册：2月24日\n- 期中教学检查：第9-10周\n- 期末考试：第17-19周\n- 寒假开始：7月12日\n\n具体安排请以教务处最新通知为准。"),
        ("教务处最新通知有哪些？",
         "近期教务处主要通知：\n1. 关于2026届本科毕业设计（论文）工作安排的通知\n2. 关于开展期中教学质量检查的通知\n3. 关于本学期补考安排的通知\n4. 关于选课系统开放时间调整的通知\n\n详细内容可登录教务处官网查看。"),
        ("学校地址在哪？有几个校区？",
         "学校目前有三个校区：\n- **青岛校区**（主校区）：青岛市黄岛区前湾港路579号\n- **泰安校区**：泰安市泰山区岱宗大街223号\n- **济南校区**：济南市天桥区胜利庄路17号\n\n本科生主要在青岛校区就读。"),
        ("四六级报名时间是什么时候？",
         "根据学校通知，本学期英语四六级考试报名安排：\n- 报名时间：3月中旬（具体以教务处通知为准）\n- 考试时间：6月14日\n- 报名方式：登录全国大学英语四六级考试报名系统\n\n请关注教务处和班级群通知，不要错过报名时间。"),
    ],
    # ── 毕设助手（毕设辅导）──
    "毕设助手": [
        ("毕业设计什么时候开始？流程是什么？",
         "根据教务安排，毕业设计主要流程：\n1. **选题**（第7学期12月）：双向选择确认题目\n2. **任务书下达**：指导教师在管理系统中下达\n3. **开题报告**：学生撰写并参加开题答辩\n4. **中期检查**（第8学期3-4月）：提交中期报告\n5. **论文撰写与查重**（4-5月）：定稿、知网查重+AIGC检测\n6. **答辩**（5-6月）：PPT汇报+教师提问\n7. **材料归档**（6月）：系统中完善所有材料\n\n请尽早与导师沟通确认选题方向，不要拖到最后。"),
        ("开题报告怎么写？",
         "开题报告主要包括以下部分：\n\n1. **课题名称**：简洁明确\n2. **研究目的和意义**：为什么做这个课题\n3. **国内外研究现状**：文献综述，引用10-15篇参考文献\n4. **主要研究内容**：你打算做什么\n5. **拟解决的关键问题**：技术难点\n6. **研究方法和技术路线**：怎么做\n7. **进度安排**：时间表\n8. **参考文献**：格式规范\n\n重点是研究内容和技术路线，要具体不要空泛。开题报告需在管理系统中提交，经指导教师审核通过后方可开题。"),
        ("论文查重率要求是多少？",
         "根据学校毕业设计管理规定：\n- **查重率要求**：文字复制比不超过30%\n- **查重系统**：知网大学生论文检测系统\n- **AIGC检测**：从2024届起增加，AIGC生成比例原则上不超过40%\n- **注意事项**：\n  1. 直接复制的文字会被标红\n  2. 公式、代码通常不计入查重\n  3. 参考文献格式正确的引用不计入\n  4. 查重和AIGC检测不通过需修改后重新提交\n\n合理使用AI工具辅助文献检索、语言润色是允许的，但不能直接生成论文内容。"),
        ("答辩需要准备什么？",
         "毕业设计答辩准备清单：\n\n**材料准备：**\n1. 论文终稿（打印装订）\n2. PPT（建议15-20页）\n3. 系统演示环境（确保能正常运行）\n\n**PPT 内容：**\n- 选题背景与意义（1-2页）\n- 系统设计与架构（3-4页）\n- 核心实现（5-6页，重点）\n- 测试与实验结果（2-3页）\n- 总结与展望（1页）\n\n**答辩流程：** 自述8-10分钟 → 老师提问5-10分钟\n\n**注意：** 提前演练，控制时间，准备好常见问题的回答。"),
        ("怎么选毕设题目？",
         "选题建议：\n\n1. **与导师方向匹配**：先了解导师的研究方向\n2. **难度适中**：能在规定时间内完成\n3. **「真题真做」优先**：工科专业要求80%以上选题来源于实际\n4. **一人一题**：题目不得与往届重复\n\n**热门方向参考：**\n- Web/App 开发类（前后端分离系统）\n- 数据分析与可视化\n- 机器学习/深度学习应用\n- 大语言模型应用（RAG、智能助手等）\n\n选题需经教学单位毕设工作领导小组论证审核。"),
    ],
    # ── 求职教练 ──
    "求职教练": [
        ("怎么写简历？有什么建议？",
         "简历写作建议：\n\n**基本原则：** 一页纸，突出重点\n\n**必备模块：**\n1. **个人信息**：姓名、联系方式、求职意向\n2. **教育背景**：学校、专业、GPA（如果不错的话）\n3. **项目经历**：用 STAR 法则描述（情境-任务-行动-结果）\n4. **技能清单**：编程语言、框架、工具\n5. **竞赛/荣誉**：有含金量的放\n\n**避免：** 照片（除非要求）、与岗位无关的经历、模糊描述。"),
        ("面试一般问什么？怎么准备？",
         "技术面试常见环节：\n\n1. **自我介绍**（1-2分钟）：突出项目和技能\n2. **项目深挖**：准备好每个项目的技术细节、遇到的问题和解决方案\n3. **算法题**：LeetCode 中等难度，重点掌握数组、链表、树、动态规划\n4. **八股文**：计算机网络、操作系统、数据库基础\n5. **反问环节**：准备2-3个有质量的问题\n\n建议提前1-2个月刷题，多做模拟面试。加油，你可以的！"),
        ("实习一般什么时候找？",
         "实习时间线建议：\n- **大二暑期**：可以开始找第一段实习，要求不高\n- **大三秋季**（9-11月）：大厂秋招提前批\n- **大三寒假**：春招实习投递\n- **大三暑期**：核心实习期，争取转正机会\n\n**渠道：** 牛客网、实习僧、Boss直聘、学院就业群、学长内推。"),
    ],
    # ── AI 聊天室 ──
    "AI 聊天室": [
        ("帮我写一段Python快排",
         "```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```\n\n这是最简洁的列表推导式写法。生产环境中建议用 `sorted()` 或原地分区版本。需要更详细的解释吗？"),
        ("用英语帮我润色这段话",
         "当然可以！请把需要润色的内容发给我，我会帮你：\n1. 修正语法错误\n2. 改善表达的流畅度\n3. 提升用词的学术性（如果是论文的话）\n\n直接贴上来就行！"),
    ],
}

SAMPLE_QA_ALIAS = {}

async def seed_conversations(session: AsyncSession, users: dict, bots: list) -> None:
    print("💬 创建对话记录...")
    students = users["students"]
    teachers = users["teachers"]
    total_conv = 0
    total_msg = 0

    # 教师也有部分对话（测试用）
    all_users = students + teachers

    # 所有归属组织的 bot 学生都可以用
    public_bots = [b for b in bots if b.organization_id is not None]

    for u in all_users:
        is_teacher = u in teachers
        # 教师与所有bot都交互过；学生只能用公开bot，随机选
        selected_bots = bots if is_teacher else random.sample(public_bots, k=min(random.randint(4, 6), len(public_bots)))
        for bot in selected_bots:
            bot_name = bot.name
            qa_key = SAMPLE_QA_ALIAS.get(bot_name, bot_name)
            qa_list = SAMPLE_QA.get(qa_key, [])
            if not qa_list:
                continue
            # 教师1-2轮；学生 5-12轮（模拟一学期使用）
            num_convs = random.randint(1, 2) if is_teacher else random.randint(5, 12)
            for conv_idx in range(num_convs):
                conv = Conversation(
                    user_id=u.id,
                    model_config_id=bot.model_config_id,
                    name=f"{bot_name[:8]}·第{conv_idx+1}次",
                    create_at=rand_time(120, 1),
                )
                session.add(conv)
                await session.flush()
                total_conv += 1

                # 每轮对话 2-4 组 QA（多轮交流）
                n_qa = min(random.randint(2, 4), len(qa_list))
                qa_samples = random.sample(qa_list, k=n_qa)
                t = conv.create_at
                for q, a in qa_samples:
                    t = t + timedelta(seconds=random.randint(10, 60))
                    session.add(Message(conversation_id=conv.id, role="user", content=q, create_at=t))
                    t = t + timedelta(seconds=random.randint(3, 15))
                    session.add(Message(conversation_id=conv.id, role="assistant", content=a, create_at=t))
                    total_msg += 2

    await session.commit()
    print(f"   创建 {total_conv} 条对话，{total_msg} 条消息")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
async def main(clean: bool = False):
    print("=" * 55)
    print("  ModelHub 种子数据 — 软工2201班规模")
    print("=" * 55)

    async with AsyncSessionLocal() as session:
        if clean:
            await clean_all(session)

        orgs          = await seed_organizations(session)
        users         = await seed_users(session, orgs)
        models        = await seed_models(session)
        vdbs, configs = await seed_vector_dbs(session, users, orgs, models)
        bots          = await seed_bots(session, users, orgs, configs, vdbs)
        await seed_conversations(session, users, bots)

    print()
    print("✅ 种子数据写入完成！")
    print()
    print("登录账号：")
    print("  管理员:  admin@sdust.edu.cn          / admin123456")
    print("  教师:    zhang.wei@sdust.edu.cn      / teacher123")
    print("  学生:    s20220001@sdust.edu.cn      / student123")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ModelHub 种子数据脚本")
    parser.add_argument("--clean", action="store_true", help="先清空所有数据再重建")
    args = parser.parse_args()
    asyncio.run(main(clean=args.clean))
