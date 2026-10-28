from .corpus import Corpus

EXAMPLES = [
    {"id": "normal", "title": "明确答案", "question": "报销期限多久？", "history": [], "description": "单一制度资料：仅保留 D01，不存在期限冲突。"},
    {"id": "conflict", "title": "制度冲突", "question": "报销期限多久？", "history": [], "description": "完整资料：D01 为 30 天，D02 为 15 天，未给优先级。"},
    {"id": "outside", "title": "资料外问题", "question": "公司股票期权的行权价格是多少？", "history": [], "description": "资料库未收录股票期权制度。"},
    {"id": "paraphrase", "title": "相似改写", "question": "费用最晚什么时候报账？", "history": [], "description": "单一制度资料：使用同义表达查询报销期限。"},
    {"id": "followup", "title": "上下文追问", "question": "需要哪些凭证？", "history": [{"role": "user", "content": "国内差旅住宿报销上限是多少？"}, {"role": "assistant", "content": "根据 D03，国内差旅住宿费每人每晚报销上限为 500 元。"}], "description": "完整资料：根据历史理解差旅报销，并重新读取凭证条款。"},
    {"id": "transient_failure", "title": "一次工具失败", "question": "报销期限多久？", "history": [], "description": "单一制度资料；第一次检索失败，观察后由模型决定是否再尝试。"},
    {"id": "persistent_failure", "title": "持续工具失败", "question": "报销期限多久？", "history": [], "description": "检索持续失败，应报告未完成，不能声称没有相关制度。"},
]
EXAMPLE_MAP = {item["id"]: item for item in EXAMPLES}


def scenario_corpus(scenario_id: str | None, path=None, enhanced=True) -> Corpus:
    if scenario_id is not None and scenario_id not in EXAMPLE_MAP:
        raise ValueError("未知演示场景")
    corpus = Corpus.load(path, enhanced=enhanced)
    if scenario_id in {"normal", "paraphrase", "transient_failure"}:
        corpus = Corpus([doc for doc in corpus.documents if doc["document_id"] != "D02"], enhanced=enhanced)
    return corpus


def faults_for(scenario_id):
    if scenario_id == "transient_failure":
        return {"search_documents": 1}
    if scenario_id == "persistent_failure":
        return {"search_documents": -1}
    return {}
