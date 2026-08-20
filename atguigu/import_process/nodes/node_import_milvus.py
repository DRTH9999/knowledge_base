# atguigu/import_process/nodes/node_import_milvus.py
import json
from pymilvus import DataType
from atguigu.config.config import MilvusConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点：数据持久化
    """
    name = "node_import_milvus"

    # 读取上游向量化结果
    def get_chunks(self, state):
        # 读取上游 chunks; 从第一个 chunk 推断稠密向量维度; 从第一个 chunk 获取文件标题

        chunks = state.get("chunks", "")

        if not chunks:
            logger.error("导入向量库节点: 数据持久化, 未找到chunks")
            raise Exception("导入向量库节点: 数据持久化, 未找到chunks")

        dense_vector = chunks[0].get("dense_vector")

        if not dense_vector:
            logger.error("导入向量库节点: chunks 缺少 dense_vector, 请先执行 node_bge_embedding 向量化节点")
            raise Exception("导入向量库节点: chunks 缺少 dense_vector, 请先执行 node_bge_embedding 向量化节点")

        # Milvus 在创建 FLOAT_VECTOR 字段时必须指定维度，所以该节点通过第一个 chunk 推断向量维度
        dim = len(dense_vector)

        # 获取文件标题, 文件标题用于后续的幂等处理, 即删除该文件之前写入的旧切片
        file_title = chunks[0].get("file_title")

        return chunks, dim, file_title

    # 创建或复用 Collection
    def create_milvus_collection(self, dim):

        # 获取 Milvus 客户端
        milvus_client = get_milvus_client()
        collection_name = MilvusConfig.chunks_collection

        # 检查客户端是否初始化成功
        if not milvus_client:
            logger.error("milvus_client初始化失败")
            raise Exception("milvus_client初始化失败")

        # 检查 Collection 是否存在
        if not milvus_client.has_collection(collection_name):

            # 创建 Schema
            schema = milvus_client.create_schema(
                auto_id=True,  # 表示主键 id 不由业务代码生成，而是由 Milvus 自动生成
            )
            # 添加字段
            schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
            ).add_field(
                field_name="file_title",  # 文件标题, 标识来源文件
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="title",  # 切片标题, 表示切片所属标题
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="content",  # 切片内容, 是真正用于知识检索的正文
                datatype=DataType.VARCHAR,
                max_length=5000,
            ).add_field(
                field_name="item_name",  # 条目名称, 表示知识点、章节或条目名称
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="part",  # 分段序号, 表示切片在文件中的序号
                datatype=DataType.INT64,
            ).add_field(
                field_name="dense_vector",  # 稠密向量, 用于语义相似度匹配
                datatype=DataType.FLOAT_VECTOR,
                dim=dim,  # 维度使用前面从 chunks[0] 推断出的 dim
            ).add_field(
                field_name="sparse_vector",  # 稀疏向量, 用于倒排索引和内积检索
                datatype=DataType.SPARSE_FLOAT_VECTOR,
            )

            # 创建稠密向量索引, 创建一个索引配置容器
            # .prepare_index_params() 是 PyMilvus SDK 中 MilvusClient 类提供的实例方法
            index_params = milvus_client.prepare_index_params()

            # 添加稠密向量索引
            # add_index() 也来自 PyMilvus SDK
            index_params.add_index(
                field_name="dense_vector",
                index_type="IVF_FLAT",  # AUTOINDEX
                metric_type="COSINE",
                params={"nlist": 128, "nprobe": 10},
            )

            # 创建稀疏向量索引
            index_params.add_index(
                field_name="sparse_vector",
                index_type="SPARSE_INVERTED_INDEX",  # AUTOINDEX
                metric_type="IP",
                params={
                    "inverted_index_algo": "DAAT_MAXSCORE",  # 高效的稀疏检索算法
                    "normalize": True,  # L2 归一化，让内积 (IP) 等价于余弦相似度
                    "quantization": "none",  # 关闭量化，保持原始精度：模型生成的向量已经压缩的一半的精度了（BGE_FP16=1），这里就不再压缩了
                    # "quantization": "none" → 存储原始向量，不压缩
                    # "quantization": "sq8" → 存储压缩后的向量（8-bit 量化
                }
            )

            # 创建 Collection
            milvus_client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )

        return collection_name, milvus_client  # Collection 名称, Milvus 客户端

    # 删除旧数据并插入新数据
    def insert_data(self, chunks, collection_name, file_title, milvus_client):

        # 加载 Collection, 幂等删除与 file_title 重复的记录, 删除数据记得先加载表
        milvus_client.load_collection(collection_name=collection_name)

        # 转义文件标题(引号冲突)
        # 如果不进行转义, 最终过滤表达式可能出现引号冲突, 导致表达式解析失败.
        # 例如原始文件名是: 产品说明书'2026.pdf
        file_title = file_title.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

        # 文件标题拼接到 Milvus 的过滤表达式中
        filter_str = f"file_title == '{file_title}'"

        # 按文件标题删除旧数据
        milvus_client.delete(collection_name=collection_name, filter=filter_str)

        # 批量插入 chunks
        # 把整个 chunks 列表直接交给 Milvus, 因此，Milvus 会按照之前定义的 Schema, 读取每个 chunk 中对应的字段:
        # file_title, title, content, item_name, part, dense_vector, sparse_vector
        res = milvus_client.insert(
            collection_name=collection_name,
            data=chunks,
        )
        # 插入响应保存在 res 中
        logger.info(res)

        # 提取 Milvus 自动生成的主键 id, 把插入数据返回的id, 回填到对应的chunks, 为了保证数据的完整性
        ids = res.get("ids")

        # 将 Milvus 返回的 ID 写回原始的 chunks
        if ids:
            for i, chunk in enumerate(chunks):
                chunk["id"] = ids[i]

    def process(self, state: ImportGraphState):
        # 第一步: 获取上一步向量化后的 chunks
        chunks, dim, file_title = self.get_chunks(state)

        # 第二步:创建 milvus 的 Collection
        collection_name, milvus_client = self.create_milvus_collection(dim)

        # 第三步: 幂等性删除并插入数据到 milvus 中
        self.insert_data(chunks, collection_name, file_title, milvus_client)

        return {
            "chunks": chunks,
        }


if __name__ == '__main__':
    node = NodeImportMilvus()
    with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json", "r", encoding="utf-8") as f:
        chunks = json.load(f)
    init_state = {
        "chunks": chunks
    }
    result = node(init_state)
    logger.info(json_format(result))


"""
# 
node_import_milvus.py 是 RAG 文档导入流程中的“向量库持久化节点”。
负责将上游生成的文本、元数据、稠密向量和稀疏向量持久化到向量数据库中，供后续 RAG 检索使用

