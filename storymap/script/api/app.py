import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .quota import _IDEMPOTENCY_STORES as _GENERATE_IDEMPOTENCY_STORES
from .routers import ai_proxy, coords, debug, generation, health, portrait, static_pages, tasks
from .star_office import (
    build_star_office_agents as _star_office_agents_payload,
    build_star_office_memo as _star_office_memo_payload,
    build_star_office_status as _star_office_status_payload,
)

__all__ = [
    "_GENERATE_IDEMPOTENCY_STORES",
    "_star_office_agents_payload",
    "_star_office_memo_payload",
    "_star_office_status_payload",
    "create_app",
]


def create_app(
    *,
    allowed_origins,
    resolve_cors_origin,
    static_service,
    task_service,
    proxy_service,
    amap_config_js,
    geovis_config_js,
    coords_bulk_update,
    portrait_service=None,
) -> FastAPI:
    app = FastAPI(
        title="故事地图 API",
        description=(
            "## 故事地图（StoryMap）后端 API 文档\n\n"
            "本服务为「历史人物时空分析」前端与外部脚本提供统一入口，主要能力包括：\n\n"
            "- **健康检查**：`/health`、`/health/ready`、`/health/runtime`，用于探活与依赖健康汇总。\n"
            "- **人物生成任务**：通过 `POST /generate` 提交人物名或问句，生成可交互的人物轨迹页与对话档案；通过 `/task`、`/tasks`、`/task/cancel`、`/task/retry` 管理异步任务生命周期。\n"
            "- **AI 对话代理**：`/api/ai/proxy` 提供模型推理代理，支持普通 JSON 与 Server-Sent Events 流式响应。\n"
            "- **地理编码补点**：`/coords/bulk` 批量刷新地图坐标与古今地名映射。\n"
            "- **静态资源**：根路径与人物页（`/<人物名>.html` 等）走 `/` 与 `/{path}` 静态分发。\n\n"
            "### 通用约定\n"
            "- 全部接口需在允许的 Origin 列表内（CORS 已配置）；调试接口另需运行时调试令牌。\n"
            "- 异步任务统一返回 `task_id`，客户端可通过 `GET /task?id=<task_id>` 轮询或订阅服务端事件获取进度。\n"
            "- 服务端在异常时返回结构化 JSON：`{ok: false, error, ...}`，请根据 HTTP 状态码与 `error` 字段做用户提示。\n"
        ),
        version="1.0.0",
        contact={"name": "故事地图团队", "url": "https://storymap.opendeploy.site"},
    )

    allow_all = "*" in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=512)

    app.include_router(
        health.create_router(
            resolve_cors_origin=resolve_cors_origin,
            static_service=static_service,
            task_service=task_service,
            proxy_service=proxy_service,
        )
    )
    app.include_router(debug.create_router(resolve_cors_origin=resolve_cors_origin, static_service=static_service))
    app.include_router(tasks.create_router(resolve_cors_origin=resolve_cors_origin, task_service=task_service))
    app.include_router(
        generation.create_router(
            resolve_cors_origin=resolve_cors_origin,
            static_service=static_service,
            task_service=task_service,
            proxy_service=proxy_service,
        )
    )
    app.include_router(coords.create_router(resolve_cors_origin=resolve_cors_origin, coords_bulk_update=coords_bulk_update))
    app.include_router(ai_proxy.create_router(resolve_cors_origin=resolve_cors_origin, proxy_service=proxy_service))
    app.include_router(
        portrait.create_router(
            resolve_cors_origin=resolve_cors_origin,
            task_service=task_service,
            proxy_service=proxy_service,
            portrait_service=portrait_service,
        )
    )
    app.include_router(
        static_pages.create_router(
            resolve_cors_origin=resolve_cors_origin,
            static_service=static_service,
            amap_config_js=amap_config_js,
            geovis_config_js=geovis_config_js,
        )
    )

    return app


def run_server(app: FastAPI, port: int, logger) -> None:
    logger.info("server_start port=%s", port)
    print(f"故事地图智能分析服务已启动：http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
