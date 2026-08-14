# atguigu/import_process/nodes/node_item_name_recognition.py
import json
from langchain.chat_models import init_chat_model
from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.prompt import ITEM_NAME_SYSTEM_PROMPT, ITEM_NAME_USER_PROMPT_TEMPLATE  # 导入大模型提示词和用户提示词模板
from atguigu.tool.json_format_tool import json_format
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding  # 导入 BGE-M3 嵌入模型的调用函数, 用于将文本向量化.
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client  # 导入 Milvus 客户端单例工厂函数
from pymilvus import DataType  # 从 PyMilvus (Milvus 向量数据库的 Python SDK) 中导入 DataType 类, DataType 用于声明 Collection 字段的数据类型


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"  # 覆盖 父类的 name 属性, 如果子类不覆盖 name, 则 self.name 仍是 "node_base", 会触发异常.

    def get_chunks(self, state: ImportGraphState):
        chunks = state.get("chunks")
        file_title = state.get("file_title")

        if not chunks:
            logger.error("chunks 为空, 无法进行主体识别, 必须有值才可以进行主体识别")
            raise Exception("chunks 为空, 无法进行主体识别, 必须有值才可以进行主体识别")

        if not file_title:
            logger.error("file_title 为空, 无法进行主体识别, 必须有值才可以进行主体识别")
            raise Exception("file_title 为空, 无法进行主体识别, 必须有值才可以进行主体识别")

        return chunks, file_title  # 返回值类型: Tuple[List[Dict], str]
                                   # 本质是返回一个元组, 接收方可以用解包语法 chunks, file_title = self.get_chunks(state)

    def get_chunks_content(self, chunks, file_title):
        '''
        把多个 chunk 组织成一个提供给 LLM 的字符串, 同时限制内容大小, 避免超出模型上下文限制.
        :param chunks: list[str], 含义: 文档切片列表
        :param file_title: str, 含义: 文件标题
        :return: content_str: str, 含义: 给大模型识别商品名称用的上下文文本.
        '''
        chunk_k_list = chunks[:10]  # 列表切片, 取第0到第9个元素, 即最多取前10个, 避免超出 LLM 的上下文窗口.
        # 为什么? - 文档可能有很多 chunk; - chunk 内容全部拼接可能超出 LLM 的上下文窗口; - 前几个切片通常包含标题 / 产品介绍 / 摘要 / 参数等关键信息.

        max_len = 10000  # 设定最大字符数, 这里不是 token 数, 而是 Python 字符串长度. 中文通常一个汉字算一个字符,
                         # 但模型实际消耗的 token 数与字符数不完全相同. 该限制是为了控制 LLM 输入长度和调用成本.

        content_str = "\n"  # 初始化最终字符串, 使用换行符, 使第一个拼接内容也从新行开始. 功能上初始化为 "" 也可以, 这里对结果没有本质影响.

        for index, chunk in enumerate(chunk_k_list, start=1):  # 遍历切片
            title = chunk.get("title")  # 从每个切片字典中取标题和正文
            content = chunk.get("content")  # 从每个切片字典中取标题和正文

            chunk_str = f"[切片{index}]\n{file_title}\n{title}\n{content}"  # 构造单个切片的文本
            # file_title : 可能直接带产品型号;   title : 可能出现"产品参数""产品介绍"等强语义;
            # content : 提供实际产品名称 / 品牌 / 型号等证据;  [切片N] : 让文本结构更清晰.

            if len(content_str) > max_len:  # 检查当前已拼接的文本是否超过最大长度.
                logger.info("已经超过最大长度, 停止拼接")  # 如果超过上限: - 记录日志; - break 立即跳出循环; - 后续 chunk 不再加入.
                break

            content_str += chunk_str  # 将当前 chunk 文本拼接到总文本中.
                                      # 字符串是不可变对象, 所以每次拼接都会产生新字符串. 这里最大只有 10 个 chunk, 性能问题不明显.

            content_str = content_str[:max_len]  # 最终截断兜底






    def process(self, state: ImportGraphState):
        chunks, file_title = self.get_chunks(state)

        content_str = self.get_chunks_k_content(chunks, file_title)

        # 准备大模型, 识别得到的主体名称
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )

        message = [
            {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(file_title=file_title, context=content_str)}
        ]

        res = llm.invoke(input=message)
        item_name = res.content

        item_name = item_name.replace(" ", "").replace("\n", "").replace("\t", "")

        if not item_name:
            """
            # item_name可能没有被识别到, 用文件名代替, 但是文件名也可能是没有意义的, 此时后期 chunk 当中的 file_title 和 item_name
            就都没有意义了, 但是还需要给当前 chunk 机会, 后期在存储该 chunk 时, 向量化的内容是 item_name 拼接 content内容
            # 此时这个向量就可能被获取检索检索到. 假设这种chunk后期检索相似度很低, 就不要这个chunk
            """

            item_name = file_title

        # 将 item_name 向量化后, 保存到 milvus库中, 因为后期检索时需要
        milvus_client = get_milvus_client()
        if not milvus_client:
            logger.error("milvus_client 初始化失败")
            raise Exception("milvus_client 初始化失败")

        # 幂等性删除一般不会对整张表进行删除, 一般都是针对表中的相同数据进行幂等性删除
        collection_name = MilvusConfig.item_name_collection
        if not milvus_client.has_collection(collection_name):
            schema = milvus_client.create_schema(
                auto_id=True,
            )
            schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
                is_unique=True,
            ).add_field(
                field_name="item_name",
                datatype=DataType.VARCHAR,
                max_length=500,
            ).add_field(
                field_name="file_title",
                datatype=DataType.VARCHAR,
                max_length=500
            ).add_field(
                field_name="dense_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=1024
            ).add_field(
                field_name="sparse_vector",
                datatype=DataType.SPARSE_FLOAT_VECTOR,
            )

            index_params = milvus_client.prepare_index_params()

            index_params.add_index(
                field_name="dense_vector",
                index_name="dense_vector_index",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128, "nprobe": 10},
            )
            index_params.add_index(
                field_name="sparse_vector",
                index_name="sparse_vector_index",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
                params={
                    "inverted_index_algo": "DAAT_MAXSCORE",
                    # 高效的稀疏检索算法
                    "normalize": True,
                    # ↑ L2 归一化，让内积 (IP) 等价于余弦相似度
                    "quantization": "none"
                    # ↑ 关闭量化，保持原始精度: 模型生成的向量已经压缩的一半的精度了(BGE_FP16=1), 这里就不再压缩了
                    # "quantization": "none" → 存储原始向量，不压缩
                    # "quantization": "sq8" → 存储压缩后的向量 (8-bit 量化)
                }
            )
            milvus_client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )

        return state

        # 准备数据, 插入数据
        # 幂等删除 item_name 相同的数据
        # 如果 milvus 要删除数据, 需要先加载表
        milvus_client.load_collection(collection_name=collection_name)

        milvus_client.delete



