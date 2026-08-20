# atguigu/query_process/nodes/node_search_embedding.py

import json

from atguigu.config.config import MilvusConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.milvus_client_tool import create_reqs, search_hybrid


class NodeSearchEmbedding(NodeBase):
    """
    节点功能：基于已确认主体名+改写后的用户问题，执行 Milvus 向量数据库混合检索
    """

    name: str = "node_search_embedding"

    # (取值 + 校验)
    def get_rewitten_query(self, state: QueryGraphState):

        rewritten_query = state.get("rewritten_query")  # 从状态中提取改写后的查询

        if not rewritten_query:
            logger.error("rewritten_query 为空, 必须存在")
            raise Exception("rewritten_query 为空, 必须存在")

        item_names = state.get("item_names")  # 提取主体名称列表

        if not item_names:
            logger.error("item_names 为空, 必须有值")
            raise Exception("item_names 为空, 必须有值")

        return item_names, rewritten_query  # 返回类型 ： Tuple[List[str], str]

    def get_embedding_chunks(self, item_names, rewritten_query):
        '''
        获取向量数据库中，和问题最相关的文档片段
        :param item_names: 已确认的主体名/商品名列表
        :param rewritten_query: 改写后的问题
        '''
        # 将改写后的查询文本转换为向量, 参数: 列表形式[rewritten_query], 因为函数支持批量向量化.
        embeddings = get_bge_m3_embedding([rewritten_query])  # 返回值 embeddings 是一个 dict, 包含 dense 和 sparse 两个向量

        # 获取collection名称(Milvus中的表名)
        collection_name = MilvusConfig.chunks_collection

        # 取第一个(也是唯一一个)文本的稠密向量. 取[0] 是因为输入是单个查询的列表, 返回也是列表, 取第一个元素, 类型: List[float]
        dense_data = embeddings.get("dense")[0]  # 得到第一个查询的稠密向量

        # 取第一个稀疏向量
        sparse_data = embeddings.get("sparse")[0]  # 得到第一个查询的稀疏向量

        # 构建 Milvus 标量字段过滤表达式
        # Milvus 的过滤表达式要求: in 后面是字符串格式的列表
        # 过滤确保只检索指定主体的文档, 提高准确性
        expr = f"item_name in {json.dumps(item_names, ensure_ascii=False)}"  # 将列表转为JSON字符串, 保留中文字符.

        # 创建检索请求对象
        reqs = create_reqs(
            dense_data=dense_data,  # 稠密向量数据 (用于语义相似度检索)
            sparse_data=sparse_data,  # 稀疏向量数据 (用于关键词匹配)
            dense_anns_field="dense_vector",  # Milvus中存储稠密向量的字段名
            sparse_anns_field="sparse_vector",  # Milvus中存储稀疏向量的字段名
            expr=expr,  # 标量过滤表达式
        )  # 返回值：请求对象列表, 包含两个检索请求(dense和sparse)

        # 执行混合检索并重排序
        res = search_hybrid(
            collection_name=collection_name,  # 要检索的collection
            reqs=reqs,  # 检索请求列表
            ranker=(0.8, 0.2),  # 重排序权重, dense占80%, sparse占20%.
            output_fields=["id", "title", "file_title", "content", "item_name"],  # 返回哪些字段
            limit=10,  # 返回前10条结果
        )  # 返回值: 嵌套列表[[结果1, 结果2, ...]]，外层列表对应每个查询; 内层列表是检索结果, 包含id, score, title, content, item_name等字段

        # 格式化结果
        embedding_chunks = [
            {
                **item.get("entity", {}),  # 解包, 取出命中文档的实体字段, entity 由 Milvus 搜索结果生成并返回的
                # "entity" 是 Milvus 中被检索命中的那一条数据记录里, 需要返回的业务字段集合.
                # 可以把 Milvus 的 Collection 理解成数据库中的"表", 其中每一行数据就是一个实体(entity)
                # entity 的本质: 通常是一个字典, 用于保存命中文档的业务数据
                "score": item.get("distance"),  # 提取相似度分数
                "source": "local",  # 标记数据来源为本地库
            }
            for item in res[0]  # 取出第一个查询的全部结果, 逐条遍历命中结果(第一个查询的结果列表)
        ]

        # 将检索结果包装成字典返回
        return embedding_chunks

    def process(self, state: QueryGraphState):

        # 获取改写后的用户问题与已确认的主体名
        item_names, rewritten_query = self.get_rewitten_query(state)

        # 执行混合检索, 获取切片
        embedding_chunks = self.get_embedding_chunks(item_names, rewritten_query)

        return {
            "embedding_chunks": embedding_chunks
        }


if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding = NodeSearchEmbedding()
    result = node_search_embedding(init_state)
    logger.info(json_format(result))

"""
# 这是一个RAG(检索增强生成)系统中的 向量检索节点, 负责在 Milvus 向量数据库中执行混合检索(稠密向量 + 稀疏向量), 
  根据改写后的用户问题和确认的主体名称, 检索出最相关的文档片段.

# 输入： item_names (已确认的主体名/商品名列表) + rewritten_query (改写后的用户问题)
# 输出： embedding_chunks (从 Milvus 向量库里检索回来的, 问题最相关的若干文本切片)


# entity 里面有哪些字段, 主要由以下两点决定:
    1.Milvus Collection 中定义并存储了哪些字段;
    2.output_fields 参数要求返回哪些字段.


# 本程序只有一个查询: get_bge_m3_embedding([rewritten_query]), 
这里传入的依然是一个列表: [rewritten_query], 因此, 即使这个列表中只有一个查询, 返回结果也仍按批量格式组织:
    res = [
        [查询0的全部检索结果]
    ]
所以要使用: res[0] 取出唯一那个查询对应的命中结果列表.

再例如一次提交三个查询: 
    queries = [
        "BrotherHAK180烫金机如何使用",
        "BrotherHAK180烫金机如何换烫金纸",
        "BrotherHAK180烫金机温度怎么设置",
    ]
假设每个查询返回三条结果, 那么结果可能是: 
    res = [
        [
            查询1的结果1,
            查询1的结果2,
            查询1的结果3,
        ],
        [
            查询2的结果1,
            查询2的结果2,
            查询2的结果3,
        ],
        [
            查询3的结果1,
            查询3的结果2,
            查询3的结果3,
        ],
    ]
res[0]表示: 第1个查询的所有结果


# 总结: 之所以取 [0], 是因为: Milvus 搜索接口按照批量查询返回结果, 外层表示"第几个查询", 
内层表示"这个查询命中的多条文档"; 当前程序只提交了一个查询, 所以使用 res[0] 取得第一个也是唯一一个查询的全部命中结果.
"""
