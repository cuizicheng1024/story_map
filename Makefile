.PHONY: help install css lint test check build serve deploy clean

PYTHON ?= python3
PORT   ?= 8765

help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖 (pip + npm)
	pip install -e '.[dev]'
	npm ci

css: ## 构建 Tailwind CSS
	npm run build:css

lint: ## 代码检查 (ruff)
	ruff check storymap/ cli/ tools/ tests/ --select E,F,I

test: ## 运行测试
	pytest tests/ -x --tb=short

check: lint test ## 代码检查 + 测试

build: ## 全量构建 (Markdown → HTML 人物页、首页、索引)
	$(PYTHON) tools/build_all.py

serve: ## 启动开发服务器 (http://127.0.0.1:$(PORT))
	$(PYTHON) storymap/script/story_map.py --serve --port $(PORT)

deploy: build ## 构建并部署到 GitHub Pages + OpenDeploy (CI 入口)
	$(PYTHON) tools/build_all.py

clean: ## 清理构建产物
	rm -rf artifacts/runtime/ data/reports/ data/runtime/ .cache/ cache/ __pycache__/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
