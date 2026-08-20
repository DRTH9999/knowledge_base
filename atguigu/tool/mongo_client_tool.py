import time  # 生成消息的时间戳, 用于记录聊天历史的时间
from pymongo import MongoClient  # 导入 PyMongo 库的 MongoClient 类, 用于建立与 MongoDB 服务器的连接
from atguigu.config.config import MongoDBConfig  # 导入 MongoDB 配置类, 分别获得: MongoDB 地址, MongoDB 数据库名称.

# 获取 MongoDb 连接
mongo_client = None  # 表示 MongoDB 客户端尚未创建

# 获取表
db = None  # 用于缓存 MongoDB 数据库对象
collection = None  # 用于缓存 MongoDB 集合对象, 具体集合是: chat_history


# 创建并复用 MongoDB 客户端
def get_mongo_client():
    global mongo_client

    if mongo_client is None:
        mongo_client = MongoClient(MongoDBConfig.mongo_url)  # 创建 MongoDB 客户端连接

    return mongo_client


# 获取并缓存 MongoDB 中的 chat_history 集合。
def get_mongodb_collection():
    global collection  # 声明要修改全局变量 collection
    global db  # 声明要修改全局变量 db

    mongo_client = get_mongo_client()  # 获取 MongoDB 客户端连接

    # 获取数据库对象, 判断数据库对象是否已经缓存.
    if db is None:  # 如果数据库对象不存在
        db = mongo_client[MongoDBConfig.mongo_db_name]  # 获取数据库对象, 返回 MongoDB 数据库对象

    # 获取集合对象
    if collection is None:  # 如果集合对象不存在

        # 获取集合对象. "chat_history" 是存储聊天历史的集合名, 第一次调用时, 会创建或引用名为 chat_history 的集合.
        # MongoDB 不要求必须提前执行“创建集合”的操作, 通常当第一次向该集合插入文档时, MongoDB 会自动创建它.
        collection = db["chat_history"]

        collection.create_index([("_id", 1), ("ts", -1), ("session_id", 1)])  # 为集合创建索引
        '''
        - create_index() : 用于为集合创建索引, create_index() 通常返回创建的索引名称, 类型: str.
        - 这里创建的是复合索引, 由三个字段组成: _id, ts, session_id, 每个元组结果是:("字段名", 排序方向). 1: 升序; -1: 降序
        - 为什么要创建索引: 提高查询性能, 类似书籍的目录
        - 索引字段: 
            1. ("_id", 1) : _id 升序(1 表示升序),  MongoDB 默认就有 _id 索引, 这里重复声明(实际会忽略)
            2. ("ts", -1) : ts (时间戳)降序(-1 表示降序), 用于按时间倒序查询最新记录
            3. ("session_id", 1) : session_id 升序, 用于按会话 ID 查询该会话的所有记录
        - 返回值: Collection 对象(chat_history 集合)
        - 返回值类型: pymongo.collection.Collection
        - 后续可以调用:
        - find(...) : 查询集合中的文档, 返回一个游标对象 cursor, 可以遍历获取所有匹配的文档.
        - insert_one(...) : 插入一个文档, 返回一个 InsertOneResult 对象, 包含插入文档的 _id.
        - update_one(...) : 更新一个文档, 返回一个 UpdateResult 对象, 包含更新操作的匹配和修改信息.
        - update_many(...) : 更新多个文档, 返回一个 UpdateResult 对象, 包含更新操作的匹配和修改信息.
        - delete_one(...) : 删除一个文档, 返回一个 DeleteResult 对象, 包含删除操作的匹配和删除信息.
        - delete_many(...) : 删除多个文档, 返回一个 DeleteResult 对象, 包含删除操作的匹配和删除信息.
        '''

    return collection


# 对历史记录创建进行 增删改查 的方法
# 1.获取最近的几条历史记录, 通过 limit 限定, 方法的目的是后期进行意图识别的时候, 需要获取历史记录来识别用户意图
def get_history_list(session_id, limit=10):  # 参数: session_id : 用于区分不同会话, limit : 表示最多返回多少条历史记录

    # 获取 chat_history 集合, 返回 Collection 对象
    collection = get_mongodb_collection()

    result = (collection.find(  # find() 用于查询文档
        {"session_id": session_id})  # 查询条件是一个字典, 作用: 查询 session_id 字段等于 session_id 的文档
              .sort("ts", -1)  # sort() 用于排序, "ts" 表示按时间戳排序, -1 表示降序, 时间最新的记录排在前面
              .limit(limit)  # limit() 用于限制返回的文档数量, limit 表示最多返回多少条历史记录
              )

    return list(result)  # 原本得到的 result 是游标对象 cursor, 不是列表 list 对象, 所以需要强制类型转换
    # 游标一旦被转换成列表, 游标就被消费了, 当前代码只转换一次, 所以没有问题.


