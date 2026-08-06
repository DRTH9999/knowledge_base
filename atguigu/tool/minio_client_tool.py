import json  # json 是 Python 标准库, 用来完成 Python 对象和 JSON 字符串之间的转换.
from atguigu.tool.logger import logger
from minio import Minio  # minio 是第三方 Python 包, 是 MinIO 官方提供的 Python SDK
from atguigu.config.config import MinioConfig  # 从环境变量中读取 MinIO 配置

minio_client = None  # 定义一个模块级的全局变量, 用来存储 minIO客户端.
# None 表示"没有值"或者"尚未初始化", 这里表示: 程序刚导入这个文件时, 还没有创建 MinIO 客户端.

def get_minio_client():
    '''
    # 定义函数, 用来获取 MinIO 客户端.
    # 该函数没有参数, 因为所有连接信息都从 MinIoConfig 中读取, 不需要调用者重复传入.
    # 返回值: 函数最后返回一个 MinIO 客户端对象. 虽然代码没有写返回类型, 但逻辑上相当于: def get_minio_client() -> Minio:
    '''
    global minio_client  # 声明函数内部使用的是模块级全局变量 minio_client .

    if not minio_client:  # 判断客户端是否尚未初始化. 第一次调用时: minio_client = None, 会进入初始化逻辑.
        try:  # 开始捕获异常
            minio_client = Minio(  # 创建一个 Minio 客户端对象, 并保存到全局变量中.
                endpoint=MinioConfig.minio_endpoint,  # endpoint: MinIO 服务器的地址
                access_key=MinioConfig.minio_access_key,  # access_key: MinIO 访问密钥, 可以近似理解为账号或用户名, 当前请求以哪个身份访问服务
                secret_key=MinioConfig.minio_secret_key,  # secret_key: MinIO 密钥, 可以近似理解为密码或密钥, 访问服务时需要提供该密钥
                secure=False,  # secure 决定是否使用 HTTPS 连接, 默认为 True, 使用 HTTPS 连接, 设置为 False, 使用 HTTP 连接
            )

            # 从配置类中获取默认桶名称, 并保存到局部变量 bucket_name .
            bucket_name = MinioConfig.minio_bucket_name

            # 如果桶不存在, 则创建存储桶
            if not minio_client.bucket_exists(bucket_name=bucket_name):  # 等号左边的 bucket_name: 是 bucket_exists() 方法定义的参数名称.
                minio_client.make_bucket(bucket_name=bucket_name)  # .bucket_exists()返回布尔值, 如果桶不存在, 则返回 False.

            # 设置权限, 可以公开读取, 写入需要认证; 即不允许匿名写入, 写入需要MinIO账号认证.
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

        except Exception as e:  # Exception 是 Python 的内置异常类, 表示所有异常的基类. as e : 将捕获到的异常对象保存到变量 e 。
            logger.error("minio客户端初始化失败")
            raise e  # 重新抛出刚才捕获的异常.

    return minio_client  # 返回 MinIO 客户端对象.


"""
# minio_client_tool.py 是一个 MinIO 客户端工厂模块: 第一次调用时根据环境变量创建客户端 / 自动创建桶, 并配置公开读取权限, 
之后通过全局变量复用同一个客户端.

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
  
# json.dumps(policy): 把 Python 字典 policy 转换成 JSON 字符串
  - 为什么需要转换?
    - 因为代码中 policy 是Python字典, 但是 MinIO SDK 的set_bucket_policy() 
    要求 policy 参数是一个符合 S3 Policy 格式的 JSON 字符串 , 不能直接传 Python 字典, 
    所以必须使用: json.dumps(policy)
    
# from minio import Minio
  - 表示: 从 minio 包中导入 Minio 类, 因此后面可以直接写: Minio(...)
  - 如果写成 import minio, 后续使用需要写:minio.Minio(...)
  
# 
# 为什么不直接写 minio_client = Minio(...) ?
  - 因为那样会在模块被导入时立即连接或初始化 MinIO.
  - 当前写法属于懒加载:
    - 文件导入时不初始化;
    - 真正使用时才初始化;
    - 如果项目始终没有使用 MinIO, 就不会创建客户端.

# 为什么必须写 global ?
  - 因为函数中存在赋值: minio_client = Minio(...), 如果不写 global , 函数里的 minio_client 会被认为是局部变量.
  这样在前面执行 if not minio_client: 时, 会出现 UnboundLocalError
  - 所以必须明确告诉 Python: 这里读取和修改的是函数外面定义的全局变量.
  
# 为什么不能直接在 endpoint 中写 http:// ?
  - 因为MinIO SDK 把 地址 和 协议 分开处理: endpoint 决定主机和端口; secure 决定 HTTP 或 HTTPS.
  
# 模块被首次导入:
    ->导入 json, os, Minio, MinIoConfig, logger
    -> 设置 minio_client = None
    -> 定义 get_minio_client 函数
    
  - 注意:定义函数时不会立即执行函数体. 也就是说, 模块刚被导入时不会立即检查桶, 也不会设置策略.
  
# 第一次调用函数 client = get_minio_client():
执行过程:
    进入 get_minio_client
            ↓
    声明使用全局 minio_client
            ↓
    判断 minio_client 是否为空
            ↓ 是
    根据配置创建 Minio 客户端
            ↓
    读取 bucket_name
            ↓
    查询桶是否存在
        ┌───┴────┐
      不存在     存在
        ↓         ↓
      创建桶     跳过创建
        └───┬────┘
            ↓
    构造公开读取策略
            ↓
    字典转换成 JSON
            ↓
    设置桶策略
            ↓
    返回客户端

# 后续调用函数 client2 = get_minio_client():
执行过程:
    进入函数
       ↓
    发现全局客户端已存在
       ↓
    跳过创建、检查桶、设置策略
       ↓
    直接返回原客户端

# 设计思路: 
  - 封装客户端创建 
  
  - 懒加载
  通过: minio_client = None 和 if not minio_client:
  实现真正使用时才初始化.
  
  - 复用客户端: MinIO 客户端通常可以重复使用, 不需要每次上传或下载文件都重新创建.
  因此使用 全局变量 缓存客户端: minio_client = Minio(...)
  可以减少重复对象创建和重复配置, 严格说这是一种“模块级单例”效果, 而不是通过经典单例类实现的单例模式
  
  - 自动准备基础设施
  
  - 配置与代码分离: 连接地址和密钥不写死在该文件中, 而是由 config.py 从环境变量读取.
"""
