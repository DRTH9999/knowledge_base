from pymilvus.model.hybrid import BGEM3EmbeddingFunction  # 核心依赖
from atguigu.config.config import EmbeddingConfig  # 导入项目配置类

# from typing import List
# from atguigu.tool.json_format_tool import json_format
# from atguigu.tool.logger import logger


bge_m3_model = None  # 作用: 声明一个模块级别的全局变量, 初始值为 None , 用于缓存 BGE-M3 模型实例
'''
这是实现 单例模式(懒汉式) 的缓存变量, 因为模型加载非常耗时(加载模型权重到 GPU/CPU 内存), 不能在每次调用 embedding 时都重新加载.
用模块级变量保存实例, 达到"只加载一次, 重复使用"的效果.
'''


def get_bge_m3_model():  # 获取 BGE-M3 模型实例的工厂函数, 实现了线程不安全的懒汉式单例.

    global bge_m3_model  # 声明 函数内部要修改全局变量 bge_m3_model , 而不是创建一个局部变量.
    # Python 中, 如果函数内对变量赋值, 默认会创建局部变量. 必须用 global 关键字告诉解释器: "我要修改模块级别那个 bge_m3_model ".

    if not bge_m3_model:  # 检查模型是否已经加载过.  None 在布尔上下文中为 False , 所以 not None 为 True.
                          # 是懒加载(Lazy Initialization)的核心判断——只在第一次调用时加载模型, 后续调用直接返回已缓存的实例.
        bge_m3_model = BGEM3EmbeddingFunction(  # 创建 BGEM3EmbeddingFunction 实例.
            model_name=EmbeddingConfig.bge_m3_path,  # 本地模型权重文件夹路径
            device=EmbeddingConfig.bge_device,  # 推理设备, 如 cuda:0 或 cpu
            use_fp16=EmbeddingConfig.bge_fp16  # 是否使用半精度推理(FP16), 可以减少约一半的显存占用, 加速推理
        )
    return bge_m3_model  # 返回模型实例, 调用方通过此函数拿到模型引用, 后续调用 encode_documents()


def get_bge_m3_embedding(texts: list[str]):  # 核心接口函数, 接收一批文本, 返回混合向量(稠密+稀疏)
    bge_m3_model = get_bge_m3_model()  # 获取 BGE-M3 模型实例, (首次调用会触发加载, 后续从缓存中取得)
    embedding = bge_m3_model.encode_documents(texts)  #调用 BGE-M3 的 encode_documents() 方法.
    """
    - 调用 BGE-M3 模型的 encode_documents() 方法, 将文本列表 编码为向量. 返回值是一个字典, 包含两个 key:
    "dense" : 稠密向量列表, 每条文本对应一个 numpy 数组(如 shape (1024,) 的 float32 数组).
    "sparse" : 稀疏向量列表, 每条文本对应一个 scipy.sparse 对象, 包含 indices (非零维度索引)和 data (对应的权重值).
    
    - 这是模型推理的核心调用. 之所以叫 encode_documents 而非 encode_queries ,是因为文档侧和查询侧的编码在 BGE-M3 中
    可能有不同的处理策略(如是否加指令前缀).
    """
    # print(embedding)
    # print(embedding.get("dense"))
    # print(embedding.get("sparse"))

    # 遍历稠密向量, 查看其本质类型为numpy.ndarray
    # for dense_item in embedding.get("dense"):
    #     print(dense_item, type(dense_item))

    # 遍历稀疏向量, 查看其本质类型为 CSR (Compressed Sparse Row, 压缩稀疏行) 格式
    # for sparse_item in embedding.get("sparse"):
    #     # print(sparse_item, type(sparse_item))
    #     print(sparse_item.__dict__)

    # return {
    #      "dense":[
    #          list([float(item) for item in dense_item])
    #                     for dense_item in embedding.get("dense")],
    #      "sparse":[
    #          dict(zip(
    #              [int(indice) for indice in sparse_item.indices],
    #              [float(data) for data in sparse_item.data]
    #          ))
    #          for sparse_item in embedding.get("sparse")
    #      ]
    #  }

    # 简化版
    # 格式化并返回结果
    # 因为 NumPy 数组不能直接被标准 json.dumps() 序列化, 所以需要先转换为 Python 原生类型 list, 才能正确序列化为 JSON 格式.
    return {
        "dense": [dense_item.tolist() for dense_item in embedding.get("dense")],  # 将稠密向量从 numpy 数组转为 Python 原生 list.
        "sparse": [
            dict(zip(
                sparse_item.indices.tolist(),
                sparse_item.data.tolist()
            ))
            for sparse_item in embedding.get("sparse")  # - 作用 : 将稀疏向量转为 {索引: 权重} 的字典格式.
        ]
    }


