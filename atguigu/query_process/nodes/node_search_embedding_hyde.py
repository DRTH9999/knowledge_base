# atguigu/query_process/nodes/node_search_embedding_hyde.py
import json
from langchain.chat_models import init_chat_model
from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.prompt import HYDE_PROMPT
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding  # 调用 BGE-M3 Embedding 模型, 把文本转换成稠密向量和稀疏向量
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.milvus_client_tool import create_reqs, search_hybrid  # search_hybrid 用于真正执行 Milvus 混合检索
# create_reqs() 用于创建 Milvus 混合搜索请求, 它会创建两条请求：
# 1. 对 dense_vector 字段进行稠密向量搜索； 2. 对 sparse_vector 字段进行稀疏向量搜索。


class NodeSearchEmbeddingHyde(NodeBase):
    """
    节点功能：HyDE (Hypothetical Document Embedding)
    先让 LLM 生成假设性答案，再对答案进行向量检索，提高召回率。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_search_embedding_hyde"

    def get_rewritten_query(self, state):
        '''
        - 从状态中读取字段；
        - 检查字段是否为空。
        '''
        # 读取改写后的问题
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("改写后的用户问题为空")
            raise ValueError("改写后的用户问题为空")

        # 读取商品名称列表
        item_names = state.get("item_names")
        # 检查商品名称列表是否为空, 以下情况都会失败: None, []
        if not item_names:
            logger.error("已确认的主体名 item_names 为空, 必须存在! ")
            raise ValueError("已确认的主体名 item_names 为空, 必须存在! ")

        return rewritten_query, item_names  # 返回类型 tuple[list[str], str]

    # 定义生成 HyDE 假设答案的方法, 最终返回的是"问题和答案的合并文本"
    def get_hyde_answer(self, rewritten_query):

        # 创建 Langchain 聊天模型对象, 返回一个 Langchain 聊天模型实例
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature
        )

        # 构造发送给聊天模型的消息列表
        message = [
            {
                "role": "user", "content": HYDE_PROMPT.format(rewritten_query=rewritten_query)
            }  # 调用字符串的 format() 方法, 将模板中的{rewritten_query} , 替换为实际的用户查询.
            # 使用方法: 模板字符串.format(占位符名称=实际值), 返回值: str, 不会修改原始 HYDE_PROMPT , 而是返回一个新字符串.
        ]

        # 同步调用大模型
        res = llm.invoke(input=message)

        hyde_answer = res.content  # 访问模型响应对象的 content 属性, content 属性, 表示模型生成的正文, 类型: str

        # 拼接 改写后的用户问题 和 大模型市场的假设答案
        # 为什么保留原问题而不是只嵌入假设答案？
        # 1.因为原问题中通常包含： - 商品型号； - 用户意图； - 精确关键词； - 原始约束。
        # 2.假设答案则补充： - 说明书式表达； - 操作步骤； - 专业术语； - 可能出现在知识库正文中的词。
        # 3.两者合并，可以同时保留查询意图和答案语义。
        merged_query = f"{rewritten_query} {hyde_answer}"  # 在字符串中直接插入变量值

        # 返回合并后的检索文本
        return merged_query

    # 定义 HyDE 混合向量检索方法
    # 方法作用：- 生成 BGE-M3 向量；- 创建商品过滤条件；- 创建两路 Milvus 请求；- 进行加权混合检索；- 整理结果格式。
    def get_hyde_embedding_chunks(self, item_names, merged_query):

        # 把 merged_query 放进列表后传给 Embedding 函数
        # 为什么传入列表 [merged_query] 而不是单个字符串 merged_query ?
        # 因为 Embedding 函数设计为批量接口, 参数是文本列表, 要求传入一个列表 list[str], 而不是单个字符串.
        embeddings = get_bge_m3_embedding([merged_query])

        # 从 Milvus 配置中取得知识库切片集合的名称
        collection_name = MilvusConfig.chunks_collection

        dense_data = embeddings.get("dense")[0]  # 取得第一条文本对应的稠密向量, 类型: list[float]
        sparse_data = embeddings.get("sparse")[0]  # 取得第一条文本对应的稀疏向量, 类型: dict[int, float]

        # 生成 Milvus 的标量过滤表达式
        # 向量搜索负责判断"语义是否相似"; 标量过滤负责限定"必须属于指定商品"
        # 过滤条件, 确保只检索指定商品的文档.
        # 第1步: 将 item_names 列表序列化成 Milvus 过滤表达式中的列表文本.  json.dumps(item_names, ensure_ascii=False)
        # 第2步: 使用 f-string 把 JSON 文本插入 Milvus 表达式.  f"item_name in {...}"
        # in 表示: 只允许 item_name 字段值存在于给定列表中的记录, 参与检索, 防止搜索到其他商品的说明书切片
        expr = f"item_name in {json.dumps(item_names, ensure_ascii=False)}"

        # 调用 create_reqs() 创建 Milvus 搜索请求列表
        # 内部相当于创建: 请求一：搜索 dense_vector，使用 COSINE; 请求二：搜索 sparse_vector，使用 IP
        # 稠密向量擅长捕捉整体语义；稀疏向量擅长捕捉型号、专有词、关键词等精确匹配信息
        reqs = create_reqs(
            dense_data=dense_data,  # 查询的稠密向量
            sparse_data=sparse_data,  # 查询的稀疏向量
            dense_anns_field="dense_vector",  # Milvus 稠密向量字段名称
            sparse_anns_field="sparse_vector",  # Milvus 稀疏向量字段名称
            expr=expr,  # 商品名称过滤表达式
        )

        # 执行 Milvus 混合搜索
        res = search_hybrid(
            collection_name=collection_name,  # 指定搜索哪个 Milvus 集合
            reqs=reqs,  # 传入前面构造的稠密和稀疏搜索请求
            ranker=(0.8, 0.2),
            output_fields=["id", "title", "file_title", "content", "item_name"],  # 指定搜索命中后需要返回哪些实体字段
            limit=10,  # 表示混合排序后最多返回 10 条结果
        )  # 返回值: res, 它是按“查询文本”分组的二维结果, 由于这里只提交了一条查询，所以后面使用：res[0], 取得第一条查询对应的命中列表。

        # 整理搜索结果, hyde_embedding_chunks 列表
        # 把 Milvus 原始结果转换成项目统一的知识切片格式
        hyde_embedding_chunks = [
            {
                **item.get("entity", {}),  # 取得命中结果中的实体字段, {} 是默认值, 如果没有 entity ，则返回空字典，避免直接访问：item["entity"]
                "score": item.get("distance"),  # 取得 Milvus 返回的混合搜索分数，并统一命名为 score
                "source": "local",  # 表示这条内容来自本地 Milvus 知识库，而不是 Web 搜索
            }

            for item in res[0]  # 遍历第一条查询对应的所有搜索结果
        ]

        # 返回整理后的知识切片列表, 返回值类型: list[dict]
        return hyde_embedding_chunks

    def process(self, state: QueryGraphState):
        # 获得重写的问题
        rewritten_query, item_names = self.get_rewritten_query(state)

        # 生成 HyDE 假设答案, 合并 改写后的问题, 得到 merged_query
        merged_query = self.get_hyde_answer(rewritten_query)

        # 混合向量检索, 获取切片
        hyde_embedding_chunks = self.get_hyde_embedding_chunks(item_names, merged_query)

        return {
            "hyde_embedding_chunks": hyde_embedding_chunks
        }


if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding_hyde = NodeSearchEmbeddingHyde()

    result = node_search_embedding_hyde(init_state)

    logger.info(json_format(result))

"""
# 文件作用 
这个文件实现了一个 HyDE 向量检索节点 . HyDE 全称是 Hypothetical Document Embeddings, 假设性文档嵌入. 
它解决的问题是:
 - 用户问题通常比较短，例如“Brother HAK180 烫金机如何使用”。
 - 知识库切片通常是说明书式、答案式的长文本。
 - 直接用短问题搜索长文档，问题和文档之间可能存在语义表达差异。
 - HyDE 先让大语言模型根据问题生成一段“假设答案”。
 - 再把“原问题 + 假设答案”转换成向量。
 - 使用这个内容更丰富的向量搜索知识库，提高相关文档的召回概率。
 
