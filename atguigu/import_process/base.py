'''
NodeBase 是基于 Python ABC 实现的导入流程节点的抽象基类.
核心设计目标是 "复用通用逻辑 / 约束子类行为":

- 通用逻辑封装: __call__ 方法统一处理节点执行的日志 / 任务追踪、异常捕获, 降低子类开发成本;
- 子类约束: 通过 __init__ 强制子类覆盖 name 属性, 通过 @abstractmethod 要求子类实现核心业务方法 process;

- 这个类的实现目的: 是想要做一个接口规范, 它是一个抽象类, 目的是为了让后面所有的节点类必须继承该类
且接受类中定义的规范.

'''
# atguigu/import_process/base.py

import time
from abc import ABC, abstractmethod  # ABC 是 Python 标准库 abc 模块提供的 抽象基类
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger
from atguigu.tool.task_utils import add_running_task, add_done_task, add_node_duration

"""
查询流程节点基类
定义统一的节点接口规范, 提供通用功能
子类必须实现 process 方法, 用于处理节点的具体业务逻辑
"""


class NodeBase(ABC):  # NodeBase 是所有导入流程节点的抽象父类.
    name: str = "node_base"  # name 是类属性, 用来标识节点名称, 子类需要覆盖它.

    def __init__(self):
        if self.name == "node_base":
            raise Exception(f"子类{self.__class__.__name__}必须重写 name 属性")

    @ abstractmethod
    def process(self,state):
        pass

    def __call__(self, state):
        try:
            logger.info(f"{self.name}开始执行了")

            # 修改每个节点执行中的状态
            task_id = state.get("task_id")
            add_running_task(task_id, self.name)
            start_time = time.time()
            # 这个call是后期所有的子类对象在当函数使用的时候，都会自动调用这个方法
            result = self.process(state)
            logger.info(f"{self.name}执行结束了")

            # 修改每个节点执行完成的状态
            add_done_task(task_id, self.name)
            end_time = time.time()

            # 计算每个节点执行所用的时间
            add_node_duration(task_id, self.name, end_time - start_time)
            return result
        except Exception as e:
            logger.error(f"{self.name}执行异常了")
            raise e




'''
# from abc import ABC, abstractmethod
    它适合用来定义一套统一的“接口规范”:
    - 父类规定子类必须具备哪些方法.
    - 父类可以提供可复用的通用代码.
    - 不完整的子类不能被实例化.
    
# NodeBase 的作用是:
     - 统一所有节点的接口;
     - 强制子类实现 process 方法;
     - 统一打印开始和结束日志;
     - 统一捕获异常;
     - 允许节点对象像函数一样被调用.
'''
