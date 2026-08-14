# atguigu/query_process/state.py

from typing import TypedDict, List


class QueryGraphState(TypedDict):
    """
    查询流程图状态
    包含整个查询流程中传递的所有数据。
    """

    session_id: str  # 会话ID, 标识“哪一段会话”. 同一用户连续聊天时保持不变.
    message_id: str  # 消息ID, 标识“会话中的哪一条消息”. 每次新提问通常不同.

    original_query: str  # 用户原始问题. 用户此刻的原始表达, 可能省略上下文.

    # 检索过程中的中间数据
    embedding_chunks: list  # 普通向量检索回来的切片. 用于后续的排序和生成.
    hyde_embedding_chunks: list  # 已向量化的假设性问题切片. 用于向量检索.
    web_search_docs: list  # 网络搜索回来的文档. 用于补充信息.

    # 排序过程中的数据
    rrf_chunks: list  # RRF 融合排序后的切片. 用于最终的排序.
    reranked_docs: list  # 重排序后的最终 Top-K 文档. 用于生成答案.

    # 生成过程中的数据
    prompt: str  # 组装好的 Prompt. 用于生成答案.
    answer: str  # 最终生成的答案. 系统根据 Prompt 生成的最终答案.

    # 辅助信息
    item_names: List[str]  # 提取出的商品名称. 系统从问题和历史中识别出的商品/型号; 可能为空 / 一个 / 多个.
    rewritten_query: str  # 改写后的问题. 把依赖上下文的原话补全成可独立检索的问题, 系统根据问题和历史对话生成的改写问题, 用于提高检索的准确性.
    history: list  # 历史对话记录. 此前对话, 用于判断“这款”“那个型号”具体指什么, 包含用户和系统的对话历史, 用于提供上下文信息.
