'''
NodeBase 是基于 Python ABC 实现的导入流程节点的抽象基类.
核心设计目标是 "复用通用逻辑 / 约束子类行为":

- 通用逻辑封装: __call__ 方法统一处理节点执行的日志 / 任务追踪、异常捕获, 降低子类开发成本;
- 子类约束: 通过 __init__ 强制子类覆盖 name 属性, 通过 @abstractmethod 要求子类实现核心业务方法 process;

- 这个类的实现目的: 是想要做一个接口规范, 它是一个抽象类, 目的是为了让后面所有的节点类必须继承该类
且接受类中定义的规范.

'''
# atguigu/import_process/base.py

from abc import ABC, abstractmethod  # ABC 是 Python 标准库 abc 模块提供的 抽象基类
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger

"""
查询流程节点基类
定义统一的节点接口规范, 提供通用功能
子类必须实现 process 方法, 用于处理节点的具体业务逻辑
"""


class NodeBase(ABC):  # NodeBase 是所有导入流程节点的抽象父类.
    name: str = "node_base"  # name 是类属性, 用来标识节点名称, 子类需要覆盖它.

    def __init__(self):
        """
        强制子类设置 name 属性.
        当子类实例化时, 如果仍然使用父类默认名称 "node_base" , 就抛出异常.
        """
        if self.name == "node_base":
            raise ValueError(f"子类 {self.__class__.__name__} 必须覆盖父类的 name 类属性")

    def __call__(self, state: ImportGraphState) -> ImportGraphState:  # 节点对象可以像函数一样执行.
        """
        统一执行入口, 统一处理节点的执行逻辑. 统一规定了节点的执行流程.
        """
        try:
            # 1. 开始准备执行节点. 第一步: 记录开始日志, 每个节点执行前都会自动记录日志, 子类不需要重复编写.
            logger.info(f"--- {self.name} 开始啦 ---")

            # 2. 执行节点. 第二步：调用子类业务逻辑 process 方法.
            result = self.process(state)

            # 3. 执行节点成功. 第三步：记录完成日志, 处理成功后记录完成日志, 并返回更新后的状态.
            logger.info(f"--- {self.name} 完成啦 ---")

            return result

        except Exception as e:  # 第四步: 统一异常处理. 捕获异常, 记录错误日志, 并抛出异常.
            '''
            如果 process() 抛出异常: 
            1. 记录节点名称和异常信息. 
            2. 使用裸 raise 重新抛出原异常. 
            这里重新抛出非常重要. 如果只记录日志而不 raise , 上层工作流可能误以为节点执行成功.
            '''
            logger.error(f"{self.name} 执行失败: {e}")
            raise

    # __call__ 负责公共执行流程, process 负责具体业务逻辑.

    @abstractmethod  # @abstractmethod 声明该方法必须由具体子类实现.
    def process(self, state: ImportGraphState) -> ImportGraphState:  # 定义抽象方法 process()
        """
        - 节点核心处理逻辑
        - 子类必须实现此方法
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        这是每个节点真正需要实现的业务方法：
        - 参数是当前工作流状态 ImportGraphState .
        - 返回值是处理后的 ImportGraphState .
        - 子类必须实现, 否则无法实例化.
        """
        pass


'''
from abc import ABC, abstractmethod
    它适合用来定义一套统一的“接口规范”:
    - 父类规定子类必须具备哪些方法.
    - 父类可以提供可复用的通用代码.
    - 不完整的子类不能被实例化.
'''
