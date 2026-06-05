<h1 align="center">StoryMap</h1>

<p align="center">
  <strong>从时空视角重构历史人物的生命轨迹</strong>
</p>

<p align="center">
  面向语文、历史、地理跨学科教学的互动式人物足迹地图项目
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/cuizicheng1024/sotry_map?style=flat-square" alt="GitHub stars" />
  <img src="https://img.shields.io/github/last-commit/cuizicheng1024/sotry_map?style=flat-square" alt="Last commit" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Map-AMap-0ea5e9?style=flat-square" alt="AMap" />
  <img src="https://img.shields.io/badge/LLM-MiniMax-7c3aed?style=flat-square" alt="MiniMax" />
</p>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1aLoCBnEiN">视频演示</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#配置说明">配置说明</a> ·
  <a href="#项目结构">项目结构</a>
</p>

## 目录
- [项目概况](#项目概况)
- [适用场景](#适用场景)
- [演示](#演示)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [无 LLM 也能体验什么](#无-llm-也能体验什么)
- [项目结构](#项目结构)
- [作者信息](#作者信息)

## 项目概况
**故事地图（StoryMap）** 面向文史爱好者，遵循 **“人物—时空—事件”** 的叙事主线，提供了地图可视化工具：输入一个名字，就生成可交互的足迹地图课件，知人论世，让历史人物的作品有了时空的分量。

🧭 **项目目标：**借助地图，我们可以把文学与历史研究中偏感性、经验性的“人物分析”，转成可回放、可检索的**时空轨迹**，关注行走与迁徙的线性轨迹，而不仅仅某个时间切片的个人经历。
**从时空视角重构历史人物生命轨迹，解决文史学习中“文本碎片化、时空理解弱、检索成本高”的痛点。**

**技术方案：**
**1. 输入姓名，生成故事：** LLM 结构化生成，利用模型能力检索历史人物信息，并进行结构化（时间—地点—事件/作品—意义）处理
**2.地理定位：** 集成高德地图API完成古今地名对照与地理编码，实现位置信息的精准落图与可视化。
**3. 交互式地图课件：** 基于时间轴图搭建联动的交互式地图课件。

| 核心能力 | 说明 | 教学价值 |
| --- | --- | --- |
| 人物生成 | 输入姓名后生成结构化人物材料与足迹页面 | 降低备课与资料整理成本 |
| 地图可视化 | 以高德地图呈现人物迁徙、贬谪、出使、游历轨迹 | 强化时空理解 |
| 时间轴联动 | 时间窗、节点事件、人物点位联动展示 | 更适合课堂讲解与研学展示 |
| 人物对话 | 基于人物资料生成第一人称对话体验 | 提升学生参与感 |



## 适用场景
面向中学教学与文史学习场景，适合把人物、地点、事件和作品放回同一时空框架中理解。

- **语文人物专题课**：围绕李白、苏轼、辛弃疾等人物，将作品、行旅和人生转折放在地图与时间轴中联动讲解。
- **历史人物时空复盘**：从迁徙、贬谪、出使、征战、治学等轨迹切入，帮助学生理解人物处境与时代背景。
- **跨学科研学展示**：适合语文、历史、地理融合展示，也适合校本课程、研学汇报与文化展陈场景。

🌍 从更宏观的视角重看历史人物：沿着他的足迹，我们能更容易洞悉成长变化，也能看到他与其他人物在时空上的关联。

- **💡 辅助高效备课**：自动抓取人物生平，省去翻阅史料、查找古地名的繁琐过程。
- **📍 直观展现轨迹**：将文字叙述转化为地图足迹，人物生平一目了然。
- **📚 跨学科教学**：契合“大语文”、“大历史”教学理念，在地图中讲诗词，在地理中读历史。
- **✨ 吸引学生注意力**：生成可交互网页，支持时间轴联动和事件弹窗，让课堂更有参与感。

## 演示
#### [故事地图操作展示](https://www.bilibili.com/video/BV1aLoCBnEiN)

演示内容包括：
- 人物页：人物要点 + 地图轨迹
- 主页：人类群星闪耀时 + 时间轴联动
- 人物页：地点连线与节点信息

<img src="storymap/docs/assets/moler_post_01.png" alt="人物页：人物要点 + 地图轨迹" width="880" />
<img src="storymap/docs/assets/moler_post_03.png" alt="主页：人类群星闪耀时 + 时间轴联动" width="880" />
<img src="storymap/docs/assets/moler_post_05.png" alt="人物页：地点连线与节点信息" width="880" />

主页默认展示：
- 搜索框：输入人物姓名，即可生成/跳转到人物页
- 时间轴：“人类群星闪耀时”关系图，查看历史长河中闪耀的人物群星
- 地图视角：从空间视角观察中国历史文化名人分布
- 支持拖动筛选，起止年份可自定义

人物页默认展示：
- 人物简介
- 

## 环境要求
- **Python 版本**：建议 `Python 3.10+`
- **依赖安装**：先安装项目依赖；如果你本地还没有装，可优先尝试 `pip install -r requirements.txt`
- **是否需要 `.env`**：需要。人物对话、实时生成人物页、以及高德地图底图都依赖环境变量配置
- **高德 Key 是否必填**：必填。当前人物页和主页都统一使用高德底图，没有高德 Key 页面地图无法正常加载

## 快速开始

### 本地一键体验
1) 启动服务（提供主页、人物页生成、对话接口等）：
```bash
python3 storymap/script/story_map.py --serve --port 8765
```

2) 浏览器打开主页：
- `http://localhost:8765/`

### 未收录人物
如果主页搜索框输入的人物不在当前库中，会通过服务端实时生成（需自动配置LLM接口），生成完成后自动跳转到人物页。
生成过程中会在主页显示“排队/执行进度”，建议保持页面打开并等待完成。

### 示例人物
- 苏轼
- 李白
- 辛弃疾

## 配置说明
至少建议在 `.env` 中配置以下变量：

```env
Amap_API_Key=你的高德 JS Key
Amap_API_Secret=你的高德安全密钥

LLM_PROVIDER=minimax
LLM_API_KEY=你的大模型 Key
LLM_BASE_URL=https://api.minimaxi.com/anthropic
LLM_MODEL_ID=MiniMax-M3
```

说明：
- `Amap_API_Key`：用于主页和人物页加载高德地图 JS
- `Amap_API_Secret`：高德安全密钥，配合前端地图加载
- `LLM_PROVIDER`：当前推荐使用 `minimax`
- `LLM_API_KEY`：用于人物对话与新人物实时生成
- `LLM_BASE_URL`：MiniMax Token Plan 推荐为 `https://api.minimaxi.com/anthropic`
- `LLM_MODEL_ID`：默认推荐 `MiniMax-M3`

## 无 LLM 也能体验什么
- **已有人物页可直接浏览**：仓库中已生成的人物 HTML 页面可以直接查看
- **主页可浏览现有内容**：可以查看首页时间轴、人物分布和已收录人物入口
- **新人物实时生成需要 LLM**：搜索未收录人物时，服务端需要调用大模型
- **人物对话功能需要 LLM**：人物页里的“开始对话”依赖后端大模型接口

## 项目结构

```text
storymap/
├── script/                 # 主服务、人物页渲染、地图与对话代理逻辑
├── examples/
│   ├── story/              # 人物 Markdown 原始资料
│   └── story_map/          # 已生成的人物 HTML 页面
├── docs/assets/            # README 展示图片
cli/                        # 批量生成、重渲染、辅助脚本
.env                        # 地图与 LLM 的本地配置
README.md                   # 项目说明
skill.md                    # Agent 技能说明文件
```


### ✅ 无奖测试
猜猜这些名句是谁写的？
1. 峨眉山月半轮秋，影入平羌江水流
<img src="storymap/docs/assets/moler_post_06.png" alt="人物页：事件卡片与地图联动" width="880" />

2. 问余平生事业，黄州惠州儋州
<img src="storymap/docs/assets/moler_post_02.png" alt="人物页：左侧时间轴 + 轨迹连线" width="880" />

3. 关东有义士，兴兵讨群凶
<img src="storymap/docs/assets/moler_post_04.png" alt="人物页：时间轴驱动的地点/事件弹窗" width="880" />
---

## 作者信息

作者：崔成 `cuichengzi@foxmail.com`
