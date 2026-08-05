import json  # json 是 Python 标准库, 用来完成 Python 对象和 JSON 字符串之间的转换.
from atguigu.tool.logger import logger
from minio import Minio  # minio 是第三方 Python 包, 是 MinIO 官方提供的 Python SDK
from atguigu.config.config import MinioConfig  # 从环境变量中读取 MinIO 配置

minio_client = None


def get_minio_client():
    global minio_client
    try:
        if not minio_client:
            minio_client = Minio(
                endpoint=MinioConfig.minio_endpoint,
                access_key=MinioConfig.minio_access_key,
                secret_key=MinioConfig.minio_secret_key,
                secure=False,  # 禁用HTTPS
            )

        bucket_name = MinioConfig.minio_bucket_name

        # 创建存储桶
        if not minio_client.bucket_exists(bucket_name=bucket_name):
            minio_client.make_bucket(bucket_name=bucket_name)

        # 设置权限, 可以公开读取, 写入需要认证.
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                    "Resource": f"arn:aws:s3:::{bucket_name}",
                },
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/*",
                },
            ],
        }
        minio_client.set_bucket_policy(bucket_name=bucket_name, policy=json.dumps(policy))
    except Exception as e:
        logger.error("minio客户端初始化失败")
        raise e

    return minio_client


"""
# 文件整体作用
  - 这个文件负责:
    1. 根据 环境变量 创建 MinIO 客户端.
    2. 检查指定的存储桶是否存在.
    3. 如果桶不存在, 则自动创建.
    4. 设置桶策略, 使对象可以被公开读取.
    5. 缓存客户端, 避免每次调用都重新初始化.
    6. 初始化失败时记录错误并抛出异常.
  - 核心设计是: 懒加载 + 单例缓存 + 自动初始化存储桶
  - 调用方不直接执行 Minio(...) , 而是统一调用: client = get_minio_client()
  
# 
"""
