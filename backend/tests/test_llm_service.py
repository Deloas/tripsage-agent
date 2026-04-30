from app.services.llm_service import LlmService


def test_llm_status_does_not_expose_api_key():
    """LLM 诊断信息不能泄露本地 API Key。"""
    status = LlmService().config_status()

    assert status["provider"]
    assert status["model"]
    assert "api_key" not in status
    assert "LLM_API_KEY" not in str(status)
