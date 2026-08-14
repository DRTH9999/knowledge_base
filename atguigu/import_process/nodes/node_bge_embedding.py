# atguigu/import_process/nodes/node_bge_embedding.py
import json
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.logger import logger
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format


class NodeBGEEmbedding(NodeBase):
    """
    混合向量化节点：使用 BGE-M3 模型将文本转换为向量
    """
    name = "node_bge_embedding"

    def get_chunks(self, state: ImportGraphState):
        chunks = state.get("chunks", "")
        if not chunks:
            logger.error("chunks 为空, 无法进行向量化")
            raise Exception("chunks 为空, 无法进行向量化")

        return chunks

    # 调用大模型进行批量向量化
    def get_chunks_embedding(chunks):
        for i in range(0, len(chunks), 3):
            chunk_k_list = chunks[i:i + 3]
            chunk_k_list = [f"{chunk.get('item_name')}{chunk.get('content')}" for chunk in chunk_k_list]

            # 对一批中的三个内容列表, 进行向量化操作
            embedding = get_bge_m3_embedding(chunk_k_list)
            for index, chunk in enumerate(chunk_k_list):
                chunk["dense_vector"] = embedding.get("dense")[index]
                chunk["sparse_vector"] = embedding.get("sparse")[index]

        # 备份 chunks , 以备后续流程使用
        with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json", "w", encoding="utf-8"):
            # f.write(json.dumps(chunks, ensure_ascii=False, indent=4))
            f.write(json_format(chunks))

        return chunks

    def process(self, state: ImportGraphState):

        # 步骤1: 输入数据校验
        chunks = self.get_chunks(state)

        # 步骤2: 批量生成双向量,
        new_chunks = self.get_chunks_embedding(chunks)

        return {
            "chunks": new_chunks
        }


if __name__ == '__main__':
    node = NodeBGEEmbedding()
    with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json", "r", encoding="utf-8") as f:
        chunks = json.load(f)

    init_state = {
        "chunks": chunks
    }
    result = node(init_state)
    logger.info(json_format(result))
