# atguigu/query_process/nodes/node_item_name_confirm.py

import json
from langchain.chat_models import init_chat_model  # 统一初始化聊天大模型
from atguigu.config.config import LLMConfig, MilvusConfig  # 配置文件
from atguigu.config.prompt import ITEM_NAME_EXTRACT_SYSTEM_PROMPT, \
    ITEM_NAME_EXTRACT_TEMPLATE  # 大模型的系统提示词, 定义模型身份 / 任务和基本规则; 用户提示词模板
from atguigu.query_process.base import NodeBase  # 节点基类, 所有查询处理节点的抽象基类
from atguigu.query_process.state import QueryGraphState  # 查询图 状态字典, 作用是描述查询图状态字典应该有哪些字段
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding  # BGE-M3向量生成工具
from atguigu.tool.json_format_tool import json_format  # 导入 JSON 序列化工具
from atguigu.tool.milvus_client_tool import create_reqs, search_hybrid
from atguigu.tool.logger import logger  # 日志工具
from atguigu.tool.mongo_client_tool import add_or_update_history, get_history_list, \
    update_history_item_names  # MongoDB工具


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。这个节点解决的是“用户当前问题可能没有直接说出商品名”的问题。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def get_history_content(self, state):
        '''
        作用: 验证状态参数, 保存当前用户问题, 获取最近历史内容, 拼接成模型可读文本
        :return: history_content / message_id / original_query / session_id
        '''
        # 读取并校验会话 ID, 为什么必须有 session_id ? - 没有它就无法区分不同用户或不同会话的历史记录.
        session_id = state.get("session_id")
        if not session_id:
            logger.error("session_id 不存在, 必须传递 session_id")
            raise Exception("session_id 不存在, 必须传递 session_id")

        # 读取并校验原始问题, 没有问题文本就无法执行商品名称提取
        original_query = state.get("original_query")
        if not original_query:
            logger.error("original_query 不存在, 必须传递 original_query")
            raise Exception("original_query 不存在, 必须传递 original_query")

        # 保存当前用户消息, 已经获取到 session_id 和 original_query 代表本次提问可以添加到历史记录当中.
        # 返回新插入记录的 MongoDB ObjectId .
        message_id = add_or_update_history(
            session_id,
            "user",
            original_query,
        )

        # 查询并获取最近历史记录
        # 这里当前问题已经先插入数据库, 所以查询结果中会包含当前问题.
        # 从历史记录当中获取最近的10条, 然后把内容拼接为一个字符串, 然后让大模型根据这个字符串, 帮助用户识别主体名字及修改原始问题.
        history_list = get_history_list(
            session_id,
            limit=10,
        )

        # 初始化字符串, Python 字符串是不可变对象, 后面每次 += 都会生成新字符串.
        history_content = ""  # 创建空字符串, 用于后续累加.

        # 拼接历史记录文本
        for history in history_list:
            role = history.get("role")  # 取得角色
            text = history.get("text")  # 取得文本
            content = f"{role}: {text}\n"  # 格式化单条历史

            # 追加到完整历史记录
            history_content += content

        return history_content, message_id, original_query, session_id  # 返回元组, 调用方通过元组解包接收

    def get_item_name(self, history_content, original_query):
        """
        执行: 初始化大模型; 构造消息; 调用大模型; 解析 JSON; 清洗商品名称; 返回商品名称和改写问题.
        作用: 根据历史内容和原始问题, 获取商品名称, 利用 LLM 从用户当前问题以及历史会话中提取商品名称
        :param history_content: 拼接后的历史会话
        :param original_query: 用户当前原始问题
        :return: 商品名称 item_names 和 改写后的问题 rewritten_query . 类型: tuple[list[str], str]
        """
        # 初始化模型, 并返回模型客户端对象.
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature
        )

        # 构造消息列表
        message = [
            {  # 第一条消息: 用于定义模型规则
                "role": "system",
                "content": ITEM_NAME_EXTRACT_SYSTEM_PROMPT
            },
            {  # 第二条消息: 用于提供实际输入
                # 为什么要把历史和问题放进模板?  - 因为模型需要知道: 之前聊了什么; 当前问题是什么; 当前问题中省略的主体是什么.
                "role": "user",
                "content": ITEM_NAME_EXTRACT_TEMPLATE.format(history_text=history_content,
                                                             original_query=original_query)
            },
        ]

        # 调用大模型
        res = llm.invoke(input=message)

        # 取得模型文本正文, 对大模型输出的返回信息进行整理和判断
        res_json = res.content  # 访问返回值是 LangChain 的 AIMessage 类型 的 content 属性, 即模型输出正文

        # 1.尝试将大模型的返回信息进行 JSON 解析, 但是大模型在返回 JSON 的时候有概率输出一个 JSON 的 Markdown 代码块,
        # 但 json.loads() 只能接受纯 JSON, 不能接受 Markdown 标记. 所以需要把代码块标记 ```json 和 ``` 去掉.
        if res_json.startswith("```json"):  # str.startswith() 返回 bool
            res_json = res_json.replace("```json", "").replace("```", "")  # str.replace() 返回新字符串, 不会原地修改原字符串.

        # 2.把 JSON 字符串转化为 Python 字典(反序列化), 取出item_names, 进行判断, 如果有值, 则把所有的 item_name 去除空白.
        res_dict = json.loads(res_json)

        # 取得商品名称和改写问题
        item_names = res_dict.get("item_names")
        rewritten_query = res_dict.get("rewritten_query")

        # 清理商品名, 依次删除: 普通空格 / 换行 / 制表符
        # 为什么需要清理? - 减少无意义空白对向量检索的影响. 对模型提取出的商品名称进行格式清洗, 然后再送给 BGE-M3 进行向量化和 Milvus 检索.
        if item_names:  # 检查它的"真值", item_names 为非空列表, 正常进入 if; item_names 为空列表, 则进入 else, 最终返回空列表.
            item_names = [
                item_name.replace(" ", "")
                .replace("\n", "")
                .replace("\t", "")
                for item_name in item_names  # 首先执行
            ]
        else:
            item_names = []  # 没有商品名称, 把 None 或其他假值统一转换为空列表, 这样做可以使后续代码始终按照列表处理

        # 没有改写问题时回退
        # 如果大模型没有返回改写结果, 就使用原始问题.
        # 这是一个容错设计，确保返回的 rewritten_query 始终是字符串。
        if not rewritten_query:
            rewritten_query = original_query

        return item_names, rewritten_query

    def get_final_search_item_names(self, item_names):
        '''
        执行: 将商品名称批量向量化; -> 对每个商品名称分别执行 Milvus 混合检索; -> 将搜索结果整理成统一字典列表.
        :param item_names: 大模型提取出的商品名称列表, list[str]
        :return: final_search_item_names: list[dict] - 搜索结果列表, 每个字典包含商品名称和搜索得分
        因为需要 milvus 进行混合检索, 所以需要先定义好混合检索的工具函数 Milvus_client_tool
        '''
        embedding = get_bge_m3_embedding(item_names)  # 批量向量化, 一次性把所有商品名称转成: 稠密向量, 稀疏向量

        collection_name = MilvusConfig.item_name_collection  # 取得 Milvus 商品名称集合

        final_search_item_names = []  # 初始化最终结果列表

        for index, item_name in enumerate(item_names):  # 遍历名称及下标
            dense_data = embedding.get("dense")[index]  # 取得当前商品名的所有稠密向量
            sparse_data = embedding.get("sparse")[index]  # 取得当前商品名的所有稀疏向量

            # 创建混合检索请求, 包含稠密向量和稀疏向量的检索请求. 字段名称必须和 Milvus Collection Schema 中的字段一致
            reqs = create_reqs(
                dense_data=dense_data,
                sparse_data=sparse_data,
                dense_anns_field="dense_vector",
                sparse_anns_field="sparse_vector",
            )

            # 执行混合检索, 获取搜索结果
            res = search_hybrid(
                collection_name=collection_name,
                reqs=reqs,
                ranker=(0.8, 0.2),
                limit=10,
                output_fields=["item_name"],  # 业务字段只返回 item_name
            )

            logger.info(json_format(res[0]))

            # 整理搜索结果, 取得商品名称和得分
            search_item_names = [
                {
                    "original_item_name": item_name,  # 大模型提取的原始名称, 保存 LLM 提取出的商品名称
                    "search_item_name": item.get("entity", {}).get("item_name", ""),  # Milvus 中检索到的标准名称
                    # 如果没有 entity , 则使用空字典; 然后, 如果没有商品名, 返回空字符串.
                    "score": item.get("distance")  # 取得 Milvus 返回的 相似度分数
                }
                for item in res[0]  # 对于 res[0] 中的每个检索结果 item, 创建一个新字典.
            ]

            # 合并当前搜索结果
            final_search_item_names.extend(search_item_names)  # extend() 会把列表中的元素逐个加入目标列表

            logger.info(json_format(search_item_names))

        # 返回所有输入商品名对应的全部检索结果. 类型: list[dict] - 返回搜索结果列表, 每个字典包含商品名称和搜索得分
        return final_search_item_names

    def align_item_names(self, final_search_item_names):
        """
        作用: 是根据 Milvus 检索得分, 决定是否确认商品名称.
        :param final_search_item_names: list[dict], Milvus 检索结果整理后的列表.
        :return: answer 和 final_item_names. 对齐后的商品名称列表, 返回二元组: tuple[str, list[str]]
        """
        # 高分商品筛选, 只保留分数大于等于 0.85 的商品名称
        confirm_item_names = [
            item.get("search_item_name")
            for item in final_search_item_names
            if item.get("score") >= 0.85
        ]

        # 中等分数商品筛选, 只保留分数大于等于 0.6 且小于 0.85 的商品名称
        option_item_names = [
            item.get("search_item_name")
            for item in final_search_item_names
            if 0.6 <= item.get("score") < 0.85
        ]

        # 存在高分结果
        if confirm_item_names:
            final_item_names = confirm_item_names
            answer = ""  # 只要存在高分商品: 直接确认商品名, 不向用户输出追问文本, 后续图流程继续进行检索

        # 存在中等分数结果
        elif option_item_names:
            final_item_names = []
            answer = f"请您确认想咨询下列哪些商品? {",".join(option_item_names)}"  # .join() 把字符串列表拼接成一个字符串

        # 没有任何可信结果
        else:
            final_item_names = []
            answer = "对不起, 我无法识别您要咨询的商品名称, 请重新提问."  # 没有任何分数达到 0.6 , 认为识别失败

        # answer: 当前回答, 也是初始回复文本, 调用时是空字符串.
        # final_item_names: list[str], 最终商品名称列表, 调用时是空列表.
        return answer, final_item_names

    def handler_history(self, answer, final_item_names, message_id, rewritten_query, session_id):
        """
        作用: 处理历史记录, 更新商品名称和改写问题.
        :param answer: 当前节点准备返回给用户的提示, 调用时是空字符串.
        :param final_item_names: list[str], 最终商品名称列表, 调用时是空列表.
        :param message_id: 当前消息 ID, 用于更新历史记录.
        :param rewritten_query: 改写后的完整问题, 用于更新历史记录.
        :param session_id: 会话 ID, 用于更新历史记录.
        返回值: 最终的 message_id, 类型: ObjectId
        """
        # 判断 answer 是否存在需要处理的历史记录, 如果 answer 有值, 代表有新的历史记录(添加历史记录), 如果没有, 代表不需要添加历史记录,
        # 无论有没有 answer , 都需要给历史记录回填 item_names 和 rewritten_query.
        # answer 非空: 需要添加一条 assistant 回复
        # answer 为空: 系统已经确认商品, 不需要当前节点回复;

        # 保存 assistant 回复, 如果需要提示用户确认商品, 或者提示无法识别, 则把该提示写入历史记录.
        if answer:  # 如果有需要直接返回给用户的文本, 就保存一条助手消息
            message_id = add_or_update_history(session_id, "assistant", answer)  # 插入一条助手历史消息
        '''
        为什么重新赋值给 message_id? 
        - 因为新增 assistant 消息后, 当前最后一条消息已经不再是用户问题, 而是新写入的 assistant 消息, 所以用新消息 ID 覆盖原来的用户消息 ID.
        '''

        # 查询获取最近 10 条历史
        # 为什么要重新查询? - 因为前面可能刚插入一条 assistant 回复, 原来的历史列表已经过期, 需要重新获取最新历史.
        history_list = get_history_list(session_id, limit=10)

        # 提取历史记录 ID
        ids = [history.get("_id") for history in history_list]

        # 判断 ID 列表是否非空, 批量更新历史记录
        # 如果列表不是空列表, 就批量更新这些记录, 注意它更新的是最近 10 条历史, 不只是当前用户消息.
        if ids:
            update_history_item_names(ids, final_item_names, rewritten_query)

        # 返回更新后的消息 ID
        return message_id

    def process(self, state: QueryGraphState):
        # 第一步: 读取并整理历史
        history_content, message_id, original_query, session_id = self.get_history_content(state)

        # 调用大模型, 得到: 模型识别出的商品名 和 补全上下文后的问题
        item_names, rewritten_query = self.get_item_names(history_content, original_query)

        # 初始化结果
        answer = ""
        final_item_names = []

        if item_names:  # 判断模型是否提取出商品名, 如果是非空列表, 才进行向量检索.
            # 3.对 item_names 进行向量化, 然后去 milvus 中进行混合检索, 整理成字典列表 final_search_item_names
            final_search_item_names = self.get_final_search_item_names(item_names)

            # 4.根据 final_search_item_names 的分数, 确定最终的确认名字或者候选的名字, 对齐名字及设置最终的answer和最终的item_names
            answer, final_item_names = self.align_item_names(answer, final_search_item_names)

        # 5.根据最终的 answer, 更新历史记录. 如果有 answer , 还会插入 assistant 消息, 然后将结果回填到最近历史记录。
        message_id = self.handler_history(answer, final_item_names, rewritten_query, session_id)

        # 返回节点状态
        return {
            "message_id": message_id,  # 用户或助手消息 ID
            "original_query": original_query,  # 原始用户问题
            "answer": answer,  # 当前节点准备返回给用户的提示, 需要直接输出的确认/失败提示
            "item_names": final_item_names,  # 已确认标准商品名
            "rewritten_query": rewritten_query,  # 上下文补全问题
            "history": get_history_list(session_id, limit=10)  # 最近 10 条历史记录
        }


