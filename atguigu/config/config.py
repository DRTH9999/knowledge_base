import os
from dotenv import load_dotenv

# load_dotenv(override=True)
"""
# 这个api方法会自动爬楼, 去寻找项目当中的.env文件, 并加载其中的环境变量.
# override=True 说明 .env 文件当中与系统环境变量同名的配置, 会覆盖系统环境变量.
# 如果为True, 代表 .env文件的配置会覆盖系统环境变量; 如果为False, 则代表 .env文件的配置不会覆盖系统环境变量.
"""

# 使用绝对路径加载 .env
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
load_dotenv(dotenv_path=env_path, override=True)


class MineruConfig:
    mineru_token = os.getenv("MINERU_TOKEN")
    mineru_base_url = os.getenv("MINERU_BASE_URL")


class LLMConfig:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_api_base = os.getenv("OPENAI_API_BASE")
    llm_default_model = os.getenv("LLM_DEFAULT_MODEL")
    llm_default_temperature = float(os.getenv("LLM_DEFAULT_TEMPERATURE"))
    vl_model = os.getenv("VL_MODEL")
    item_model = os.getenv("ITEM_MODEL")


# 定义 MinioConfig 配置类
class MinioConfig:
    minio_endpoint = os.getenv("MINIO_ENDPOINT")
    minio_access_key = os.getenv("MINIO_ACCESS_KEY")
    minio_secret_key = os.getenv("MINIO_SECRET_KEY")
    minio_bucket_name = os.getenv("MINIO_BUCKET_NAME")
    minio_img_dir = os.getenv("MINIO_IMG_DIR")


if __name__ == "__main__":
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
    print(os.path.dirname(__file__))
    print(env_path)
