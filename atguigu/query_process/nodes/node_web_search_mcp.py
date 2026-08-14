# atguigu/query_process/nodes/node_web_search_mcp.py
import asyncio
from idlelib import query
from agents.mcp import MCPServerStreamableHttp
from atguigu.config.config import McpConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.json_format_tool import json_format


class NodeWebSearchMcp(NodeBase):
    """
    节点功能，调用外部搜索引擎补充信息
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        # TODO
        logger.info(f"【{self.name}】节点逻辑")

        # return state
        return {"web_search_docs": []}

    async def mcp_turn(self, query, limit=10) -> None:
        token = McpConfig.api_key
        async with MCPServerStreamableHttp(
                name="Web Search",
                params={
                    "url": McpConfig.mcp_base_url,
                    "headers": {"Authorization": f"Bearer {token}"},
                    "timeout": 10,
                },
                cache_tools_list=True,
                max_retry_attempts=3,
        ) as server:
            result = server.call_tool("bailian_web_search", arguments={
                "query":query,
                "count":limit,
            })

    asyncio.run(self.mcp_turn(query, limit))

if __name__ == "__main__":

    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用"
    }

    # 执行节点的业务调用
    node_web_search_mcp = NodeWebSearchMcp()
    result = node_web_search_mcp(init_state)
    logger.info(json_format(result))