if __name__ == "__main__":
    # 模拟会话历史
    session_id = "test_001"
    add_or_update_history(session_id, "user", "咨询下烫金机。")
    add_or_update_history(session_id, "assistant", "您好。请问是哪个型号")
    add_or_update_history(session_id, "user", "hak180")
    add_or_update_history(session_id, "assistant", "具体有什么问题呢？")

    # 初始化图状态
    init_state = {
        "session_id": "test_001",
        "original_query": "咋用？"
    }

    # 创建节点对象
    node_item_name_confirm = NodeItemNameConfirm()
    # 执行节点的单元测试
    result = node_item_name_confirm(init_state)
    # 将返回的图状态进行json序列化
    logger.info(json_format(result))

"""
# 
1.从状态 state 中取得：
    会话 ID：session_id
    用户当前问题：original_query
2.把当前用户问题写入 MongoDB 历史记录。
3.查询该会话最近 10 条消息，并拼接成对话文本。
4.将历史对话和当前问题交给大语言模型，让模型：
    提取商品名称 item_names
    将上下文相关问题改写为完整问题 rewritten_query
5.使用 BGE-M3 将商品名称转换成：
    稠密向量 dense
    稀疏向量 sparse
6.在 Milvus 商品名称集合中做混合检索。
7.根据检索得分决定：
    得分高：直接确认商品
    得分中等：让用户从候选商品中选择
    得分低：提示无法识别商品
8.更新历史记录中的：
    商品名称
    改写后的问题
9.返回更新后的图状态。

# 整体流程:
    用户提问问题
      ↓
    保存用户消息到 MongoDB
      ↓
    读取最近 10 条会话记录
      ↓
    调用大模型提取商品名, 改写问题
      ↓
    使用 BGE-M3 对商品名生成稠密和稀疏向量
      ↓
    在 Milvus 商品名称集合中混合检索
      ↓
    根据相似度分数决定: 
      ├─ 高分：直接确认商品名称
      ├─ 中分：询问用户选择哪个商品
      └─ 低分：提示无法识别
      ↓
    更新历史记录
      ↓
    返回新的图状态

# 例如历史会话是:
    user: 咨询下烫金机
    assistant: 请问是哪个型号
    user: hak180
    assistant: 具体有什么问题
    user: 咋用？
    
    - 当前问题"咋用?"本身没有商品名. 因此程序不能只分析当前问题, 而是:
    1. 保存当前问题.
    2. 读取同一 session_id 的历史消息.
    3. 把历史和当前问题交给大模型.
    4. 让大模型推断"用户问的是 HAK180 烫金机怎么用".
    5. 再通过 Milvus 标准化商品名称, 避免直接相信大模型生成的名称.
    6. 只有相似度足够高时, 才确认这个商品.

- 这是典型的: LLM 信息提取 + 向量数据库实体对齐 设计.
  大模型负责理解自然语言和上下文, Milvus 负责把模型提取出的非标准商品名对齐到系统中真实存在的标准商品名.
  
  
# 完整执行调用链
NodeItemNameConfirm(init_state)
  ↓
NodeBase.__call__(state)
  ├─ 记录节点开始日志
  ↓
NodeItemNameConfirm.process(state)
  ↓
get_history_content(state)
  ├─ 读取 session_id
  ├─ 读取 original_query
  ├─ 保存 user 消息
  ├─ 查询最近 10 条历史
  └─ 拼接 history_content
  ↓
get_item_names(history_content, original_query)
  ├─ init_chat_model()
  ├─ 构造 messages
  ├─ llm.invoke()
  ├─ 清除 Markdown JSON 标记
  ├─ json.loads()
  ├─ 提取 item_names
  └─ 提取 rewritten_query
  ↓
如果 item_names 非空
  ↓
get_final_search_item_names(item_names)
  ├─ BGE-M3 批量向量化
  ├─ 遍历每个商品名
  ├─ 创建稠密检索请求
  ├─ 创建稀疏检索请求
  ├─ Milvus 混合检索
  └─ 整理搜索结果
  ↓
align_item_names(...)
  ├─ score >= 0.85：确认
  ├─ 0.6 <= score < 0.85：询问用户
  └─ score < 0.6：识别失败
  ↓
handler_history(...)
  ├─ 必要时保存 assistant 消息
  ├─ 查询最近 10 条历史
  └─ 批量回填商品名和改写问题
  ↓
查询最新历史
  ↓
返回状态字典
  ↓
NodeBase.__call__
  ├─ 记录节点结束日志
  └─ 返回结果
"""
