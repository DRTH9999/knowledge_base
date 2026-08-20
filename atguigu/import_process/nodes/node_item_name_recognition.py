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

    # 取得并校验上一步数据, 返回 chunks 和 file_title
    def get_chunks(self, state: ImportGraphState):
        '''
        - chunks: 文档切片列表。
        - 每个切片通常包含 title 、 content 、 file_title 、 part 等信息。

        - file_title: 文件标题或文件名主体。
        - 它可以作为商品名称识别时的补充上下文。
        '''
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

    # 整理交给大模型的上下文文本
    def get_chunks_content(self, chunks, file_title):
        '''
        把多个 chunk 组织成一个提供给 LLM 的字符串, 同时限制内容大小, 避免超出模型上下文限制.
        :param chunks: list[str], 含义: 文档切片列表
        :param file_title: str, 含义: 文件标题
        :return: content_str: str, 含义: 给大模型识别商品名称用的上下文文本.
        '''
        chunk_k_list = chunks[:10]  # 列表切片, 取第0到第9个元素, 即最多取前10个, 避免超出 LLM 的上下文窗口.
        # 为什么? - 文档可能有很多 chunk， chunk 内容全部拼接可能超出 LLM 的上下文窗口; - 前几个切片通常包含标题 / 产品介绍 / 摘要 / 参数等关键信息.

        # 设置最大文本长度, 节点将提交给大模型的上下文限制在最多 10000 个字符左右
        max_len = 10000  # 设定最大字符数, 这里不是 token 数, 而是 Python 字符串长度. 中文通常一个汉字算一个字符,
        # 但模型实际消耗的 token 数与字符数不完全相同. 该限制是为了控制 LLM 输入长度和调用成本.

        content_str = "\n"  # 初始化最终字符串, 使用换行符, 使第一个拼接内容也从新行开始. 功能上初始化为 "" 也可以, 这里对结果没有本质影响.

        # 遍历切片列表, 获取每个切片的标题和内容
        for index, chunk in enumerate(chunk_k_list, start=1):
            title = chunk.get("title")  # 从每个切片字典中取得标题
            content = chunk.get("content")  # 从每个切片字典中取得正文

            # 构造单个切片的文本
            chunk_str = f"[切片{index}]\n{file_title}\n{title}\n{content}"
            # file_title : 可能直接带产品型号;
            # title : 可能出现"产品参数""产品介绍"等强语义;
            # content : 提供实际产品名称 / 品牌 / 型号等证据;  [切片N] : 让文本结构更清晰.

            # 控制拼接后的内容长度
            if len(content_str) > max_len:  # 检查当前已拼接的文本是否超过最大长度.
                logger.info("已经超过最大长度, 停止拼接")  # 如果超过上限: - 记录日志; - break 立即跳出循环; - 后续 chunk 不再加入.
                break

            # 将当前 chunk 文本拼接到总文本中
            content_str += chunk_str  # 字符串是不可变对象, 所以每次拼接都会产生新字符串. 这里最大只有 10 个 chunk, 性能问题不明显.

        # 循环结束后，又进行一次截断
        content_str = content_str[:max_len]  # 最终截断兜底

        # 返回整理后的上下文文本
        return content_str

    # 调用大语言模型识别商品名称
    def get_item_name(self, content_str, file_title):
        """
        调用大语言模型识别商品名称
        :param content_str: str, 含义: 给大模型识别商品名称用的上下文文本.
        :param file_title: str, 含义: 文件标题
        :return: item_name: str, 含义: 识别出的商品名称.
        """

        # 初始化大模型
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )

        # 构造 system 和 user 消息
        message = [
            {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(context=content_str, file_title=file_title)}
        ]

        # 同步调用模型并获取结果
        res = llm.invoke(input=message)
        item_name = res.content

        # 清洗模型输出
        # 原因是提示词要求模型只输出商品名称，但实际模型响应中可能带有多余空白或换行。清洗后，商品名称更适合作为：
        # - Milvus 中的字段值；- 过滤条件；- 后续向量化文本；- 文档切片的标签。
        item_name = item_name.replace(" ", "").replace("\n", "").replace("\t", "")

        # 识别失败时使用文件标题兜底
        # 如果模型没有识别出商品名称，或者模型返回空字符串，则使用 file_title 作为 item_name 。
        # 商品名称是后续数据链路中的重要字段，即使模型识别失败，也不能让整个文档切片失去主体标识，因此使用文件标题作为最低限度的备用名称。
        if not item_name:
            item_name = file_title

        return item_name

    # 创建或获取商品名称集合
    def create_milvus_collection(self):
        """
        # 把识别出的 item_name ，做向量化后， 保存到 milvus(原因在于后期检索的时候需要使用)
        # 检索流程时，第一个节点就是做用户意图识别，用户提出问题，问的是和哪个商品相关的问题，需要去识别商品名称（历史消息）
        # 识别出来的意图是哪个商品，需要在存储商品主体 milvus 当中去做一个对比（相似性查找）
        # 识别出来的意图产品如果找到了对应的item_name，那么我们就知道用户问的这个问题是和哪个商品相关的问题。
        """
        # 获取 milvus 客户端
        milvus_client = get_milvus_client()

        # 如果客户端初始化失败，节点无法保存商品名称向量，因此直接抛出异常。
        if not milvus_client:
            logger.error("初始化 milvus 客户端失败！")
            raise Exception("初始化 milvus 客户端失败！")

        # 获取 Collection 名称
        # 商品名称被保存到专门的 Collection 中，而不是与普通文档切片混在一起。
        # 这样查询时可以先针对商品名称做匹配，再根据商品名称去检索对应文档。
        collection_name = MilvusConfig.item_name_collection

        # 判断 Collection 是否存在
        # 只有在 Collection 不存在时才创建，这样可以保证多次执行导入流程时不会重复创建同一张表。
        if not milvus_client.has_collection(collection_name):
            # 定义schema
            schema = milvus_client.create_schema(
                auto_id=True,  # Schema 设置为自动生成主键
            )
            # Milvus 的主键字段
            schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
                is_unique=True,
            ).add_field(
                field_name="item_name",  # 原始保存商品名称
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="file_title",  # 保存商品名称对应的文件标题
                datatype=DataType.VARCHAR,
                max_length=100
            ).add_field(
                field_name="dense_vector",  # 保存商品名称的稠密向量
                datatype=DataType.FLOAT_VECTOR,
                dim=1024
            ).add_field(
                field_name="sparse_vector",  # 保存商品名称的稀疏向量
                datatype=DataType.SPARSE_FLOAT_VECTOR,
            )

            index_params = milvus_client.prepare_index_params()

            # 创建稠密向量索引
            # 稠密向量主要用于捕捉语义相似性，例如用户使用不同说法描述同一个商品。
            index_params.add_index(
                field_name="dense_vector",
                index_type="IVF_FLAT",  # 暴力索引
                metric_type="COSINE",  # 余弦相似度
                params={"nlist": 128, "nprobe": 10},  # 提升效率否则暴力检索的准备效率太低，需要调参
            )

            # 创建稀疏向量索引
            # 稀疏向量主要用于捕捉稀疏特征，例如商品名称中的关键词，可以更好地保留关键词、型号、规格等词法信息。
            index_params.add_index(
                field_name="sparse_vector",
                index_type="IVF_FLAT",  # 暴力索引
                metric_type="IP",
                params={
                    "inverted_index_algo": "DAAT_MAXSCORE",  # 高效的稀疏检索算法
                    "normalize": True,  # ↑ L2 归一化，让内积 (IP) 等价于余弦相似度
                    "quantization": "none",  # 关闭量化，保持原始精度：模型生成的向量已经压缩的一半的精度了（BGE_FP16=1），这里就不再压缩了
                    # "quantization": "none" → 存储原始向量，不压缩
                    # "quantization": "sq8" → 存储压缩后的向量（8-bit 量化）
                }
            )

            # 创建并返回 Collection
            milvus_client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )

        return collection_name, milvus_client

    # 写入商品名称并回填 chunks, 商品名称数据写入和切片回填
    def insert_data_backup(self, chunks, collection_name, file_title, item_name, milvus_client):
        """
        # 幂等删除item_name相同的数据
        # milvus要删除数据，需要先去加载这个表
        # 在删除表当中的同名数据，不是字段也不是表
        """
        # 加载 collection
        # 在删除和插入数据前，先加载商品名称 Collection。
        milvus_client.load_collection(collection_name=collection_name)

        # 对商品名称进行转义, 因为后面要把商品名称拼接进 Milvus 过滤表达式中。
        # 对商品名称中的以下字符进行转义：- 反斜杠；- 单引号；- 双引号。
        safe_item_name = item_name.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

        # 根据 item_name 删除同名记录
        # 幂等处理思路：同一个商品名称重复导入时，先删除旧记录，再写入当前记录，避免商品名称 Collection 中不断产生相同的重复数据。
        filter_str = f"item_name == '{safe_item_name}'"
        milvus_client.delete(
            collection_name=collection_name,
            filter=filter_str
        )

        # 调用 BGE-M3 对商品名称向量化
        # BGE-M3 返回两种向量： - dense ：稠密向量；- sparse ：稀疏向量。
        embedding = get_bge_m3_embedding([item_name])  # 该工具接收字符串列表，因此这里把单个商品名称包装成列表

        # 组装 Milvus 插入数据
        # 商品名称 Collection 中保存四类业务数据：- 商品名称；- 文件标题；- 商品名称的稠密向量；- 商品名称的稀疏向量。
        data = {
            "item_name": item_name,
            "file_title": file_title,
            "dense_vector": embedding["dense"][0],  # 取[0]：当前商品名称对应的是返回结果中的第一条向量
            "sparse_vector": embedding["sparse"][0],  # 取[0]：当前商品名称对应的是返回结果中的第一条向量
        }

        # 插入 Milvus, 将商品名称记录写入 Collection
        result = milvus_client.insert(
            collection_name=collection_name,
            data=data,
        )

        # 把商品名称 item_name 回填到每一个 chunk 切片
        for chunk in chunks:
            chunk["item_name"] = item_name  # 直接修改原来的 chunks 列表，为每个切片增加相同的商品名称。

    def process(self, state: ImportGraphState):
        # 第一大步：获取上一个节点返回的chunks(切片)和file_title(文件名)
        chunks, file_title = self.get_chunks(state)

        # 第二大步：根据 chunks 去切10个，把内容整理成一个字符串
        content_str = self.get_chunks_content(chunks, file_title)

        # 第三大步：根据上一步得到的字符串，调用大模型识别得到主体名称
        item_name = self.get_item_name(content_str, file_title)

        # 第四大步：如果没有 collection，则创建 collection
        collection_name, milvus_client = self.create_milvus_collection()

        # 第五大步：插入数据到 milvus 当中，然后将 item_name 回填到每个 chunk
        self.insert_data_backup(chunks, collection_name, file_title, item_name, milvus_client)

        return {
            "item_name": item_name,
            "chunks": chunks,
        }


