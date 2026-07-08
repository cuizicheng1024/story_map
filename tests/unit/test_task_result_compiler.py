from storymap.script.runtime.task_result_compiler import compile_task_outcome


def test_compile_task_outcome_adds_public_urls(monkeypatch):
    monkeypatch.setenv("STORYMAP_PUBLIC_BASE_URL", "https://storymap.cn")

    outcome = compile_task_outcome(
        resolved_targets=["李白", "杜甫"],
        results=[
            {
                "ok": True,
                "person": "李白",
                "markdown_path": "storymap/examples/story/李白.md",
                "html_path": "artifacts/story_map/李白.html",
                "exports": {"geojson": "artifacts/story_map/李白.geojson", "csv": "artifacts/story_map/李白.csv"},
            },
            {
                "ok": True,
                "person": "杜甫",
                "markdown_path": "storymap/examples/story/杜甫.md",
                "html_path": "artifacts/story_map/杜甫.html",
            },
        ],
        overlaps=[],
        duration="1s",
        conclusion="ok",
        multi_html_path="artifacts/story_map/多人物合并视图_demo.html",
        multi_exports={"geojson": "artifacts/story_map/多人物合并视图_demo.geojson"},
        relative_path=lambda value: str(value or ""),
        meta={},
    )

    first = outcome.summary["files"][0]
    assert first["public_html"] == "https://storymap.cn/%E6%9D%8E%E7%99%BD.html"
    assert first["public_geojson"] == "https://storymap.cn/%E6%9D%8E%E7%99%BD.geojson"
    assert first["public_csv"] == "https://storymap.cn/%E6%9D%8E%E7%99%BD.csv"
    assert outcome.summary["multi"]["public_html"] == "https://storymap.cn/%E5%A4%9A%E4%BA%BA%E7%89%A9%E5%90%88%E5%B9%B6%E8%A7%86%E5%9B%BE_demo.html"