if __name__ == '__main__':
    node = NodeItemNameRecognition()
    # with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json","r",encoding="utf-8") as f:
    #     chunks_JSON = f.read()  # 如果这样写, 下面需要反序列化

    with open(r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json", "r", encoding="utf-8") as f:
        chunks = json.load(f)

    init_state = {
        "chunks": chunks,
        "file_title": "hak180产品安全手册"
    }
    result = node(init_state)
    logger.info(json_format(result))


"""
# 整个系统的工作流程是:
  - 文件读入 → 切片(Chunking) → 主体名称识别 → 向量化存储 → 检索问答
  - 职责是:
    1. 从上游状态 state 取到文档切片 chunks 和文件标题 file_title ;
    2. 从前 10 个切片中拼接一段有限长度的文本;
    3. 调用大模型识别该文档对应的商品/主体名称 item_name ;
    4. 将该商品名称生成稠密、稀疏向量;
    5. 将名称和向量写入 Milvus ;
    6. 将 item_name 写回每一个 chunk;
    7. 返回新的节点状态数据.
    
  - 完整执行时序图
  node(init_state)
  │
  └─► NodeBase.__call__(state)
        │
        ├─ logger.info("node_item_name_recognition开始执行了")
        │
        └─► self.process(state)
              │
              ├─► get_chunks(state)
              │     └─ return (chunks, file_title)
              │
              ├─► get_chunks_content(chunks, file_title)
              │     └─ return content_str  (拼接后的字符串)
              │
              ├─► get_item_name(content_str, file_title)
              │     ├─ init_chat_model(...)  → llm
              │     ├─ llm.invoke(messages)  → res
              │     └─ return item_name
              │
              ├─► create_milvus_collection()
              │     ├─ get_milvus_client()
              │     ├─ 如果集合不存在: 创建 Schema + 索引 + 集合
              │     └─ return (collection_name, milvus_client)
              │
              ├─► insert_data_backup(chunks, collection_name, file_title, item_name, milvus_client)
              │     ├─ 幂等删除旧数据
              │     ├─ get_bge_m3_embedding([item_name])
              │     ├─ milvus_client.insert(data)
              │     └─ 回填 item_name 到每个 chunk
              │
              ├─ 写调试 JSON 文件
              │
              └─ return {"item_name": item_name, "chunks": chunks}
        │
        └─ logger.info("node_item_name_recognition执行结束了")

# 当前节点主要输出:
    - item_name: 类型: str, LLM识别的商品主题名称;
    - chunks: 类型: List[Dict], 已经补充 item_name 字段的切片列表, 每个切片 chunk 都会多一个 item_name 字段.

# chunks = state.get("chunks")
  - state 是一个字典(ImportGraphState ), 来自上一个节点的输出.
  - state.get("chunks") : 安全地从字典中取值. 如果 key 不存在, 返回 None 而不是抛 KeyError.
  - 为什么用 .get() 而不是 state["chunks"] : 更安全, 不会因为 key 不存在而崩溃.
  
# 预期 chunk 结构大致是:
    {
    "title": "产品概述",
    "content": "HAK180 产品安全手册……"
    }
    
# 构造单个切片的文本: chunk_str = f"[切片{idx}]\n{file_title}\n{title}\n{content}\n"
例如:
    [切片1]
    HAK180产品安全手册
    产品概述
    HAK180 是一款……
    
- 为什么把 file_title / title /  content 都发送给 LLM:
    file_title : 可能直接带产品型号;
    title : 可能出现"产品参数""产品介绍"等强语义;
    content : 提供实际产品名称 / 品牌 / 型号等证据;
    [切片N] : 让文本结构更清晰.
"""
