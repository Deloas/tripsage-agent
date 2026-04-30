class TripSageError(Exception):
    """项目内可预期异常的基类。"""

    def __init__(self, message: str, code: int = 5000) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class ExternalServiceError(TripSageError):
    """外部接口异常，例如高德、MCP 或大模型服务失败。"""


class ValidationBizError(TripSageError):
    """业务参数校验异常。"""