# 2.新增/更新历史记录
def add_or_update_history(session_id, role, text, rewritten_query=None, item_names=None, ts=None, _id=None, image_url=None):
    '''
    # 为什么在封装数据库 增加 和 修改 的时候全部合二为一, 写一个方法或者函数?
    - 因为在传递参数的时候唯一不同就是id. 如果是修改历史记录, 那么id一定存在; 如果是新增历史记录, 那么id一定不存在
    # 思想: 如果id存在, 则进行修改操作; 如果id不存在, 则进行新增操作.
    # 参数_id: 决定当前函数执行新增还是更新
    '''

    collection = get_mongodb_collection()

    # 更新操作
    if _id is not None:  # 函数真正想判断的是: 调用方是否传入了文档 ID, 而不是 ID 对象的布尔值.
        # 构造更新数据
        data = {
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query,
            "item_names": item_names,
            "image_url": image_url,
            "ts": ts or time.time(),  # 如果传入了 ts, 则使用 ts; 否则使用当前时间.
        }
        collection.update_one(
            {"_id": _id},  # 第一个参数是过滤条件: {"_id": _id}, 寻找 _id 等于指定值的文档
            {"$set": data},  # 第二个参数是更新操作: {"$set": data}, 表示将找到的文档只修改 data 中列出的字段, 而不是用整个新文档替换原文档.
        )  # $set: 是 MongoDB 更新操作符

        return _id  # 返回当前被更新文档的 ID

    # 新增操作
    else:
        # 构造新文档, 这里没有手动设置 _id, 因为 MongoDB 会自动生成一个唯一的 _id : ObjectId("...")
        data = {
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query,
            "item_names": item_names,
            "image_url": image_url,
            "ts": ts or time.time(),
        }

        result = collection.insert_one(data)  # 向集合中插入一条文档

        return result.inserted_id  # result.inserted_id 用于获取新文档 ID, 新增时 MongoDB 自动生成 ObjectId


# 3.删除指定会话的全部历史记录
def clear_history_list(session_id):
    collection = get_mongodb_collection()  # 获取 chat_history 集合

    collection.delete_many({"session_id": session_id})  # 删除所有满足条件的文档


# 4.根据一组文档 ID, 批量更新历史记录中的商品名称和改写后的问题.
def update_history_item_names(ids, item_names, rewritten_query):
    '''
    :param ids: 文档 ID 列表, 类型: list[ObjectId], 例如:
    ids = [
    ObjectId("..."),
    ObjectId("...")
    ]
    :param item_names: 商品名称列表, 类型: list, 例如: ["HAK180烫金机"]
    :param rewritten_query: 改写后的问题, 类型: str, 例如: "HAK180烫金机怎么使用? "
    '''
    # 获取集合, 返回 Collection 对象
    collection = get_mongodb_collection()

    #  构造更新数据
    data = {
        "item_names": item_names,
        "rewritten_query": rewritten_query,
    }

    collection.update_many(  # update_many(), 批量更新所有匹配文档
        {"_id": {"$in": ids}},  # $in:是 MongoDB 查询运算符, 查询 _id 属于 ids 列表的所有文档
        {"$set": data},
    )


"""
# 文件整体作用:
这是一个 MongoDB 数据库操作的封装工具模块, 主要用于管理聊天历史记录. 它提供了:
    - MongoDB 连接管理(单例模式)
    - 聊天历史记录的增删改查操作
    - 专门针对 chat_history 集合的业务操作
    

# MongoDB 的语义, 本质是字符串
  - "$set" / "$in" / "_id" / "session_id" / "ts", 这些都是字符串字面量, Python 不检查它们的含义, 只是把它们当作字典的键存起来,
    由 MongoDB 服务端进行语法校验.
    $in 和 $set 的语义是在 MongoDB 服务端被解释的, Python 端只负责把它们当字符串传过去.


# $set 是 MongoDB 定义的更新操作符(Update Operator). 语义是: 只修改列出的字段, 其他字段保持原样.
  - $set 存在的意义就是: 告诉 MongoDB —— 这是"局部更新", 不是"整体替换".
  - 如果去掉 $set，role、text、ts、session_id 全都会被删掉, 聊天历史就毁了.
  

# $in 是 MongoDB 的查询操作符
  - {"_id": {"$in": ids}}的语义: _id 的值中, 属于 ids 这个列表中的任意一个.
  

# 为什么用 $ 开头?
  - 因为 MongoDB 需要一种方式区分"字段名"和"操作符", 约定 $ 前缀之后, MongoDB 解析文档时只要看首字符就能判断这个键是字段还是指令.
这也是为什么 MongoDB 不建议你自己的字段名以 $ 开头.


# _id 的两种完全不同的身份

1."_id" 带引号 —— MongoDB 字段名
例如: {"_id": _id}, {"_id": {"$in": ids}} ...
这些都是字符串, 指的是 MongoDB 文档中那个名叫 _id 的字段.

  - _id 是 MongoDB 规定的主键字段名, 不是项目定义的, 
    每个文档必须有 _id; _id 在集合内唯一; MongoDB 自动为它建立唯一索引; 如果插入时不提供, 会自动生成; 一旦写入, 不允许修改.

2._id 不带引号 —— Python 函数参数
例如: _id = None
定义位置就在函数签名里, 是一个带默认值 None 的普通参数

把前两者放在一起
    data = {
        "_id": _id,
    }
左边 "_id"  → 字符串，MongoDB 的字段名
右边 _id    → Python 变量, 函数参数

参数名 _id 可以随便改成 doc_id、message_id、record_id, 因为它只是 Python 变量. 
但字典里的 "_id" 一个字符都不能改, 因为 MongoDB 只认这个字段名.


# _id 的值从哪来?
注意 data 里根本没有 _id, 但插入之后却能拿到 result.inserted_id.
这是 PyMongo 的行为: 当待插入文档缺少 _id 时, PyMongo 会在客户端生成一个 ObjectId 并补进文档, 
然后再发给服务端. 正因为 ID 是客户端生成的, insert_one() 才能立即返回 inserted_id, 不需要等服务端回传.


# 总结
- $set / $in 是 MongoDB 的操作符, "_id" 是 MongoDB 的主键字段名.
三者在 Python 代码里都只是字典的字符串键, 所以不需要 import / 不需要定义 / Python 也不校验它们, 真正解释它们的是 MongoDB 服务端.

- 而不带引号的 _id 是另一回事 —— 它是 add_or_update_history() 的函数参数, 定义在函数签名里,
至于 _id 字段的值(ObjectId), 是 PyMongo 在插入时自动生成并补进文档的, 这也是 insert_one() 能立刻返回 inserted_id 的原因.
"""

