# atguigu/import_process/nodes/node_import_milvus.py
import json
from atguigu.tool.logger import logger
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点：数据持久化
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks", "")
        if not chunks:
            logger.error("导入向量库节点: 数据持久化, 未找到chunks")
            raise Exception("导入向量库节点: 数据持久化, 未找到chunks")

        return state


if __name__ == '__main__':
    node = NodeImportMilvus()
    with open(r"", "r", encoding="utf-8") as f:
        chunks = json.load(f)
    init_state = {
        "chunks": chunks
    }
    result = node(init_state)
    logger.info(json_format(result))