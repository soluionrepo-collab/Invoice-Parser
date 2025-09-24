from urllib.parse import urlparse
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from config.config import Config
from src.adapters.logger import logger
from azure.core.exceptions import ResourceNotFoundError, AzureError


class DocumentIntelligence:
    """
    Async wrapper around azure.ai.documentintelligence.aio.DocumentIntelligenceClient.
    Provides an async `extract_content_async` method which returns the AnalyzeResult
    (same shape as the sync SDK's result).
    """

    def __init__(self):
        self.client = DocumentIntelligenceClient(endpoint=Config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT, 
                                                 credential=AzureKeyCredential(Config.AZURE_DOCUMENT_INTELLIGENCE_KEY))

    async def extract_content_async(self, pdf_bytes: bytes, model_id: str = None):
        """
        Try to analyze document bytes. If model_id is given, try it first.
        Otherwise try a sensible ordered list of prebuilt models for invoice/document parsing.
        Returns AnalyzeResult on success or raises AzureError with helpful message.
        """
        if not isinstance(pdf_bytes, (bytes, bytearray)):
            raise TypeError("extract_content_async expects raw bytes of the document")

        # Candidate models to try (order: invoice-specific first, then generic document/layout)
        candidates = []
        if model_id:
            candidates.append(model_id)
        # Common prebuilt models - try invoice first since you parse invoices
        candidates += [
            "prebuilt-layout",
        ]

        for m in candidates:
            try:
                logger.info(f"[DI] attempting analyze with model='{m}'")
                # Use keyword `body` because SDK may expect that param name
                poller = await self.client.begin_analyze_document(model_id=m, body=pdf_bytes)
                result = await poller.result()
                logger.info(f"[DI] analyze succeeded with model='{m}'")
                return result
            except ResourceNotFoundError as e:
                # Model not found on this resource - record and try next candidate
                logger.warning(f"[DI] model '{m}' not found on resource: {str(e)}")
                last_exc = e
                continue
            except AzureError as e:
                # Other Azure errors (auth, throttling, network). stop and raise so caller sees meaningful error.
                logger.error(f"[DI] analyze failed with model='{m}': {e}", exc_info=True)
                raise
            except Exception as e:
                # Unexpected local error - bubble up
                logger.error(f"[DI] unexpected error analyzing with model='{m}': {e}", exc_info=True)
                raise

    async def begin_analyze_async(self, pdf_bytes: bytes, model_id: str = "prebuilt-layout"):
        """
        Start an analyze_document call and return the poller immediately.
        Caller is responsible for awaiting poller.result() later.
        This lets callers start many analyzes quickly and await them concurrently.
        """
        if not isinstance(pdf_bytes, (bytes, bytearray)):
            raise TypeError("begin_analyze_async expects raw bytes of the document")

        try:
            logger.info(f"[DI] begin analyze (async) with model='{model_id}'")
            poller = await self.client.begin_analyze_document(model_id=model_id, body=pdf_bytes)
            return poller
        except ResourceNotFoundError as e:
            logger.warning(f"[DI] model '{model_id}' not found on resource: {str(e)}")
            raise
        except AzureError as e:
            logger.error(f"[DI] begin analyze failed: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"[DI] unexpected begin analyze error: {e}", exc_info=True)
            raise

        
    async def close(self):
        """Close the underlying client (recommended on shutdown)."""
        try:
            await self.client.close()
        except Exception:
            pass
  

    
async_document_intelligence_client = DocumentIntelligence()