# atguigu/query_process/nodes/node_search_embedding.py

from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format

class NodeSearchEmbedding(NodeBase):

    """
    节点功能：基于已确认主体名+改写后的用户问题，执行Milvus向量数据库混合检索
    """

    name: str = "node_search_embedding"

    def process(self, state: QueryGraphState):
        pass

    def get_rewitten_query(state: QueryGraphState):
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("rewritten_query 为空, 必须存在")
            raise Exception("rewritten_query 为空, 必须存在")

        item_names = state.get("item_names")
        if not item_names:
            logger.error("item_names 为空, 必须有值")
            raise Exception("item_names 为空, 必须有值")



if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding = NodeSearchEmbedding()
    result = node_search_embedding(init_state)
    logger.info(json_format(result))