# 执行流程:

获取改写后的问题和商品名称
        ↓
调用大模型，生成假设答案
        ↓
拼接“问题 + 假设答案”
        ↓
生成 BGE-M3 稠密向量和稀疏向量
        ↓
限定 item_name，在 Milvus 中进行混合搜索
        ↓
稠密结果权重 0.8，稀疏结果权重 0.2
        ↓
整理搜索结果
        ↓
返回 hyde_embedding_chunks


# 读取并校验状态 -> 构造 HyDE 提示词 -> 调用大模型 -> 合并问题与假设答案 -> 生成 BGE-M3 稠密向量和稀疏向量 
-> 构造过滤条件, 限定 item_name -> 创建两路搜索请求 -> 执行混合搜索ranker=(0.8, 0.2) -> 统一结果格式, 整理搜索结果 
-> 返回 hyde_embedding_chunks


# 最终执行流程与设计思路
该节点的完整执行过程如下：

1.外部工作流调用节点对象：
    node_search_embedding_hyde(init_state)
    
2.NodeBase.__call__() 预计会转调当前类的：
    process(state)
    
3.process() 调用 get_rewritten_query()：
    从状态中获取 rewritten_query；
    获取 item_names；
    两者任一为空则记录错误并抛出 ValueError。
    
4.process() 调用 get_hyde_answer(rewritten_query)：
    用 HYDE_PROMPT 构造提示词；
    初始化 LangChain 聊天模型；
    调用 LLM；
    得到 res.content 中的假设性答案  
    拼接成 merged_query。
    
5.process() 调用 get_hyde_embedding_chunks(item_names, merged_query)：
    使用 BGE-M3 为合并文本生成 dense 和 sparse 向量；
    用 item_names 生成 Milvus 过滤条件；
    构造 dense 与 sparse 混合检索请求；
    以 0.8 : 0.2 权重融合语义检索和关键词检索；
    最多返回 10 条结果；
    整理结果字段并增加 score、source。
    
6.process() 返回：
    {
        "hyde_embedding_chunks": hyde_embedding_chunks
    }
    
7.整体设计上，这个类将“输入校验”“LLM 生成”“向量化”“Milvus 检索”“结果规范化”拆成了三个方法，职责边界清楚：
 
    get_rewritten_query()：保证输入完整；
    get_hyde_answer()：生成更适合检索的语义文本；
    get_hyde_embedding_chunks()：向量检索并转换结果；
    process()：负责编排整个节点执行顺序。
"""
