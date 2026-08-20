import dashscope
from http import HTTPStatus
from atguigu.config.config import RerankerConfig
from atguigu.tool.logger import logger

# 以下为华北2（北京）地域的配置, 调用时请将{WorkspaceId}替换为真实的业务空间ID, 各地域的配置不同. 
dashscope.base_http_api_url = RerankerConfig.reranker_base_url
dashscope.api_key = RerankerConfig.reranker_api_key


def text_rerank(query, texts, limit=10):
    try:
        resp = dashscope.TextReRank.call(
            model="qwen3-rerank",
            query=query,
            documents=texts,
            top_n=limit,
            return_documents=False,  # 因为有原始文档, 如果再返回文本. 会消耗大量不必要的Token.
            instruct="Given a web search query, retrieve relevant passages that answer the query."  # instruct 有两种模式.
        )
        if resp.status_code == HTTPStatus.OK:
            return [
                {
                    "index": item.index,
                    "score": item.relevance_score,
                }
                for item in resp.output.results
            ]

        else:
            logger.error(f"重排序请求失败 {resp.status_code}")
            raise Exception(f"重排序请求失败 {resp.status_code}")

    except Exception as e:
        logger.error(f"重排序请求失败: {e}")
        raise e


if __name__ == '__main__':
    text_rerank("如何学好自由泳", ["自由泳是奥运会必选项目", "如何学好自由泳", "自由泳是奥运会必选项目"])


'''
instruct string 可选

添加自定义排序任务类型说明, 仅在使用 qwen3-rerank 及qwen3-vl-rerank模型时生效. 通过该参数可以指导模型采用不同的排序策略, 例如: 

- 问答检索任务（默认）: "Given a web search query, retrieve relevant passages that answer the query."
侧重点: 寻找问题的答案. 模型会优先评估文档是否解答了Query中的问题. 
示例: 对于Query"如何预防感冒? ", 文档"勤洗手是预防感冒的有效方法"会获得高分；而文档"感冒是一种常见疾病"虽然主题相关, 但因未提供答案, 得分会显著更低. 

- 语义相似度排序任务: "Retrieve semantically similar text."
侧重点: 判断语义的等价性. 模型会评估Query和文档的核心含义是否一致, 而不管具体措辞或句式. 
示例: 在FAQ场景中, 用户Query"如何修改密码? "与候选问题"忘记密码怎么办? "在语义上高度相似, 应获得高分. 模型会关注两者是否指向同一个用户意图. 
建议使用英文撰写. 如不指定该参数, 将默认按问答检索任务进行排序. 
'''