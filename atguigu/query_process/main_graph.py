from langgraph.graph import StateGraph

from atguigu.query_process.state import QueryGraphState


class MainGraph:
    def __init__(self):
        self.builder = StateGraph(state_schema=QueryGraphState)
        self.add_nodes()

    def add_nodes(self):
        self.builder.add_node()