# if __name__ == '__main__':
#     texts = [
#         "hello world",
#         "hello milvus"
#     ]
#     result = get_bge_m3_embedding(texts)
#     print(result)
#     logger.info(json_format(result))


'''
# 这是一个 BGE-M3 嵌入模型客户端工具, 用于将文本转化为向量(embedding). 
  BGE-M3 是一个支持 稠密向量(dense) 和 稀疏向量(sparse) 的混合嵌入模型, 常用于 RAG(检索增强生成) 系统中, 为 Milvus 向量数据库生成向量.
  
# from typing import List
  - 作用: 从 Python 标准库中引入 List 泛型类型, 用于函数签名中标注 "字符串列表" 类型.

# from pymilvus.model.hybrid import BGEM3EmbeddingFunction
  - 作用: 从 pymilvus (milvus向量数据库的Python SDK) 中引入 BGEM3EmbeddingFunction 类.
  - 这是核心依赖, BGEM3EmbeddingFunction 封装了 BGE-M3 模型的加载和推理逻辑, 调用encode_documents() 即可将文本转为稠密+稀疏混合向量.
  使用Milvus 官方封装的好处是开箱即用, 不需要自己处理模型加载 / tokenizer / 推理等细节.
  
# from atguigu.config.config import EmbeddingConfig
  - 作用: 导入项目配置类 EmbeddingConfig , 其中包含 bge_m3_path (模型路径) / bge_device (设备, 如 cuda:0 或 cpu ) /
    bge_fp16 (是否使用半精度) 等配置项.
  - 实现: 配置与代码分离, 方便在不同环境(开发/生产/不同机器) 切换模型路径和设备, 无需修改代码.

# 稠密矩阵的转换: 由 numpy 的 ndarray 类型转换为 Python 的 list 列表形式
  - embedding.get("dense") 返回的是 numpy 数组列表（如 [np.array([0.1, 0.2, ...]), ...] ）.
  - .tolist() 是 numpy 的最高效转换方法, 直接将底层 C 数组拷贝为 Python list, 比逐元素 float(item) 快得多.
  - 转成 Python 原生类型后可以直接 JSON 序列化, 便于网络传输或存入数据库. 
  
# 稀疏矩阵的转换: 将稀疏向量转为 {索引: 权重} 的字典格式.
  - sparse_item 是 scipy 稀疏矩阵对象.  .indices 是非零维度的索引数组 (如 [3, 15, 200] ),  .data 是对应的权重值 (如 [0.5, 0.3, 0.8] ).
  - .tolist() 将 numpy/scipy 数组转为 Python list.
  - zip(indices_list, data_list) 将索引和权重一一配对.
  - dict(...) 转为 {3: 0.5, 15: 0.3, 200: 0.8} 这种字典格式.
  - 这是 Milvus 混合检索所需的稀疏向量输入格式.
  
# 调用 get_bge_m3_embedding(["text1", "text2"])
      │
      ├─► get_bge_m3_model()
      │     ├─ 第一次调用? → 创建 BGEM3EmbeddingFunction 实例 → 缓存到全局变量
      │     └─ 非第一次?   → 直接返回缓存的实例
      │
      ├─► model.encode_documents(texts)
      │     输出: {"dense": [np.array, ...], "sparse": [sparse_matrix, ...]}
      │
      ├─► 格式转换
      │     dense: np.array → .tolist() → Python list
      │     sparse: sparse_matrix → zip(indices, data) → dict
      │
      └─► 返回 {"dense": [...], "sparse": [{...}, ...]}

#
"sparse": [
    dict(zip(
        sparse_item.indices.tolist(),
        sparse_item.data.tolist()
    ))
    for sparse_item in embedding.get("sparse")
]

等价于:

sparse_result = []
sparse_embeddings = embedding.get("sparse")
  
for sparse_item in sparse_embeddings:
    indices = sparse_item.indices.tolist()
    data = sparse_item.data.tolist()
  
    pairs = zip(indices, data)
    sparse_dict = dict(pairs)
  
    sparse_result.append(sparse_dict)
      
# 最终返回值结果
    {
        "dense": list[list[float]],
        "sparse": list[dict[int, float]],
    }
'''
