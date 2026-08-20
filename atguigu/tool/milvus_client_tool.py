from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker, RRFRanker  # 导入 Milvus SDK 的关键类
from atguigu.config.config import MilvusConfig  # 导入 Milvus 配置类, 应包含连接 URL 等配置信息

milvus_client = None  # 定义模块级全局变量, 用于存储 Milvus 客户端单例.
'''
# 这是一个封装 Milvus 向量数据库操作的工具模块, 主要提供:
    1. Milvus 客户端连接管理(单例模式)
    2. 创建混合检索请求(稠密向量 + 稀疏向量)
    3. 执行混合搜索功能, 对两个检索结果进行加权融合
    
# 执行过程与设计思路
    核心设计理念: 为 RAG(检索增强生成)系统提供混合向量检索能力, 结合稠密向量(语义相似度)和稀疏向量(关键词匹配)提高检索准确性。
'''


def get_milvus_client():
    '''
    获取或创建 Milvus 客户端实例, 典型的单例模式实现, 确保全局唯一连接.
    :return: 返回 MilvusClient 对象
    '''
    global milvus_client  # 声明使用全局变量, 而非局部变量; 允许在函数内修改全局 milvus_client 的值; 如果不声明, milvus_client = ... 会创建局部变量
    if not milvus_client:  # 检查客户端是否已创建(None 为假值); 实现懒加载: 只在首次调用时创建连接; 后续调用直接返回已有实例
        milvus_client = MilvusClient(  # 调用 MilvusClient 构造方法, 创建 MilvusClient 实例
            uri=MilvusConfig.milvus_url  # uri 参数: Milvus 连接服务地址
        )
    return milvus_client


# 创建混合检索请求, 包括稠密向量和稀疏向量的检索请求. 根据稠密向量和稀疏向量, 分别创建两个 Milvus 搜索请求.
def create_reqs(
        dense_data,  # list / array, 必填, 含义: 当前查询文本的稠密向量
        sparse_data,  # dict / sparse matrix, 必填, 含义: 当前查询文本的稀疏向量
        dense_anns_field=None,  # str, 默认值: None, 含义: 表示 Milvus Collection 中存储稠密向量的字段名
        sparse_anns_field=None,  # str, 默认值: None, 含义: 表示 Milvus Collection 中存储稀疏向量的字段名
        limit=10,  # int, 默认值=10, 含义: 表示每一路 AnnSearchRequest 最多取多少个候选结果
        dense_params=None,  # dict, 默认值: None, 含义: 稠密向量检索参数
        sparse_params=None,  # dict, 默认值: None, 含义: 稀疏向量检索参数
        expr=None  # str, 默认值: None, 含义: 标量过滤表达式(如"age > 18")
):
    # 补充设置默认搜索参数, 为没有提供的参数设置默认值
    if not dense_params:
        dense_params = {
            "metric_type": "COSINE"  # 稠密向量使用 COSINE (余弦相似度), 余弦度量不受向量长度影响, 只关注方向, 适合语义相似度计算
        }  # 两个向量方向越接近，文本语义越相似.
        # 在当前业务中, 用户提取名称向量 与 Milvus 商品标准名称向量 进行比较
    if not sparse_params:
        sparse_params = {
            "metric_type": "IP"  # 稀疏向量使用 IP (内积), 稀疏向量的维度很高但大部分为 0, 内积计算高效(只计算非零维度), 反映词频重要性
        }  # 通常结果越大, 代表匹配程度越高

        # 创建稠密向量搜索请求
        dense_reqs = AnnSearchRequest(
            data=[dense_data],  # 为什么用列表包装? - Milvus API 支持批量查询(多个查询向量); 这里只查询一个向量, 所以是单元素列表, dense_data 是向量数据
            anns_field=dense_anns_field,  # 指定在哪个字段上搜索, 对应 Collection 中定义的稠密向量字段
            limit=limit,  # 指定返回结果数量
            param=dense_params,  # 传入稠密向量检索参数
            expr=expr,  # 指定过滤表达式
        )

        # 创建稀疏向量搜索请求
        sparse_reqs = AnnSearchRequest(
            data=[sparse_data],  # 与 稠密向量不同, 稀疏向量数据 是稀疏向量(字典格式,如 {101: 0.5, 523: 0.8} )
            anns_field=sparse_anns_field,
            limit=limit,
            param=sparse_params,
            expr=expr,
        )

        # 返回请求列表, [dense_req, sparse_req]
        # 为什么返回列表 :- hybrid_search 方法需要多个 AnnSearchRequest 对象; - 列表顺序对应后续 Ranker 的权重顺序
        return [dense_reqs, sparse_reqs]  # 返回值: list[ANNSearchRequest]


