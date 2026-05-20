"""ContextAssembler — 一次组装，所有 LangGraph 节点共享，消除双重发送"""
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    resolved_params: dict = field(default_factory=dict)
    wiki_context: str = ""
    conversation_context: str = ""
    agent_memory_context: str = ""
    wiki_hit: bool = False

    @property
    def total_context(self) -> str:
        parts = [self.wiki_context, self.conversation_context, self.agent_memory_context]
        return "\n\n".join(p for p in parts if p)


class ContextAssembler:
    """一次组装，所有节点共享，消除上下文双重发送"""

    def __init__(self, token_budget: int = 6000):
        self.token_budget = token_budget
        self._memory = None

    @property
    def memory(self):
        if self._memory is None:
            from memory.store import AgentMemory
            self._memory = AgentMemory()
        return self._memory

    async def assemble(self, session_id: str, user_text: str,
                       agent_type: str, wiki_store=None) -> AssembledContext:
        resolved = {}
        wiki_context = ""
        conversation_context = ""
        agent_memory_context = ""

        # Step 1: Wiki 实体解析
        if wiki_store:
            try:
                wiki_context, resolved_wiki = self._match_wiki(user_text, wiki_store, agent_type)
                resolved.update(resolved_wiki)
            except Exception:
                logger.warning("Wiki match failed", exc_info=True)

        # Step 2: 对话历史（按 importance 排序 + 摘要）
        try:
            conversation_context, resolved_history = self._build_conversation(session_id)
            resolved.update(resolved_history)
        except Exception:
            logger.warning("Conversation context build failed", exc_info=True)

        # Step 3: Agent 记忆
        try:
            agent_memory_context = self._build_agent_memory(session_id)
        except Exception:
            logger.warning("Agent memory build failed", exc_info=True)

        return AssembledContext(
            resolved_params=resolved,
            wiki_context=wiki_context,
            conversation_context=conversation_context,
            agent_memory_context=agent_memory_context,
            wiki_hit=bool(resolved),
        )

    def _match_wiki(self, user_text: str, wiki_store, agent_type: str) -> tuple:
        keywords = self._extract_keywords(user_text, agent_type)
        if not keywords:
            return "", {}
        try:
            matched = wiki_store.search_concepts(keywords, limit=3)
        except AttributeError:
            matched = wiki_store.search(keywords[0]) if keywords else []
        if not matched:
            return "", {}
        lines = []
        for page in matched:
            title = page.get("title", "")
            body = page.get("body", "")[:400]
            if body:
                lines.append(f"### {title}\n{body}")
        return "\n".join(lines), self._extract_frontmatter_params(matched)

    def _extract_keywords(self, user_text: str, agent_type: str) -> list:
        patterns = {
            "bi": ["即期", "远期", "掉期", "结汇", "购汇", "交易量", "套保率", "月", "季", "年"],
            "pricing": ["报价", "询价", "远期", "掉期", "即期", "价格", "汇率"],
            "ANALYSIS": ["为什么", "原因", "分析", "变化"],
        }
        kw_list = patterns.get(agent_type, patterns["bi"])
        return [kw for kw in kw_list if kw in user_text]

    def _extract_frontmatter_params(self, pages: list) -> dict:
        params = {}
        for page in pages:
            fm = page.get("frontmatter", {})
            if not fm:
                continue
            for key in ("product_type", "bank_name", "cust_name", "dimension", "appid"):
                if key in fm:
                    params[key] = fm[key]
        return params

    def _build_conversation(self, session_id: str) -> tuple:
        turns = self.memory.get_context(session_id, last_n=20)
        if not turns:
            return "", {}

        # 按 importance DESC, turn_index DESC 排序
        turns = sorted(turns, key=lambda t: (-t.get("importance", 1), -t["turn_index"]))

        max_idx = max(t["turn_index"] for t in turns)
        recent_turns = [t for t in turns if t["turn_index"] >= max_idx - 2]
        older_turns = [t for t in turns if t["turn_index"] < max_idx - 2]

        lines = []
        if recent_turns:
            lines.append("## 最近对话")
            for t in sorted(recent_turns, key=lambda x: x["turn_index"]):
                query = t.get("user_query", "")
                if query:
                    lines.append(f"用户: {query}")
                params = t.get("parsed_params", {})
                if params:
                    lines.append(f"解析: {self._params_to_text(params)}")

        if older_turns:
            try:
                summaries = self.memory.get_summaries(session_id)
                if summaries:
                    lines.append("## 历史摘要")
                    for s in summaries[-3:]:
                        content = s.get("content", "")
                        if isinstance(content, dict):
                            content = content.get("summary", str(content))
                        lines.append(str(content)[:300])
            except (AttributeError, Exception):
                pass

        resolved = {}
        if recent_turns:
            last = recent_turns[0]
            params = last.get("parsed_params", {})
            if not params:
                for t in recent_turns:
                    if t.get("parsed_params"):
                        params = t["parsed_params"]
                        break
            for key in ("product_type", "buy_sell", "bank_name", "cust_name", "dimension"):
                if key in params:
                    resolved[key] = params[key]

        # 语义检索：相似历史查询
        try:
            query_text = ""
            if turns:
                query_text = turns[-1].get("user_query", "") or ""
            if query_text:
                similar = self.memory.find_similar(query_text, limit=3)
                if similar:
                    lines.append("## 相似历史查询")
                    for s in similar:
                        if isinstance(s, dict):
                            lines.append(f"- {s.get('user_query', '')[:80]} -> "
                                        f"{self._params_to_text(s.get('parsed_params', {}))}")
        except Exception:
            pass  # find_similar 不可用则跳过

        return "\n".join(lines), resolved

    def _build_agent_memory(self, session_id: str) -> str:
        try:
            from agent.memory import AgentMemory as AgentMem
            mem = AgentMem()
            return mem.build_context_prompt(session_id) or ""
        except Exception:
            return ""

    @staticmethod
    def _params_to_text(params: dict) -> str:
        parts = []
        for k, v in params.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (str, int, float)):
                parts.append(f"{k}={v}")
        return ", ".join(parts)