if __name__ == '__main__':
    node = NodeItemNameRecognition()
    chunk_path = r"E:\260515\knowledge_base\outputs\hak180产品安全手册\chunk.json"

    with open(chunk_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    init_state = {
        "chunks": chunks,
        "file_title": "hak180产品安全手册"
    }
    result = node(init_state)

    # 单独调试时把回填了 item_name 的 chunks 写回 chunk.json，供后续节点读取
    with open(chunk_path, "w", encoding="utf-8") as f:
        f.write(json_format(result["chunks"]))

    logger.info(json_format(result))

"""
# 文件定义了 RAG 导入流程中的“商品主体名称识别节点”：
它接收上一个文档切片节点生成的 chunks 和文件标题 file_title ，调用大语言模型识别文档对应的商品名称或主体名称，
然后将商品名称向量化并保存到 Milvus，同时把商品名称回填到每个文档切片中，最后把处理后的数据交给下一个向量化节点。


#
这个节点位于 RAG 导入流程的文档切片节点之后，主要负责识别当前文档对应的商品主体名称。
节点首先从状态中获取 chunks 和 file_title ，并检查这两个字段是否为空。
之后从前 10 个切片中提取文件标题、切片标题和正文，拼接成不超过 10000 个字符的上下文，避免一次性将全部文档内容交给大模型。

接下来，节点根据系统提示词和用户提示词调用配置好的聊天模型，让模型从文件标题和切片内容中识别商品名称。
模型返回结果后，代码会删除空格、换行和制表符。如果模型没有识别出有效名称，就使用文件标题作为兜底。

识别出商品名称后，节点获取或创建商品名称 Milvus Collection。
这个 Collection 保存商品名称、文件标题，以及 BGE-M3 生成的稠密向量和稀疏向量。
写入之前，代码会根据商品名称删除同名旧记录，以实现重复导入时的幂等处理；然后将商品名称向量化并写入 Milvus。

最后，节点遍历所有 chunks，把识别出的 item_name 回填到每个切片中，并返回 item_name 和更新后的 chunks 。
下一个切片向量化节点会读取这些 chunks，将商品名称和切片正文一起生成向量，之后再写入文档切片 Collection。
查询时，系统可以先通过商品名称 Collection 确认用户问题对应的商品，再使用 item_name 过滤对应商品的文档切片，从而完成更准确的 RAG 检索。


# 作用可以概括为三个方面：

- 识别文档属于哪个商品
  - 例如根据文件名、标题和前几个文档切片，识别出“海尔某型号冰箱”“某品牌净水器”等商品名称。
  - 识别结果保存在 item_name 中。
  
- 建立商品名称索引
  - 节点会将商品名称通过 BGE-M3 转换成稠密向量和稀疏向量。
  - 然后存入单独的商品名称 Milvus Collection。
  - 查询时，可以先根据用户问题识别或匹配商品名称，再找到对应的文档范围。
  
- 给每个切片补充商品归属
  - 每个 chunk 都会增加 item_name 字段。
  - 后续切片向量化时，会将 item_name 和 content 拼接后生成向量。
  - 查询时可以按照商品名称过滤，只检索对应商品的切片，减少不同商品文档之间的干扰。


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
    
    
# 商品名称既包含自然语言语义，也经常包含型号、规格和产品编号。稠密向量更适合捕捉语义相似性，稀疏向量更适合保留关键词和精确词法信息。
"""
