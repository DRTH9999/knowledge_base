# atguigu/query_process/nodes/node_search_embedding_hyde.py

from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format

class NodeSearchEmbeddingHyde(NodeBase):
    """
    节点功能：HyDE (Hypothetical Document Embedding)
    先让 LLM 生成假设性答案，再对答案进行向量检索，提高召回率。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_search_embedding_hyde"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        # TODO
        logger.info(f"【{self.name}】节点逻辑")

        # return state
        return {"hyde_embedding_chunks": []}

    def get_rewritten_query(self, state):
        rewritten_query = state.get("rewritten_query")
        item_names = state.get("item_names")
        if not rewritten_query:
            logger.error("改写后的用户问题为空")
            raise ValueError("改写后的用户问题为空")
        if not item_names:
            logger.error("已确认的主体名为空")
            raise ValueError("已确认的主体名为空")
        return item_names, rewritten_query



if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding_hyde = NodeSearchEmbeddingHyde()
    result = node_search_embedding_hyde(init_state)
    logger.info(json_format(result))