# 混合搜索函数, 执行混合向量检索. 执行 Milvus 混合向量搜索, 并使用 WeightedRanker 融合多路检索结果.
def search_hybrid(
        collection_name,  # str, 必填, 含义: 要搜索的集合名词
        reqs,  # list[AnnSearchRequest], 必填, 含义: 搜索请求列表, 来自craete_reqs
        ranker=(0.5, 0.5),  # tuple, 默认值: (0.5, 0.5), 含义: 多路搜索结果的融合权重
        limit=10,  # int, 默认值: 10, 含义: 控制 融合排序后 最终返回多少条结果
        output_fields=None  # list[str], 默认值: None, 含义: 搜索结果中额外返回哪些实体字段 (如 ["text", "metadata"])
):
    milvus_client = get_milvus_client()  # - 获取客户端单例, - 确保连接已建立

    # 创建加权排序器, 导入类 WeightedRanker 的作用: 融合多个搜索结果
    weight_ranker = WeightedRanker(ranker[0], ranker[1], norm_score=True)
    '''
    # 参数
    - ranker[0]: 稠密向量权重(默认 0.5)
    - ranker[1]: 稀疏向量权重(默认 0.5)
    - norm_score=True : 表示在进行加权融合前, 对不同搜索路径的分数进行归一化.
      为什么要进行归一化? - 因为两种检索使用的度量不同: 稠密：COSINE, 稀疏：IP, 两者原始分数范围和分布可能不同.
                       - COSINE 的分数范围是 [-1, 1], IP 的分数范围是 [0, 1]
                       - 归一化是为了让不同检索分数具有更可比较的尺度，然后再乘权重。

    
    # 为什么需要权重?
    - 平衡语义搜索和关键词匹配; - 可根据业务调整(如文档搜索偏向关键词，问答偏向语义)
    
    # 计算公式: final_score = 0.5 * dense_score + 0.5 * sparse_score
    '''

    # 真正向 Milvus 发起混合检索
    res = milvus_client.hybrid_search(
        collection_name=collection_name,  # 集合名
        reqs=reqs,  # 搜索请求列表, 传入[dense_reqs, sparse_reqs]
        ranker=weight_ranker,  # 指定使用前面创建的加权融合器
        limit=limit,  # 指定融合后最终返回多少条结果
        output_fields=output_fields,  # 指定返回哪些普通字段
    )  # 执行流程: 调用 MilvusClient 的 hybrid_search 方法, 传入集合名、请求列表、排序器、限制和输出字段, 返回搜索结果
       # - 对每个请求并行执行向量搜索; - 使用 weight_ranker 融合结果; - 按最终分数排序; - 返回 Top-K 结果

    return res  # 把 Milvus 原始搜索结果直接返回给调用者


'''
# 
第一步: 调用 create_reqs() -> 第二步: 补充默认参数 -> 第三步: 构造稠密请求 -> 第四步: 构造稀疏请求 -> 第五步: 返回请求列表 -> 
第六步: 执行混合检索 -> 第七步: 获取客户端单例 -> 第八步: 创建融合器 ->  第九步: Milvus 执行搜索 -> 第十步：返回结果


# 导入 Milvus 核心组件    
from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker, RRFRanker
    各组件含义:
    - MilvusClient : Milvus 轻量级客户端, 提供简化的数据库操作接口
    - AnnSearchRequest : 近似最近邻(Approximate Nearest Neighbor)搜索请求对象, 用于封装单个向量检索请求, 创建 dense_reqs 和 sparse_reqs
                         一个 AnnSearchRequest 对应一个向量字段上的检索请求.
    - WeightedRanker : 加权排序器, 通过权重, 组合多个搜索结果, 用于融合稠密向量和稀疏向量的检索结果.
    - RRFRanker : 倒数排名融合(Reciprocal Rank Fusion)排序器, 一种合算法无需权重的排名融合, WeightedRanker 更关注各路检索分数及权重
为什么导入这些 : 混合检索需要构造多个搜索请求, 并通过排序器融合结果. RRFRanker 主要关注每个结果在不同检索列表中的排名


# 全局客户端变量
milvus_client = None
    - 定义模块级全局变量, 用于存储 Milvus 客户端单例.

    - 为什么用全局变量:
    1. 避免重复创建连接, 节省资源
    2. 实现单例模式, 确保整个应用共用一个连接
    3. Python 的函数可以通过 global 关键字修改模块级变量


# 混合检索请求创建 设计思想

    - 稠密向量用 COSINE(余弦相似度)
      - 稠密向量(如 BERT 编码)通常归一化后用余弦相似度
      - 余弦度量不受向量长度影响, 只关注方向
      - 适合语义相似度计算
      
    - 稀疏向量用 IP(内积)
      - 稀疏向量(如 TF-IDF / BM25)的维度很高但大部分为 0
      - 内积计算高效(只计算非零维度)
      - 反映词频重要性
      

# 结合前面提供的 node_item_name_confirm.py 和 bgem3_client_tool.py, 完整调用链是
用户问题
  ↓
LLM 提取商品名称
  ↓
get_bge_m3_embedding()
  ↓
生成 dense 向量和 sparse 向量
  ↓
create_reqs()
  ↓
生成两路 AnnSearchRequest
  ↓
search_hybrid()
  ↓
MilvusClient.hybrid_search()
  ↓
WeightedRanker 融合结果
  ↓
返回标准商品名称及分数
'''
