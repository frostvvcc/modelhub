import os
from typing import Any, List, Optional
from llama_index.core.bridge.pydantic import Field, PrivateAttr
from llama_index.core.embeddings import BaseEmbedding
from openai import OpenAI
import asyncio  # 添加 asyncio 导入
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 嵌入模型封装类
class ChatEmbeddings(BaseEmbedding):
    model: str = Field(description="使用的词嵌入模型")
    api_key: str = Field(description="API key.")
    base_url: str = Field(description="Base Url")
    reuse_client: bool = Field(default=True, description=(
        "Reuse the client between requests. When doing anything with large "
        "volumes of async API calls, setting this to false can improve stability."
    ),
                               )
    _client: Optional[Any] = PrivateAttr()

    # 初始化函数
    def __init__(
            self,
            model: str,
            api_key: Optional[str],
            base_url: Optional[str],
            reuse_client: bool = True,
            **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            reuse_client=reuse_client,
            **kwargs,
        )
        self._client = None

    # 客户端管理
    def _get_client(self) -> OpenAI:
        if not self.reuse_client:
            return OpenAI(api_key=self.api_key, base_url=self.base_url)

        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @classmethod
    def class_name(cls) -> str:
        return "ChatEmbeddings"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def get_general_text_embedding(
        self, prompt: str, input_type: str = "document",
    ) -> List[float]:
        kwargs: dict = {"model": self.model, "input": prompt}
        if self.model.startswith("text-embedding"):
            kwargs["extra_body"] = {"input_type": input_type}
        response = self._get_client().embeddings.create(**kwargs)
        return response.data[0].embedding

    def get_query_embedding(self, query: str) -> List[float]:
        return self.get_general_text_embedding(query, input_type="query")

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._get_text_embeddings(texts)

    def _get_text_embedding(self, text: str) -> List[float]:
        return self.get_general_text_embedding(text, input_type="document")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        batch_size = 20
        all_embeddings: List[List[float]] = []
        extra_body = (
            {"input_type": "document"}
            if self.model.startswith("text-embedding")
            else None
        )
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            kwargs: dict = {"model": self.model, "input": batch}
            if extra_body:
                kwargs["extra_body"] = extra_body
            response = self._get_client().embeddings.create(**kwargs)
            batch_embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
            all_embeddings.extend(batch_embeddings)
        return all_embeddings

    def _get_query_embedding(self, query: str) -> List[float]:
        return self.get_general_text_embedding(query, input_type="query")

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await asyncio.to_thread(
            self.get_general_text_embedding, query, "query",
        )

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return await asyncio.to_thread(
            self.get_general_text_embedding, text, "document",
        )

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)


if __name__ == "__main__":
    test_embedding = ChatEmbeddings(
        model="text-embedding-v3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=os.getenv("DASHSCOPE_API_KEY", "")
    )
    print(len(test_embedding.get_general_text_embedding('test')))
