from config.config import Config
from openai import AsyncAzureOpenAI
import time
from typing import Any
import random
import asyncio
from src.adapters.logger import logger 
from src.models import AzureResponseModel

class AsyncAzureOpenAIHelper:
    def __init__(self):
        self.client = AsyncAzureOpenAI(
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_key=Config.AZURE_OPENAI_KEY,
            api_version=Config.AZURE_OPENAI_VERSION,
        )
        logger.info(f"Initialized AsyncAzureOpenAIHelper with endpoint {Config.AZURE_OPENAI_ENDPOINT}")

    async def get_response(
        self,
        system_prompt: str,
        user_prompt: Any,
        model: str ,
        json_mode: bool = False,
        retries: int = 3,
    ) -> AzureResponseModel:
        """
        Sends a chat completion request to Azure OpenAI asynchronously and returns the response.

        This method attempts to send a request up to `retries` times in case of failure,
        applying exponential backoff between attempts. It logs request attempts, response times,
        token usage, and any errors encountered.

        Parameters:
            system_prompt (str): The system-level instructions or context for the model.
            user_prompt (ANY): The user's message or query to be sent to the model.
            json_mode (bool, optional): If True, request the response in structured JSON format. Defaults to False.
            model (str, optional): The Azure OpenAI model to use for generation. Defaults to `Config.GPT_GENERATION_4O_MINI_MODEL`.
            retries (int, optional): Number of retry attempts in case of failure. Defaults to 3.

        Returns:
            AzureResponseModel: A Pydantic model containing:
                - content (str): The text content of the response.
                - input_tokens (int): Number of tokens in the input prompt.
                - output_tokens (int): Number of tokens in the generated completion.
                - latency_seconds (Optional[float]): Time taken for the request in seconds.
        """

        input_tokens, output_tokens = 0, 0

        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Attempt {attempt}: Sending request to Azure OpenAI")
                start = time.time()
                response = await self.client.chat.completions.create(
                    model=model,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    top_p=0.8,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                end = time.time()
                latency = end - start
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens

                logger.info(
                    f"Received response in {latency:.2f}s | "
                    f"input_tokens={input_tokens}, output_tokens={output_tokens}"
                )

                return AzureResponseModel(
                    content=response.choices[0].message.content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_seconds=latency,
                )

            except Exception as ex:
                logger.error(f"Attempt {attempt} failed: {ex}", exc_info=True)
                backoff = (2**attempt) + random.random()
                logger.info(f"Retrying after {backoff:.2f}s...")
                await asyncio.sleep(backoff)

        logger.critical("Azure OpenAI not responding after all retries")
        raise RuntimeError("Azure OpenAI not responding after all retries")

async_openai_client = AsyncAzureOpenAIHelper()
