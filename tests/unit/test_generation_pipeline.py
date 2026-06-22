from storymap.script.agent.generation_pipeline import (
    FileGenerationCheckpointStore,
    GenerationRetryPolicy,
    GenerationStages,
    build_generation_checkpoint,
    decorate_generation_result,
    extract_generation_failure_info,
    run_generation_with_retry,
)


def test_build_checkpoint_and_decorate_result_include_stage_retry_and_error_fields():
    checkpoint = build_generation_checkpoint(source="markdown_file", resume_stage=GenerationStages.BUILD_PROFILE)

    result = decorate_generation_result(
        {"ok": False},
        stage=GenerationStages.MARKDOWN_GENERATION,
        retry_count=2,
        checkpoint=checkpoint,
        error_info={"classification": "timeout", "retryable": True, "error": "request timed out"},
    )

    assert result["stage"] == GenerationStages.MARKDOWN_GENERATION
    assert result["retry_count"] == 2
    assert result["checkpoint"] == {"source": "markdown_file", "resume_stage": GenerationStages.BUILD_PROFILE}
    assert result["error_classification"] == "timeout"
    assert result["error_retryable"] is True
    assert result["error"] == "request timed out"


def test_extract_generation_failure_info_prefers_client_trace_and_normalizes_negative_cache():
    class DummyClient:
        def latest_trace(self):
            return {"classification": "negative_cache", "retryable": False}

    result = extract_generation_failure_info(DummyClient())

    assert result == {
        "classification": "negative_cache",
        "retryable": False,
        "error": "命中失败缓存，请稍后重试",
    }


def test_run_generation_with_retry_retries_once_for_retryable_failures():
    calls = []
    progress_messages = []
    warnings = []

    class DummyError(RuntimeError):
        classification = "timeout"
        retryable = True

    class DummyLogger:
        def warning(self, message, *args):
            warnings.append(message % args)

    class DummyClient:
        def latest_trace(self):
            return {"classification": "timeout", "retryable": True, "error": "first attempt timeout"}

    def generate(_client, person: str) -> str:
        calls.append(person)
        if len(calls) == 1:
            raise DummyError("boom")
        return "# 李白\n"

    markdown, retry_count, error_info = run_generation_with_retry(
        client=DummyClient(),
        person="李白",
        generate_historical_markdown=generate,
        progress=progress_messages.append,
        logger=DummyLogger(),
        retry_policy=GenerationRetryPolicy(max_attempts=2),
    )

    assert markdown == "# 李白\n"
    assert retry_count == 1
    assert error_info == {}
    assert calls == ["李白", "李白"]
    assert progress_messages == ["李白 首轮生成未完成，准备自动重试", "李白 生成人物档案重试（2/2）"]
    assert warnings == ["generate_markdown_retry person=李白 attempt=1 classification=timeout error=first attempt timeout"]


def test_file_generation_checkpoint_store_persists_and_clears_entries(tmp_path):
    store = FileGenerationCheckpointStore(str(tmp_path / "generation_checkpoints.json"))

    saved = store.save(
        "苏轼",
        requested_person="苏东坡",
        stage=GenerationStages.RENDERING,
        checkpoint=build_generation_checkpoint(source="generated_markdown", resume_stage="markdown_saved"),
        retry_count=1,
        error_info={"classification": "timeout", "retryable": True, "error": "render timed out"},
        ok=False,
    )

    loaded = store.load("苏轼")

    assert loaded["person"] == "苏轼"
    assert loaded["requested_person"] == "苏东坡"
    assert loaded["stage"] == GenerationStages.RENDERING
    assert loaded["retry_count"] == 1
    assert loaded["checkpoint"]["source"] == "generated_markdown"
    assert loaded["error_classification"] == "timeout"
    assert loaded["error_retryable"] is True
    assert loaded["ok"] is False
    assert saved["person"] == loaded["person"]

    store.clear("苏轼")
    assert store.load("苏轼") == {}
