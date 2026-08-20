# atguigu/query_process/nodes/node_web_search_mcp.py
import asyncio
import json
from agents.mcp import MCPServerStreamableHttp
from atguigu.config.config import McpConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format


class NodeWebSearchMcp(NodeBase):
    """
    节点功能: 调用外部搜索引擎补充信息
    这个文件定义了一个“网络搜索节点”。它接收上游节点改写后的用户问题，通过 HTTP 连接到 MCP 服务，调用百炼网络搜索工具，
    然后把搜索结果转换为项目统一使用的文档结构，写入查询流程状态中的 web_search_docs
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_web_search_mcp"

    # 异步调用 MCP 搜索服务
    # async def 表示这是协程函数。调用它时不会直接运行函数体，而是先返回一个协程对象；必须通过 await 或 asyncio.run() 才会真正执行。
    async def mcp_run(self, query, limit=10):
        '''
        调用 MCP 搜索服务
        :param query: 发送给搜索引擎的查询文本
        :param limit:期望返回的搜索结果数量, 表示调用者不传 limit 时自动使用 10
        '''

        # 从配置类中读取 API Key，并赋值给局部变量 token
        token = McpConfig.api_key

        # 创建 MCP HTTP 客户端, 并使用异步上下文管理器
        # async with 是异步版本的 with，适用于需要异步初始化和异步释放资源的对象, 例如：异步 HTTP 客户端；数据库连接；WebSocket；MCP 服务会话。
        # 为什么使用 async with ?  - 自动建立连接。 - 无论调用成功还是发生异常，都能执行清理。 - 防止连接、会话等资源泄漏。
        # 当代码退出 async with 块时，无论正常返回还是发生异常，都会自动关闭/清理 server 使用的连接和会话。
        async with MCPServerStreamableHttp(
                name="websearch",  # 指定 MCP 服务的逻辑名称, 当前 MCP 客户端连接的名称或标识
                # 连接参数
                params={
                    "url": McpConfig.mcp_base_url,  # MCP 服务地址
                    "headers": {"Authorization": f"Bearer {token}"},  # HTTP 请求头，用于认证。
                    "timeout": 10,  # 单次 HTTP 请求的超时
                },
                cache_tools_list=True,  # 允许缓存 MCP 服务端提供的工具列表, MCP 服务可以提供可调用工具列表。开启缓存后，客户端不需要在每次工具访问前重复获取列表。
                max_retry_attempts=3,  # 最大重试次数, 表示网络调用失败时，SDK最多按配置尝试重试
                client_session_timeout_seconds=30  # 整个客户端会话或工具调用生命周期的超时, 设置客户端会话级别超时，单位明确为秒
        ) as server:  # 异步上下文管理器成功进入后，将创建的 MCP 客户端对象赋值给变量 server
            # server 是 MCPServerStreamableHttp 的实例，用于调用远程工具.

            # 调用 MCP 服务中的工具，并等待结果,  await 用于等待异步操作完成
            # call_tool(): 是 MCP 客户端对象的方法，作用是调用远程工具。call_tool() 返回的是可等待对象，因此必须用 await 调用.
            # await 的含义是：发起远程调用；当前协程在等待网络响应时让出控制权；事件循环可执行其他异步任务；搜索服务响应后，恢复执行；
            # 将工具执行结果赋值给 result。
            result = await server.call_tool(
                "bailian_web_search",  # 远端工具名称

                arguments={  # 存在一次参数名转换
                    "query": query,  # 网络搜索关键字
                    "count": limit,  # 要求搜索服务返回的结果数量
                }
            )  # call_tool() 正常返回 MCP 工具结果对象。按后续代码的使用方式，这里返回的对象类型是 MCPClientToolResult

            return result

    def process(self, state: QueryGraphState):
        # 读取改写后的问题
        rewritten_query = state.get("rewritten_query")

        if not rewritten_query:
            logger.error("rewritten_query 不能为空! ")
            raise ValueError("rewritten_query 不能为空! ")

        # 调用异步方法 mcp_run() 执行网页搜索，并将结果保存到 result。
        '''
        执行顺序是：
        调用 self.mcp_run(rewritten_query)；
        因为 mcp_run 是 async def，此时不会立刻执行，而是返回协程对象（coroutine）；
        asyncio.run(...) 创建/运行事件循环；
        事件循环执行协程中的 HTTP 请求；
        请求完成后获取 return result 的真实返回值；
        将真实搜索结果赋值给局部变量 result。
        '''
        result = asyncio.run(self.mcp_run(rewritten_query))

        # 解析 MCP 返回内容, search_data 的类型: list[dict], 即每一个元素是一条网页搜索结果
        '''
        # 第一步: result.content: content 是 MCP 结果对象的属性，预计保存内容块列表。
        # 第二步: result.content[0]: [0] 是列表下标访问，表示获取第一个内容块.
        # 第三步: result.content[0].text: text 是文本内容块的属性，预期类型为: str, 保存远端工具返回的 JSON 文本
        # 第四步: json.loads(): 将 JSON 文本转换为 Python 字典
        # 第五步: .get("pages"): 从字典中获取 "pages" 字段, 读取搜索页面列表
        '''
        search_data = json.loads(result.content[0].text).get("pages")

        # 返回网页文档结果, 类型: list[dict]; 键: "web_search_docs", 值: 搜索结果列表
        # 这样设计的原因是：工作流中各节点可能需要遵守固定状态字段协议。后续节点只需读取：state.get("web_search_docs"),
        #                就可以使用网页检索结果，而不必关心底层搜索服务的原始字段格式.
        return {
            "web_search_docs": [
                {
                    "title": item.get("title"),  # 读取网页标题
                    "content": item.get("snippet"),  # 将搜索结果的 snippet 字段映射为内部统一字段 content。
                    # snippet 通常指搜索引擎返回的网页摘要，而不是网页全文
                    "url": item.get("url"),  # 读取网页来源地址
                    "source": "web",  # 给每条文档添加固定来源标记
                }
                for item in search_data  # 依次遍历 search_data 返回的每一个页面对象, 把原始结果转成项目统一格式。
            ]
        }


if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用"
    }

    # 执行节点的业务调用
    node_web_search_mcp = NodeWebSearchMcp()
    result = node_web_search_mcp(init_state)
    logger.info(json_format(result))

"""
# 整体流程:

 上游商品确认/问题改写节点
         │
         │ 在状态中写入 rewritten_query
         ▼
 NodeWebSearchMcp 节点对象被调用
         │
         ▼
 NodeBase.__call__(state)
         │
         ├─记录“节点开始执行”
         ▼
 NodeWebSearchMcp.process(state)
         │
         ├─读取 rewritten_query
         ├─检查查询是否为空
         ├─asyncio.run(...) 运行异步方法
         ▼
 NodeWebSearchMcp.mcp_run(query, limit=10)
         │
         ├─读取 MCP 地址和 API Key
         ├─创建 MCP HTTP 客户端
         ├─连接 MCP 服务
         ├─调用 bailian_web_search
         └─返回 MCP CallToolResult
         │
         ▼
 process() 读取 result.content[0].text
         │
         ├─json.loads() 转成 Python 字典
         ├─读取 pages 列表
         └─列表推导式转换文档格式
         │
         ▼
 返回 {"web_search_docs": [...]}
         │
         ▼
 NodeBase.__call__ 记录“节点结束执行”
         │
         ▼
 LangGraph 将结果合并进共享状态
         │
         ▼
 NodeRrf 汇合 → NodeRerank 合并本地与 Web 文档

"""