它主要完成三件事：
    - 接收上游完成切分和向量化的 chunks 数据。
    - 创建或复用 Milvus Collection，并定义字段结构和向量索引。
    - 根据文件标题删除旧数据，再将当前文档的新切片和向量写入 Milvus。
    

#     
这个文件实现的是 RAG 文档导入流程中的 Milvus 持久化节点。
上游节点已经完成文档解析、切分和向量化，
这里从状态中的 chunks 获取切片数据，并从第一个稠密向量推断向量维度、获取文件标题。
随后通过 Milvus 客户端检查 Collection 是否存在，不存在时创建 Schema 和索引。
Schema 中同时保存文件标题、切片标题、正文、条目名称、分段序号、稠密向量和稀疏向量，
其中稠密向量使用余弦相似度索引，稀疏向量使用倒排索引和内积检索。

在数据写入阶段，节点先加载 Collection，然后根据 file_title 删除该文件之前的旧切片，
再批量插入当前 chunks，从而实现同一文件重复导入时的幂等更新。由于主键配置为 auto_id=True ，Milvus 会自动生成 ID，
插入成功后代码再将返回的 ID 回填到对应 chunk 中。最后，节点返回更新后的 {"chunks": chunks} ，将结果写回流程状态。


# 向量字段解决的是“存什么”，索引解决的是“怎么快速查”。两者不是重复配置，而是存储和检索两个不同层次的功能。
  - 向量是被检索的数据，索引是检索这些数据的加速结构。
  - 稠密向量和稀疏向量是数据字段，负责保存 Embedding 模型生成的向量；
  索引负责组织这些向量并提高相似度搜索效率。
  如果没有索引，Milvus 可能需要扫描大量向量进行逐条计算，数据量大时检索延迟会很高。
"""
