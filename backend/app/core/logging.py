from loguru import logger


def configure_logging() -> None:
    """集中配置日志；后续可以扩展到文件轮转和 JSON 日志。"""
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
    )

