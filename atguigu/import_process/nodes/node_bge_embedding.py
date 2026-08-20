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

    # 从上一步状态中获取 chunks
    def get_chunks(self, state: ImportGraphState):
        chunks = state.get("chunks", "")
        if not chunks:
            logger.error("chunks 为空, 无法进行向量化")
            raise Exception("chunks 为空, 无法进行向量化")

        return chunks

    # 调用大模型进行批量向量化
    def get_chunks_embedding(self, chunks):

        # 按照每批 3 个 chunk 进行处理
        for i in range(0, len(chunks), 3):  # Python 的 range 按步长 3 遍历 chunks，最后一批不足 3 条时，也会正常处理。

            # 截取当前批次，这里没有创建新的 chunk 字典，只是创建了一个指向原始 chunk 字典的列表。
            # 因此，后面对 chunk_k_list 中元素的字段修改，实际上会修改原始的 chunks 。
            chunk_k_list = chunks[i:i + 3]  # 通过列表切片获得当前批次的数据

            # 构造待向量化文本
            # 也就是说，对当前批次中的每个 chunk：
            # 1. 取出 item_name ；2. 取出 content ；3. 将主体名称和正文直接拼接；4. 生成一个待向量化文本；5. 将多个文本组成一个列表。
            chunk_k_text_list = [
                f"{chunk.get('item_name')}{chunk.get('content')}"
                for chunk in chunk_k_list
            ]

            # 调用 BGE-M3 模型
            # 对一批中的三个内容列表，进行向量化操作
            embedding = get_bge_m3_embedding(chunk_k_text_list)  # 获取模型

            # 将向量回填到对应的 chunk
            # 通过 enumerate 同时获得：- 当前 chunk 在批次中的索引 index ；- 当前 chunk 对象chunk 。
            # 这里采用的是“原地回填”的方式：- 不重新创建完整chunks；- 不额外构造一份新的数据结构；- 直接给原来的 chunk 增加向量字段；
            #                          - 后续节点可以直接使用同一个 chunks 列表进行入库。
            for index, chunk in enumerate(chunk_k_list):
                chunk["dense_vector"] = embedding.get("dense")[index]
                chunk["sparse_vector"] = embedding.get("sparse")[index]

        # 备份 chunks , 以备后续流程使用
        with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json", "w", encoding="utf-8") as f:
            # f.write(json.dumps(chunks, ensure_ascii=False, indent=4))
            f.write(json_format(chunks))

        return chunks

    def process(self, state: ImportGraphState):

        # 步骤1: 输入数据校验
        chunks = self.get_chunks(state)

        # 步骤2: 批量生成双向量,
        new_chunks = self.get_chunks_embedding(chunks)

        # 节点只返回 chunks 字段
        # 下游 NodeImportMilvus 接收这个结果后，会读取每个 chunk 中的：
        # - file_title ，- title ，- content ，- item_name ，- part ，- dense_vector ，- sparse_vector
        # 然后将它们批量写入 Milvus 的 chunks 集合。
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


"""
#
这个文件定义了 RAG 知识导入链路中的 BGE-M3 混合向量化节点。
它的上游是主体名称识别节点，下游是 Milvus 入库节点。
节点首先从 LangGraph 的 state 中取得已经完成切片和主体名称标注的 chunks，并检查 chunks 是否为空。
然后按照每批 3 条数据进行处理，把每个 chunk 的 item_name 和 content 拼接成待向量化文本，批量调用 BGE-M3 的文档编码接口。
BGE-M3 会同时返回 dense vector 和 sparse vector，节点按照批次内索引将两种向量回填到对应的 chunk 中，
最后返回包含向量字段的 chunks。
这样下游就可以把文本、主体名称、切片信息以及两类向量一起写入 Milvus。

- 使用双向量是因为稠密向量擅长语义相似度，稀疏向量擅长产品型号、错误码和专业关键词匹配，两者结合可以提升 RAG 的召回效果。
- 批处理主要是为了减少模型调用次数并提高吞吐量，而模型本身通过工具层懒加载并缓存，避免每批重复初始化。


BGE-M3 同时生成两种向量：

- 稠密向量 dense_vector
  - 主要表达文本的整体语义。
  - 适合处理“意思相近但字面表达不同”的问题。
  - 例如“如何更换设备电池”和“设备电池替换方法”可能具有较高语义相似度。
  
- 稀疏向量 sparse_vector
  - 更关注关键词、型号、专业术语和词项匹配。
  - 对产品型号、特殊名词、错误代码等内容比较重要。
  - 例如“HAK180”“E01”“220V”等关键词不能只依赖语义近似。
  
  
# 采用批处理的主要思想是：
    - 避免每条文本都单独调用一次模型；
    - 减少模型调用次数；
    - 提高向量化吞吐量；
    - 同时将单批数据量控制在较小范围内，避免一次处理过多文本导致显存或内存压力。
    
    
# 处理完所有批次，当 for 循环结束后，所有 chunk 都应该拥有：
    - 原始文本字段；
    - 主体名称字段；
    - 稠密向量字段；
    - 稀疏向量字段。
    
整体数据结构大致为：
    {
        "chunks": [
            {
                "title": "...",
                "file_title": "...",
                "content": "...",
                "part": 0,
                "item_name": "...",
                "dense_vector": [...],
                "sparse_vector": {...}
            }
        ]
    }
"""
