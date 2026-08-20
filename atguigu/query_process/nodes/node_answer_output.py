# atguigu/query_process/nodes/node_answer_output.py
import re
from langchain.chat_models import init_chat_model
from atguigu.config.config import LLMConfig
from atguigu.config.prompt import ANSWER_PROMPT
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.mongo_client_tool import add_or_update_history
from atguigu.tool.task_utils import put_data


class NodeAnswerOutput(NodeBase):
    """
    节点功能: 定义了 RAG 查询流程中的最终答案输出节点
    """
    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_answer_output"

    def process(self, state: QueryGraphState):

        answer = state.get("answer")  # answer ：前置流程可能已经生成的直接答案

        task_id = state.get("task_id")  # task_id ：当前查询任务的唯一标识，用于找到对应的任务队列

        # 判断前面是否已经有直接答案
        # 这条分支一般用于处理不需要继续检索的情况
        if answer:
            # 表示向当前任务的队列中放入一条 final 类型的数据。后续 SSE 接口会读取这条数据并推送给前端。
            put_data(task_id, "final", {"answer": answer})

        # 没有直接答案时，进入正常 RAG 生成流程
        # 读取状态 -> 组装 Prompt -> 调用大模型流式生成 -> 提取图片 URL -> 写入 MongoDB 和任务队列 -> 返回答案到图状态
        else:
            # 格式化提示词
            chunks, item_names, prompt, rewritten_query = self.format_prompt(state)

            # 大模型生成答案，流式输出，推送到前端
            answer = self.generate_answer(answer, prompt, task_id)

            # 获取chunks当中图片url
            images = self.get_image_urls(chunks)

            # 把答案写入历史记录并且推送图片
            self.write_history(answer, images, item_names, rewritten_query, state, task_id)

        return {
            "answer": answer,
        }

    # 构造答案生成上下文, 负责把 结构化状态 转换为大模型可以理解的文本 Prompt
    def format_prompt(self, state):

        # 获取重排序后的文档
        chunks = state.get("reranked_docs")

        # 逐条拼接文档内容
        '''
        类似结构:
        [1][local][某产品使用说明][本地文档地址]
        文档正文内容

        [2][web][官方网页标题][网页地址]
        网页正文内容
        '''
        chunk_content = ""
        for idx, chunk in enumerate(chunks, start=1):
            title = chunk.get("title")
            content = chunk.get("content")
            url = chunk.get("url")
            source = chunk.get("source")
            content = f"[{idx}][{source}][{title}][{url}]\n{content}\n\n"
            chunk_content += content

        # 拼接历史对话, 历史对话的作用是补充当前问题缺失的上下文
        history = state.get("history")
        history_content = ""
        for h in history:
            h_content = f"[{h['role']}]: {h['text']}\n\n"
            history_content += h_content

        # 拼接商品名称
        item_names = state.get("item_names")
        item_names_str = ",".join(item_names)

        # 获取改写后的问题
        rewritten_query = state.get("rewritten_query")

        # 使用 ANSWER_PROMPT 组装完整提示词
        prompt = ANSWER_PROMPT.format(
            context=chunk_content,  # 重排序后的知识片段
            history=history_content,  # 历史对话内容
            item_names=item_names_str,  # 当前商品名称
            question=rewritten_query  # 改写后的问题
        )

        # 对 Prompt 做长度截断
        prompt = prompt[:10000]

        # 后续步骤使用: - chunks ：用于提取图片 - item_names ：用于写入历史 - prompt ：用于调用模型 - rewritten_query ：用于写入历史
        return chunks, item_names, prompt, rewritten_query

    # 流式调用大模型
    def generate_answer(self, answer, prompt, task_id):

        # 初始化聊天模型
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            base_url=LLMConfig.openai_api_base,
            api_key=LLMConfig.openai_api_key,
            temperature=0.3,
        )

        # 构造消息格式
        # 当前调用使用单轮用户消息, 将完整 Prompt 作为用户内容传给模型
        message = [
            {
                "role": "user",
                "content": prompt,
            }
        ]

        # 启用流式输出
        # stream 不会等模型生成完整答案后一次性返回，而是持续返回多个输出片段。
        # 流式输出适合问答系统，因为用户可以较早看到答案开头，不需要等待整个模型调用结束。
        res = llm.stream(input=message)

        # 同时完成前端推送和完整答案拼接
        # 每收到一个片段, 会同时进行两件事: 1.放入任务队列, 实时推送给前端; 2.拼接到 answer, 形成完整答案
        answer = ""  # 这是完整的答案, 要存储到 state 中
        for r in res:
            # 流式输出，把答案放入队列，后续sse推送
            put_data(task_id, "delta", {"delta": r.content})
            answer += r.content
        return answer

    # 提取图片地址
    def get_image_urls(self, chunks):
        # 识别 chunks 当中的图片url
        seen = set()  # 使用集合去重, 多个文档可能引用同一张图片, 因此使用集合避免重复图片地址.

        # 使用正则匹配 Markdown 图片
        md_img_pattern = re.compile(r'!\[.*?\]\((.*?)\)')

        # 遍历文档正文, 函数从每个文档的 content 字段中提取图片地址
        for i, doc in enumerate(chunks):
            # 检查 text 字段中的 Markdown 图片 (主要针对 Local Chunk)
            text = doc.get("content")
            matches = md_img_pattern.findall(text)  # 找所有的和正则匹配的元素放到列表

            # 对地址进行清理和去重
            for img_url in matches:
                img_url = img_url.strip()
                if img_url and img_url not in seen:
                    seen.add(img_url)
        images = list(seen)
        return images

    # 持久化和最终事件推送, 需要把这个答案变为历史记录存储到 mongoDB 中
    def write_history(self, answer, images, item_names, rewritten_query, state, task_id):

        # 保存助手答案, 如果模型确实生成了答案，则以 assistant 角色写入 MongoDB。这样下一次用户继续提问时，系统可以读取历史对话，恢复上下文。
        if answer:
            session_id = state.get("session_id")
            add_or_update_history(
                session_id=session_id,
                role="assistant",
                text=answer,
                rewritten_query=rewritten_query,
                item_names=item_names,
                image_url=images,
            )
        # 推送最终图片信息
        # 这一步将图片列表作为 final 事件放入任务队列
        put_data(task_id, "final", {"image_urls": images})


"""
# 概括
这个文件负责把前面检索、融合和重排序阶段得到的知识片段，
结合用户问题改写结果、商品信息以及历史对话，组装成最终 Prompt，调用大语言模型生成答案。
同时，它支持模型答案的流式输出、图片提取、历史记录持久化，并把最终答案写回查询图状态。


# node_answer_output.py 是 RAG 查询图中的最终答案输出节点。
它首先从共享状态中读取前置节点产生的答案和任务 ID。
如果前面已经生成了直接答案，例如商品无法识别或需要用户确认，就直接通过任务队列发送最终事件；
如果没有直接答案，则读取重排序后的检索文档、历史对话、商品名称和改写问题，按照统一格式组装 Prompt。
随后调用兼容 OpenAI 协议的聊天模型进行流式生成，每获得一个模型片段就通过任务队列推送给前端，同时拼接成完整答案。
模型生成结束后，节点从检索文档中提取 Markdown 图片地址，
去重后将完整答案、图片、商品名称和改写问题写入 MongoDB 历史记录，
最后返回 {"answer": answer} ，把最终答案写回查询图状态。
"""
